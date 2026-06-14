"""Rank-objective Monte Carlo: the principled version of all the league-aware
heuristics. Simulate one round's points for every manager using SHARED per-match
scoreline draws, so players in the same match (and a team's clean sheet vs its
opponent's attackers) are correlated for free. Then score each of the 6 squads
and count P(you finish strictly 1st, ties split).

It re-ranks the top transfer plans / captain picks by simulated P(win) — the
actual objective the cover/differential/variance/EO terms only approximate.

Design (deliberately bounded): the HIGH-variance, correlation-bearing components
(goals, assists, clean sheet, concede) are simulated from the shared scoreline;
the low-variance ones (appearance, saves, set-piece duty, MotM) enter at their
expected value. Goal/assist means and the clean-sheet probability match the model
exactly, so this adds variance + correlation without shifting the level.
"""
import numpy as np

from src import config, optimizer

_GOAL = config.SCORING["goal"]
_CS = config.SCORING["clean_sheet"]
_CONC = config.SCORING["concede_per2"]
_ASSIST = config.SCORING["assist"]


def _thin(counts: np.ndarray, weights: list[tuple], total_rate: float, rng) -> dict:
    """Multinomial allocation of `counts` events among weighted recipients via
    sequential binomial thinning (vectorised over sims). weights: [(id, rate)].
    `total_rate` is the team's mean (so each recipient's share = rate/total)."""
    out = {}
    remaining = counts.astype(np.int64)
    rem_p = 1.0
    for pid, rate in weights:
        p = min(rate / total_rate, rem_p) if total_rate > 0 else 0.0
        if p <= 0 or rem_p <= 1e-9:
            out[pid] = np.zeros_like(remaining)
            continue
        drawn = rng.binomial(remaining, min(p / rem_p, 1.0))
        out[pid] = drawn
        remaining = remaining - drawn
        rem_p -= p
    return out


def simulate_player_points(proj, fixtures_next, ids, n_sims=6000, seed=12345) -> dict:
    """{player id -> array[n_sims] of simulated round points} for the given ids,
    using one shared scoreline draw per match."""
    rng = np.random.default_rng(seed)
    ids = [i for i in ids if i in proj.index]
    pts = {i: np.zeros(n_sims) for i in ids}
    by_team = {}
    for i in ids:
        by_team.setdefault(proj.loc[i, "team"], []).append(i)

    def _f(i, col):
        v = proj.loc[i, col]
        return float(v) if v == v else 0.0      # NaN -> 0

    for fx in fixtures_next or []:
        mu_h, mu_a = fx.get("mu_home"), fx.get("mu_away")
        if mu_h is None or mu_a is None:
            continue
        gh = rng.poisson(max(mu_h, 1e-6), n_sims)
        ga = rng.poisson(max(mu_a, 1e-6), n_sims)
        for team, mu_team, team_goals, opp_goals in (
                (fx["home"], mu_h, gh, ga), (fx["away"], mu_a, ga, gh)):
            owned = by_team.get(team, [])
            if not owned:
                continue
            goals = _thin(team_goals, sorted(((i, _f(i, "xg")) for i in owned),
                                             key=lambda x: -x[1]), mu_team, rng)
            assist_events = rng.binomial(team_goals.astype(np.int64), config.ASSISTED_GOAL_SHARE)
            assists = _thin(assist_events, sorted(((i, _f(i, "xa")) for i in owned),
                                                  key=lambda x: -x[1]),
                            max(config.ASSISTED_GOAL_SHARE * mu_team, 1e-6), rng)
            cs = (opp_goals == 0).astype(float)
            conceded = (opp_goals // 2).astype(float)
            for i in owned:
                pos = proj.loc[i, "position"]
                ps = _f(i, "p_start")
                hm = _f(i, "heat_mult") or 1.0          # heat scales attacking output
                low = _f(i, "pts_appear") + _f(i, "pts_saves") + _f(i, "pts_duty") + _f(i, "pts_motm") - 0.25
                pts[i] = (pts[i] + low
                          + goals[i] * _GOAL.get(pos, 0) * hm
                          + assists[i] * _ASSIST * hm
                          + cs * ps * _CS.get(pos, 0)
                          - conceded * _CONC.get(pos, 0) * ps)
    return pts


def _squad_total(pts: dict, xi_ids: list, captain_id, n_sims: int) -> np.ndarray:
    tot = np.zeros(n_sims)
    for i in xi_ids:
        if i in pts:
            tot = tot + pts[i]
    if captain_id in pts:
        tot = tot + pts[captain_id]              # captain doubled (×2 - 1 extra)
    return tot


def win_probability(my_total: np.ndarray, rival_totals: list[np.ndarray]) -> float:
    """P(my_total strictly highest, ties split evenly)."""
    if not rival_totals:
        return 1.0
    stack = np.vstack([my_total] + rival_totals)
    mx = stack.max(axis=0)
    is_max = stack == mx
    counts = is_max.sum(axis=0)
    return float((is_max[0] / counts).mean())


def rank_plans_by_win(proj, plans, my_squad_ids, rival_squads, rival_captains,
                      regime=None, field_own=None, n_sims=6000, fixtures=None):
    """Re-rank transfer `plans` by simulated P(you finish 1st) vs the field's
    actual squads. Attaches `p_win` to each plan and returns them sorted. The
    rivals' point arrays are simulated ONCE; each plan is then a cheap re-sum."""
    fixtures_next = fixtures if fixtures is not None else proj.attrs.get("fixtures_next", [])
    if not fixtures_next or not rival_squads:
        return plans
    rival_sets = [set(s) for s in rival_squads]
    all_ids = set(my_squad_ids)
    for p in plans:
        all_ids.update(p.get("in_ids", []))
    for s in rival_sets:
        all_ids.update(s)
    pts = simulate_player_points(proj, fixtures_next, list(all_ids), n_sims)
    if not pts:
        return plans

    rival_totals = []
    for k, s in enumerate(rival_sets):
        owned = proj.loc[[i for i in s if i in proj.index]]
        if len(owned) < 11:
            continue
        xi = optimizer.best_xi(owned, "xp_next")
        cap = rival_captains[k] if rival_captains and k < len(rival_captains) \
            and rival_captains[k] in set(xi["xi_ids"]) else xi["captain_id"]
        rival_totals.append(_squad_total(pts, xi["xi_ids"], cap, n_sims))

    base = list(my_squad_ids)
    for p in plans:
        squad = [i for i in base if i not in p.get("out_ids", [])] + p.get("in_ids", [])
        owned = proj.loc[[i for i in squad if i in proj.index]]
        if len(owned) < 11:
            p["p_win"] = None
            continue
        xi = optimizer.best_xi(owned, "xp_next")
        xidf = owned.loc[[i for i in xi["xi_ids"] if i in owned.index]]
        cap, _ = optimizer.choose_captain(xidf, regime, field_own, "xp_next")
        cap = cap or xi["captain_id"]
        my_total = _squad_total(pts, xi["xi_ids"], cap, n_sims)
        p["p_win"] = round(win_probability(my_total, rival_totals), 4)
    ranked = sorted([p for p in plans if p.get("p_win") is not None],
                    key=lambda p: p["p_win"], reverse=True)
    return ranked + [p for p in plans if p.get("p_win") is None]
