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
                adj = _f(i, "cal_adj") or 1.0           # SAME calibration the projection applies
                low = _f(i, "pts_appear") + _f(i, "pts_saves") + _f(i, "pts_duty") + _f(i, "pts_motm") - 0.25
                # `low` is read from already-calibrated columns; the scoreline terms are
                # recomputed from raw xg/xa, so scale only those by adj to match xp_next
                # (else the sim carries a position-systematic bias vs the rest of the model).
                pts[i] = (pts[i] + low
                          + adj * (goals[i] * _GOAL.get(pos, 0) * hm
                                   + assists[i] * _ASSIST * hm
                                   + cs * ps * _CS.get(pos, 0)
                                   - conceded * _CONC.get(pos, 0) * ps))
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


def _final_standing(pts, owned, xi_ids, cap, current, rl_sqrt, n_sims):
    """A manager's simulated FINAL cumulative total = current points + expected
    rest-of-cup points + tournament-scaled round-to-round noise. The shared next-round
    Monte Carlo supplies correlated variance; we centre it (subtract its own mean) and
    scale the spread by sqrt(rounds_left) to approximate the variance of ALL remaining
    rounds, while the drift (the mean) is the whole-cup expectation xp_tournament. This
    turns 'P(win next week)' into 'P(finish 1st at the final whistle)'."""
    sim_next = _squad_total(pts, xi_ids, cap, n_sims)
    have = [i for i in xi_ids if i in owned.index]
    mean_next = float(owned.loc[have, "xp_next"].sum()) + (float(owned.loc[cap, "xp_next"])
                                                           if cap in owned.index else 0.0)
    mean_rest = optimizer.squad_xp(owned, "xp_tournament")     # expected TOTAL remaining points
    return current + mean_rest + (sim_next - mean_next) * rl_sqrt


def _rival_finals(proj, rival_sets, rival_captains, pts, n_sims, title, rl_sqrt, rival_current):
    """Each rival's simulated final-standing (or next-round) array, simulated once."""
    out = []
    for k, s in enumerate(rival_sets):
        owned = proj.loc[[i for i in s if i in proj.index]]
        if len(owned) < 11:
            continue
        xi = optimizer.best_xi(owned, "xp_next")
        cap = rival_captains[k] if rival_captains and k < len(rival_captains) \
            and rival_captains[k] in set(xi["xi_ids"]) else xi["captain_id"]
        cur = (rival_current[k] if title and rival_current and k < len(rival_current) else 0.0)
        out.append(_final_standing(pts, owned, xi["xi_ids"], cap, cur, rl_sqrt, n_sims)
                   if title else _squad_total(pts, xi["xi_ids"], cap, n_sims))
    return out


def formation_win_probs(proj, squad_ids, fixtures, rival_squads, rival_captains,
                        regime=None, field_own=None, n_sims=6000,
                        my_current=0.0, rival_current=None, rounds_left=1):
    """For a FIXED squad, P(finish 1st) under EACH valid formation — so the applied XI
    and the finder field the shape that maximises the TITLE probability, not just
    expected points. Returns [{formation, p_win, xi_ids, captain_id, vice_id, total}]
    best-p_win first. Reuses one shared scoreline draw across all formations + rivals."""
    owned = proj.loc[[i for i in squad_ids if i in proj.index]]
    forms = optimizer.formation_options(owned, "xp_next", p_start_floor=config.XI_PSTART_FLOOR)
    if not forms or not fixtures or not rival_squads:
        return []
    title = rival_current is not None
    rl_sqrt = max(float(rounds_left), 1.0) ** 0.5 if title else 1.0
    rival_sets = [set(s) for s in rival_squads]
    all_ids = set(squad_ids)
    for s in rival_sets:
        all_ids.update(s)
    pts = simulate_player_points(proj, fixtures, sorted(all_ids), n_sims)
    if not pts:
        return []
    rival_sims = _rival_finals(proj, rival_sets, rival_captains, pts, n_sims, title, rl_sqrt, rival_current)
    out = []
    for f in forms:
        xi_ids = [i for i in f["xi_ids"] if i in owned.index]
        if len(xi_ids) < 11:
            continue
        cap, vice = optimizer.choose_captain(owned.loc[xi_ids], regime, field_own, "xp_next")
        cap = cap or xi_ids[0]
        my_final = (_final_standing(pts, owned, xi_ids, cap, my_current, rl_sqrt, n_sims) if title
                    else _squad_total(pts, xi_ids, cap, n_sims))
        out.append({"formation": f["formation"], "p_win": round(win_probability(my_final, rival_sims), 4),
                    "xi_ids": xi_ids, "captain_id": cap, "vice_id": vice, "total": f["total"]})
    if not out:
        return out
    out.sort(key=lambda r: -r["p_win"])
    # robust pick: among formations whose P(title) ties the best (within the MC-noise band),
    # take the highest EXPECTED POINTS — so a flat-p_win race (e.g. far ahead/behind) keeps the
    # EV-best shape, and p_win only overrides EV when a formation is genuinely better.
    _max = out[0]["p_win"]
    pick = max((r for r in out if r["p_win"] >= _max - config.PWIN_FORMATION_BAND), key=lambda r: r["total"])
    return [pick] + [r for r in out if r is not pick]


