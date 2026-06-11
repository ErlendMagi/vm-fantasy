"""Tournament advancement probabilities.

Group stage: vectorized Monte Carlo over remaining group matches using
odds-implied Poisson scorelines (completed matches enter deterministically).
2026 format: 12 groups of 4; top 2 plus the 8 best third-placed teams -> R32.

Knockouts: the R32 bracket mapping is a seeding labyrinth, so instead of
simulating it we propagate P(reach round) with Bradley-Terry win probabilities
against the strength-weighted average surviving opponent, normalized so the
expected team count per round is exact (32 -> 16 -> 8 -> 4 -> 2 -> 1).
"""
import numpy as np
import pandas as pd

from src import config, projections

ROUND_TARGETS = [("R16", 16), ("QF", 8), ("SF", 4), ("F", 2), ("WIN", 1)]


def _scale_capped(raw: np.ndarray, caps: np.ndarray, target: float) -> np.ndarray:
    """Scale `raw` to sum exactly `target` without any element exceeding its cap
    (water-filling: clipped elements sit at their cap, the rest share the
    remaining budget proportionally)."""
    raw = np.asarray(raw, dtype=float)
    caps = np.asarray(caps, dtype=float)
    clipped = np.zeros(raw.shape, dtype=bool)
    out = raw.copy()
    for _ in range(raw.size):
        budget = target - caps[clipped].sum()
        free_raw = raw[~clipped].sum()
        if budget <= 0 or free_raw <= 0:
            out[~clipped] = 0.0
            break
        out = np.where(clipped, caps, raw * (budget / free_raw))
        newly = (out > caps + 1e-12) & ~clipped
        if not newly.any():
            break
        clipped |= newly
    return np.minimum(out, caps)


def advancement_table(fixtures: list[dict], match_odds: dict | None,
                      outrights: dict | None, n_sims: int = config.MC_SIMS,
                      seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    group_matches = [m for m in fixtures if m.get("stage") == "group"]
    strengths = projections.team_strengths(outrights)
    remaining = [m for m in group_matches if m.get("status") != "finished"]
    mus = projections.fixture_mus(remaining, match_odds, strengths)

    groups: dict[str, list[str]] = {}
    for m in group_matches:
        g = groups.setdefault(m["group"], [])
        for t in (m["home"], m["away"]):
            if t not in g:
                g.append(t)

    adv_direct: dict[str, np.ndarray] = {}   # team -> bool (n_sims,) finished top-2
    third_keys, third_teams = [], []          # per group: (n_sims,) sort key + team index per sim
    for g, teams in sorted(groups.items()):
        idx = {t: i for i, t in enumerate(teams)}
        pts = np.zeros((n_sims, 4))
        gd = np.zeros((n_sims, 4))
        gf = np.zeros((n_sims, 4))
        for m in (x for x in group_matches if x["group"] == g):
            i, j = idx[m["home"]], idx[m["away"]]
            if m.get("status") == "finished" and m.get("score_home") is not None:
                hg = np.full(n_sims, m["score_home"])
                ag = np.full(n_sims, m["score_away"])
            else:
                mu = mus[m["match_id"]]
                hg = rng.poisson(mu["mu_home"], n_sims)
                ag = rng.poisson(mu["mu_away"], n_sims)
            pts[:, i] += 3 * (hg > ag) + (hg == ag)
            pts[:, j] += 3 * (ag > hg) + (hg == ag)
            gd[:, i] += hg - ag
            gd[:, j] += ag - hg
            gf[:, i] += hg
            gf[:, j] += ag
        # composite rank key, comparable across groups; tiny noise breaks ties
        key = pts * 1e6 + (gd + 100) * 1e3 + gf + rng.random((n_sims, 4))
        order = np.argsort(-key, axis=1)
        for t, i in idx.items():
            adv_direct[t] = (order[:, 0] == i) | (order[:, 1] == i)
        third = order[:, 2]
        third_keys.append(key[np.arange(n_sims), third])
        third_teams.append(np.array([teams[t] for t in third], dtype=object))

    # best 8 third-placed teams across the 12 groups
    tk = np.stack(third_keys, axis=1)                      # (n_sims, 12)
    cutoff = np.sort(tk, axis=1)[:, -8]                    # 8th best key per sim
    qualifies = tk >= cutoff[:, None]
    p_r32 = {}
    all_teams = [t for ts in groups.values() for t in ts]
    tt = np.stack(third_teams, axis=1)                     # (n_sims, 12) team names
    for t in all_teams:
        as_third = ((tt == t) & qualifies).any(axis=1)
        p_r32[t] = float((adv_direct[t] | as_third).mean())

    df = pd.DataFrame(index=sorted(all_teams))
    df["R32"] = pd.Series(p_r32)

    s = pd.Series({t: strengths.get(t, np.nan) for t in df.index})
    s = s.fillna(s.min() / 2 if s.notna().any() else 1.0)
    p_reach = df["R32"].to_numpy().astype(float)
    sv = s.to_numpy()
    for col, target in ROUND_TARGETS:
        denom = p_reach.sum()
        s_bar = (p_reach * sv).sum() / denom if denom > 0 else sv.mean()
        p_win = sv / (sv + s_bar)
        p_next = _scale_capped(p_reach * p_win, p_reach, target)
        df[col] = p_next
        p_reach = p_next
    return df


def p_plays_lookup(adv: pd.DataFrame, max_round: int = 8) -> dict[tuple[str, int], float]:
    """(team, fantasy_round) -> P(team plays a match that round).
    Rounds 1-3: every team plays all 3 group games. Round 8 hosts both the
    final and the third-place match, so all 4 semifinalists play it."""
    col_for_round = {4: "R32", 5: "R16", 6: "QF", 7: "SF", 8: "SF"}
    out = {}
    for team in adv.index:
        for r in range(1, max_round + 1):
            out[(team, r)] = 1.0 if r <= 3 else float(adv.loc[team, col_for_round[r]])
    return out