def rank_plans_by_win(proj, plans, my_squad_ids, rival_squads, rival_captains,
                      regime=None, field_own=None, n_sims=6000, fixtures=None,
                      my_current=0.0, rival_current=None, rounds_left=1):
    """Re-rank transfer `plans` by simulated P(you finish 1st) vs the field's actual
    squads. When `rival_current` (each rival's CURRENT points, aligned with rival_squads)
    is given, the objective is the TITLE: P(your final cumulative total is highest),
    folding in the standings gap, the rest of the cup, and tournament-scaled variance.
    Without it, it falls back to the legacy next-round-only comparison. Rivals are
    simulated ONCE; each plan is a cheap re-sum."""
    fixtures_next = fixtures if fixtures is not None else proj.attrs.get("fixtures_next", [])
    if not fixtures_next or not rival_squads:
        return plans
    title = rival_current is not None                          # standings-aware objective
    rl_sqrt = max(float(rounds_left), 1.0) ** 0.5 if title else 1.0
    rival_sets = [set(s) for s in rival_squads]
    all_ids = set(my_squad_ids)
    for p in plans:
        all_ids.update(p.get("in_ids", []))
    for s in rival_sets:
        all_ids.update(s)
    # sorted, not list(set): UUID set order is hash-randomised per process (no pinned
    # PYTHONHASHSEED), so list() would make the win-prob non-reproducible across runs.
    pts = simulate_player_points(proj, fixtures_next, sorted(all_ids), n_sims)
    if not pts:
        return plans

    rival_sims = _rival_finals(proj, rival_sets, rival_captains, pts, n_sims, title, rl_sqrt, rival_current)

    base = list(my_squad_ids)
    for p in plans:
        squad = [i for i in base if i not in p.get("out_ids", [])] + p.get("in_ids", [])
        owned = proj.loc[[i for i in squad if i in proj.index]]
        if len(owned) < 11:
            p["p_win"] = None
            continue
        # MY scored XI must equal the XI we'd actually field (floored to likely starters);
        # rivals stay un-floored (their real lineup) so p_win is honest.
        xi = optimizer.best_xi(owned, "xp_next", p_start_floor=config.XI_PSTART_FLOOR)
        xidf = owned.loc[[i for i in xi["xi_ids"] if i in owned.index]]
        cap, _ = optimizer.choose_captain(xidf, regime, field_own, "xp_next")
        cap = cap or xi["captain_id"]
        # the −4 hit is a real points cost — deduct it so the autopilot (max p_win)
        # can't auto-apply a title-probability-negative hit.
        if title:
            my_total = _final_standing(pts, owned, xi["xi_ids"], cap, my_current, rl_sqrt, n_sims) \
                - p.get("hit_cost", 0)
        else:
            my_total = _squad_total(pts, xi["xi_ids"], cap, n_sims) - p.get("hit_cost", 0)
        p["p_win"] = round(win_probability(my_total, rival_sims), 4)
    ranked = sorted([p for p in plans if p.get("p_win") is not None],
                    key=lambda p: p["p_win"], reverse=True)
    return ranked + [p for p in plans if p.get("p_win") is None]
