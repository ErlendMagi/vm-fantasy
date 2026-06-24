"""Best XI, captain and transfer search.

Squad value = best legal XI by projected points, captain counted double.
Transfer search is exhaustive over single swaps and pruned double swaps
(top candidates per position); a third transfer (-4 hit) is only recommended
when its marginal gain clears the hit cost plus a noise margin.
"""
from itertools import combinations

import pandas as pd

from src import config


def _pos_sorted(squad: pd.DataFrame, xp_col: str, p_start_floor: float | None) -> dict:
    """Per-position candidate frames, best-first. With p_start_floor set, LIKELY
    STARTERS (p_start >= floor) are ranked strictly ahead of below-floor players
    (then by xp WITHIN each tier) — so `head(n)` fills every slot with proven
    starters first and only ever dips below the floor for a slot that can't
    otherwise be filled, picking the best available filler. This is the iron
    'never bench a likely starter for a likely-benched one' guarantee, while never
    leaving a slot empty. Rivals are sorted without a floor (their real XI)."""
    out = {}
    for pos in ("GK", "DEF", "MID", "FWD"):
        sub = squad[squad["position"] == pos]
        if p_start_floor is not None and "p_start" in sub.columns:
            ok = (sub["p_start"] >= p_start_floor).astype(int)
            out[pos] = sub.assign(_ok=ok).sort_values(["_ok", xp_col], ascending=[False, False])
        else:
            out[pos] = sub.sort_values(xp_col, ascending=False)
    return out


def best_xi(squad: pd.DataFrame, xp_col: str = "xp_next", p_start_floor: float | None = None) -> dict:
    """squad: 15-row frame with position + xp_col. Returns XI ids, formation, captain
    and total (captain doubled). With p_start_floor set, likely starters are fielded
    ahead of likely-benched players (our fielding guarantee); rivals are scored
    without it (real XI)."""
    by_pos = _pos_sorted(squad, xp_col, p_start_floor)
    cands = []
    for d, m, f in config.FORMATIONS:
        if len(by_pos["DEF"]) < d or len(by_pos["MID"]) < m or len(by_pos["FWD"]) < f or by_pos["GK"].empty:
            continue
        xi = pd.concat([by_pos["GK"].head(1), by_pos["DEF"].head(d),
                        by_pos["MID"].head(m), by_pos["FWD"].head(f)])
        nben = int((xi["p_start"] < p_start_floor).sum()) if (p_start_floor is not None
                                                              and "p_start" in xi.columns) else 0
        cands.append((nben, float(xi[xp_col].sum()), config.formation_aggression(d, m, f), d, m, f, xi))
    if not cands:
        return {"xi_ids": [], "formation": "-", "xi_xp": 0.0, "captain_id": None,
                "captain_xp": 0.0, "total": 0.0}
    # PLAYTIME-FIRST, then EV: only consider shapes that field the FEWEST likely-benched
    # players (never trade a sure starter for an unproven one to chase points). Among those,
    # EV-max; within FORMATION_TIE_EPS of the best, take the most aggressive (higher ceiling).
    min_nben = min(c[0] for c in cands)
    elig = [c for c in cands if c[0] == min_nben]
    best_total = max(c[1] for c in elig)
    _nb, total, _aggr, d, m, f, xi = max((c for c in elig if c[1] >= best_total - config.FORMATION_TIE_EPS),
                                         key=lambda c: (c[2], c[1]))
    best = {"xi_ids": list(xi["id"]), "formation": f"{d}-{m}-{f}", "xi_xp": total,
            "captain_id": xi.loc[xi[xp_col].idxmax(), "id"], "captain_xp": float(xi[xp_col].max())}
    best["total"] = best["xi_xp"] + (config.CAPTAIN_MULTIPLIER - 1) * best["captain_xp"]
    return best


def squad_xp(squad: pd.DataFrame, xp_col: str = "xp_next", p_start_floor: float | None = None) -> float:
    return best_xi(squad, xp_col, p_start_floor=p_start_floor)["total"]


def _pareto_buyable(pool: pd.DataFrame, xp_col: str) -> pd.DataFrame:
    """Drop value-DOMINATED buy candidates: remove a player A if some other SAME-POSITION player B
    is no more expensive, at least as likely to start, AND at least as good on both next-round and
    whole-tournament value (strictly better on >=1 axis). You'd never pick A over B, so it never
    reaches the search — 'no worse player at the same/higher price'. The price/value frontier (cheap
    enablers ... stars), spread across teams, is preserved, so diversification options remain."""
    tour = "xp_tournament" if "xp_tournament" in pool.columns else xp_col
    has_ps = "p_start" in pool.columns
    keep = []
    for pos in pool["position"].unique():
        sub = pool[pool["position"] == pos]
        pr = sub["price"].to_numpy(float); xn = sub[xp_col].to_numpy(float)
        xt = sub[tour].to_numpy(float)
        ps = (sub["p_start"].to_numpy(float) if has_ps else None)
        idx = sub.index.to_numpy()
        for a in range(len(sub)):
            dominated = False
            for b in range(len(sub)):
                if a == b:
                    continue
                if (pr[b] <= pr[a] + 1e-9 and xn[b] >= xn[a] - 1e-9 and xt[b] >= xt[a] - 1e-9
                        and (ps is None or ps[b] >= ps[a] - 1e-9)
                        and (pr[b] < pr[a] - 1e-9 or xn[b] > xn[a] + 1e-9 or xt[b] > xt[a] + 1e-9
                             or (ps is not None and ps[b] > ps[a] + 1e-9))):
                    dominated = True
                    break
            if not dominated:
                keep.append(idx[a])
    return pool.loc[keep]


def formation_options(squad: pd.DataFrame, xp_col: str = "xp_next",
                      p_start_floor: float | None = None) -> list[dict]:
    """Projected points of the best XI under EVERY formation the game accepts that
    this squad can actually field, captain doubled — so you can SEE which shape wins
    and by how much. The model always fields the top one; you set it on TV2 simply
    by which 11 you start. Sorted best-first. With p_start_floor, only likely starters
    are eligible to field (the playtime guarantee)."""
    by_pos = _pos_sorted(squad, xp_col, p_start_floor)
    out = []
    for d, m, f in config.FORMATIONS:
        if len(by_pos["DEF"]) < d or len(by_pos["MID"]) < m or len(by_pos["FWD"]) < f or by_pos["GK"].empty:
            continue
        xi = pd.concat([by_pos["GK"].head(1), by_pos["DEF"].head(d),
                        by_pos["MID"].head(m), by_pos["FWD"].head(f)])
        xi_xp = float(xi[xp_col].sum())
        cap_xp = float(xi[xp_col].max())
        _t = xi_xp + (config.CAPTAIN_MULTIPLIER - 1) * cap_xp     # UNROUNDED total, for banding
        nben = int((xi["p_start"] < p_start_floor).sum()) if (p_start_floor is not None
                                                              and "p_start" in xi.columns) else 0
        out.append({"formation": f"{d}-{m}-{f}", "xi_xp": round(xi_xp, 2),
                    "total": round(_t, 2), "_t": _t, "_nben": nben,
                    "aggression": config.formation_aggression(d, m, f), "xi_ids": list(xi["id"])})
    if not out:
        return out
    # PLAYTIME-FIRST: a shape that fields a likely-benched player is only chosen when NO
    # shape can field 11 likely starters — we never trade a sure starter for an unproven one
    # to chase a sliver of points. Among the fewest-benched shapes, rank by EV; band +
    # aggression-float on the SAME unrounded total best_xi uses, so the headlined formation
    # always equals the shape best_xi fields (rounding could otherwise disagree).
    out.sort(key=lambda r: (r["_nben"], -r["_t"]))
    min_nben = out[0]["_nben"]
    elig = [r for r in out if r["_nben"] == min_nben]
    top = elig[0]["_t"]
    lead = sorted([r for r in elig if r["_t"] >= top - config.FORMATION_TIE_EPS],
                  key=lambda r: -r["aggression"])
    return lead + [r for r in out if r not in lead]


def captain_options(squad: pd.DataFrame, xp_col: str = "xp_next", n: int = 3,
                    regime: str | None = None, field_own: dict | None = None,
                    p_start_floor: float | None = config.XI_PSTART_FLOOR) -> pd.DataFrame:
    """Top captain candidates ranked the way the autopilot ACTUALLY picks the
    armband (availability-weighted EV, regime tilt), restricted to the FIELDED (floored)
    starting XI — so this table agrees with choose_captain / rank_sim / what gets written
    to TV2, instead of a raw xp argmax that could headline a likely-benched player.
    The model's chosen captain (🟠 C) and vice (🔵 V) float to the top."""
    xi_ids = [i for i in best_xi(squad, xp_col, p_start_floor=p_start_floor)["xi_ids"] if i in squad.index]
    if not xi_ids:
        return squad.head(0)
    xi = squad.loc[xi_ids].copy()
    cap, vice = choose_captain(xi, regime=regime, field_own=field_own, value_col=xp_col)
    pp = xi.get("p_play", pd.Series(0.85, index=xi.index)).fillna(0.85)
    xi["cap_ev"] = (xi[xp_col].clip(lower=0) * pp).round(2)        # availability-weighted EV
    order = xi.sort_values("cap_ev", ascending=False).index.tolist()
    front = [i for i in (cap, vice) if i in xi.index]              # armband + vice always on top
    xi = xi.loc[front + [i for i in order if i not in front]]
    xi["armband"] = ["🟠 C" if i == cap else ("🔵 V" if i == vice else "") for i in xi.index]
    cols = [c for c in ["armband", "name", "team", "position", "opponent", xp_col, "p_play", "cap_ev"]
            if c in xi.columns]
    return xi.head(n)[cols]


def choose_captain(xi: pd.DataFrame, regime: str | None = None, field_own: dict | None = None,
                   value_col: str = "xp_next") -> tuple:
    """Captain + vice for a starting XI. Safety first: never captain a player
    likely to be benched (the zero-double disaster), and put the vice in a
    DIFFERENT match so one flat fixture can't kill both. Regime tilt: a leader
    covers a widely-owned star (neutralises a rival's haul); a chaser allows a
    higher-ceiling differential. regime=None ≈ availability-weighted argmax."""
    if xi is None or len(xi) == 0:
        return None, None
    field_own = field_own or {}
    pp = xi.get("p_play", pd.Series(0.85, index=xi.index)).fillna(0.85)
    ps = xi.get("p_start", pd.Series(1.0, index=xi.index)).fillna(1.0)   # likely-starter gate
    base = xi[value_col].clip(lower=0)
    score = base * pp                                   # availability-weighted EV
    if regime == "leader" and field_own:
        own = pd.Series([field_own.get(i, 0.0) for i in xi.index], index=xi.index)
        score = score + config.CAPTAIN_COVER_BONUS * own * base
    elif regime == "chaser" and "ceiling" in xi.columns:
        score = score + 0.25 * xi["ceiling"].clip(lower=0)
    # correlation tilt: leader avoids stacking the armband onto an already-heavy
    # match (variance), chaser embraces it (ceiling)
    if regime in ("leader", "chaser") and "opponent" in xi.columns:
        match = {i: frozenset({xi.loc[i, "team"], xi.loc[i].get("opponent")}) for i in xi.index}
        stack = pd.Series([sum(base[j] for j in xi.index if j != i and match[j] == match[i])
                           for i in xi.index], index=xi.index)
        score = score + (-1.0 if regime == "leader" else 1.0) * config.CAPTAIN_CORR_W * stack
    # never captain a likely-benched OR unproven (0-minute) player: require BOTH the play
    # floor and the start floor, so an unproven p_play (0.45+0.12=0.57) can't sneak the armband.
    ok = (pp >= config.CAPTAIN_PPLAY_FLOOR) & (ps >= config.XI_PSTART_FLOOR)
    pool = score[ok] if ok.any() else score
    cap = pool.idxmax()

    def _match(i):
        return (xi.loc[i, "team"], xi.loc[i].get("opponent") if "opponent" in xi.columns else None)
    cap_match = _match(cap)
    order = score.drop(index=cap).sort_values(ascending=False)
    # vice must clear the SAME play floor as the captain (it inherits the armband if
    # the captain is a late scratch — a sub-floor vice reintroduces the zero-double
    # risk). Prefer a different match (so one flat fixture can't kill both), then
    # degrade safely rather than ever defaulting to a doubtful starter.
    floor = config.CAPTAIN_PPLAY_FLOOR

    def _pick(pred):
        return next((i for i in order.index if pred(i)), None)
    sfloor = config.XI_PSTART_FLOOR
    vice = (_pick(lambda i: _match(i) != cap_match and pp.get(i, 0) >= floor and ps.get(i, 1.0) >= sfloor)
            or _pick(lambda i: pp.get(i, 0) >= floor and ps.get(i, 1.0) >= sfloor)
            or _pick(lambda i: _match(i) != cap_match and pp.get(i, 0) >= floor)
            or _pick(lambda i: pp.get(i, 0) >= floor)
            or _pick(lambda i: _match(i) != cap_match)
            or (order.index[0] if len(order) else None))
    return cap, vice


def _fast_squad_value(ids: list[str], info: dict[str, tuple]) -> float:
    """squad_xp (best XI, captain doubled) MINUS a small penalty for money parked on
    the bench, on plain tuples — the transfer search calls this ~20k times, so no
    pandas. info[pid] = (pos, xp, price, team, p_start). The XI is scored only from
    LIKELY STARTERS (p_start >= XI_PSTART_FLOOR), ranked strictly ahead of below-floor
    players (then by xP within each tier) — the SAME tiered guarantee best_xi/compose_lineup
    field: a proven starter is never benched for a likely-benched one, and the search can't
    credit a buy it would actually bench, but a slot is never left empty. The bench penalty
    (over all 15) routes budget into the XI; the formation is still chosen by xP."""
    buckets = {"GK": [], "DEF": [], "MID": [], "FWD": []}     # (above_floor, xp, price)
    total_cost = 0.0
    n_dead = 0                                                # held players that can't be fielded
    for pid in ids:
        p = info[pid]
        ok = 1 if p[4] >= config.XI_PSTART_FLOOR else 0       # p[4] = p_start
        buckets[p[0]].append((ok, p[1], p[2]))
        total_cost += p[2]
        n_dead += 1 - ok
    # likely starters first, then by xP within each tier -> head(n) fills slots with
    # proven players and only dips below the floor when a slot can't otherwise be filled
    by_pos = {pos: [(xp, pr) for _ok, xp, pr in sorted(v, key=lambda t: (t[0], t[1]), reverse=True)]
              for pos, v in buckets.items()}
    if not by_pos["GK"]:
        return 0.0
    xpfx, ppfx = {}, {}
    for pos, v in by_pos.items():
        ax, ap, tx, tp = [0.0], [0.0], 0.0, 0.0
        for xp, pr in v:
            tx += xp
            tp += pr
            ax.append(tx)
            ap.append(tp)
        xpfx[pos], ppfx[pos] = ax, ap
    best_xp, best_xi_cost = 0.0, 0.0
    for d, m, f in config.FORMATIONS:
        if len(by_pos["DEF"]) < d or len(by_pos["MID"]) < m or len(by_pos["FWD"]) < f:
            continue
        val = by_pos["GK"][0][0] + xpfx["DEF"][d] + xpfx["MID"][m] + xpfx["FWD"][f]
        if val > best_xp:
            best_xp = val
            best_xi_cost = by_pos["GK"][0][1] + ppfx["DEF"][d] + ppfx["MID"][m] + ppfx["FWD"][f]
    if best_xp <= 0.0:
        return 0.0
    captain = max(by_pos["GK"][0][0],
                  by_pos["DEF"][0][0] if by_pos["DEF"] else 0.0,
                  by_pos["MID"][0][0] if by_pos["MID"] else 0.0,
                  by_pos["FWD"][0][0] if by_pos["FWD"] else 0.0)
    return (best_xp + (config.CAPTAIN_MULTIPLIER - 1) * captain
            - config.BENCH_COST_WEIGHT * (total_cost - best_xi_cost)
            - config.DEAD_WEIGHT_HELD_PENALTY * n_dead)        # shed un-fieldable non-mains


def enforce_proven_xi(squad_ids: list[str], proj: pd.DataFrame, bank: float,
                      max_swaps: int = 2, team_cap: int = config.MAX_PER_TEAM) -> tuple[list[str], list]:
    """CLEAN-XI guarantee (deterministic, bounded, no churn of proven players): while the best XI is
    FORCED to start a benched-tier player (p_start < XI_PSTART_FLOOR) for lack of proven starters,
    swap OUT the lowest whole-tournament-value dead/filler player and IN the best affordable proven,
    played-all, ≥4%-owned, non-dominated STARTER that removes a forced filler — chosen by highest
    WHOLE-TOURNAMENT value, so the addition is a main who'll still be scoring in the late rounds (we
    play for the title, not one round). Budget + per-nation cap respected; idempotent (no-op once the
    XI is clean or nothing safe is affordable). Returns (new_squad_ids, [(out_id, in_id), ...])."""
    squad, swaps, cur_bank = list(squad_ids), [], float(bank)
    floor = config.XI_PSTART_FLOOR
    for _ in range(max_swaps):
        owned = proj.loc[[i for i in squad if i in proj.index]]
        if len(owned) < 11:
            break
        xi = best_xi(owned, "xp_next", p_start_floor=floor)["xi_ids"]
        forced = [i for i in xi if owned.loc[i, "p_start"] < floor]
        if not forced:
            break                                          # XI already all proven starters
        pool = proj[(~proj.index.isin(squad)) & (proj.get("status", "available") != "out")]
        pool = pool[pool["p_start"] >= floor]              # the replacement must itself be a fieldable starter
        if config.REQUIRE_PLAYED_ALL and "played_all" in pool.columns and pool["played_all"].any():
            pool = pool[pool["played_all"]]
        if "ownership_pct" in pool.columns and pool["ownership_pct"].notna().any():
            pool = pool[pool["ownership_pct"].fillna(0.0) >= config.OWNERSHIP_MIN_BUY]
        if config.PRUNE_DOMINATED_BUYS and not pool.empty:
            pool = _pareto_buyable(pool, "xp_next")
        if pool.empty:
            break
        counts = owned["team"].value_counts().to_dict()
        dead = sorted((i for i in squad if proj.loc[i, "p_start"] < floor),
                      key=lambda i: float(proj.loc[i, "xp_tournament"]))   # sell the least valuable first
        best = None
        for out_id in dead:
            opos, out_team = proj.loc[out_id, "position"], proj.loc[out_id, "team"]
            budget = cur_bank + float(proj.loc[out_id, "price"])
            cands = pool[(pool["position"] == opos) & (pool["price"] <= budget + 1e-9)]
            for in_id, r in cands.iterrows():
                t = r["team"]
                if counts.get(t, 0) - (1 if out_team == t else 0) + 1 > team_cap:
                    continue                               # respect the per-nation cap
                trial = [i for i in squad if i != out_id] + [in_id]
                to = proj.loc[[i for i in trial if i in proj.index]]
                txi = best_xi(to, "xp_next", p_start_floor=floor)["xi_ids"]
                if sum(1 for i in txi if to.loc[i, "p_start"] < floor) < len(forced):
                    val = float(r["xp_tournament"])        # prefer the highest whole-tournament value add
                    if best is None or val > best[0]:
                        best = (val, out_id, in_id, trial, float(r["price"]))
        if best is None:
            break                                          # no affordable safe swap removes a forced filler
        _, out_id, in_id, squad, in_price = best
        cur_bank += float(proj.loc[out_id, "price"]) - in_price
        swaps.append((out_id, in_id))
    return squad, swaps


def transfer_plans(players: pd.DataFrame, my_squad_ids: list[str], bank: float,
                   free_transfers: int = config.FREE_TRANSFERS_PER_ROUND,
                   xp_col: str = config.TRANSFER_VALUE_COL, top_n: int = 10,
                   shortlist_size: int = 14, rival_squads: list[set] | None = None,
                   regime: str | None = None, hit_margin: float | None = None,
                   cover: bool = False, team_cap: int = config.MAX_PER_TEAM) -> list[dict]:
    """Plans sorted by net gain = (squad value gain on `xp_col`) - (−4 hits), vs
    no transfers. `xp_col` defaults to whole-tournament value, so swapping out a
    player whose country is likely eliminated correctly counts their lost future
    games, and a −4 hit for a star is taken only when its rest-of-cup value beats
    the cost. Searches 0..MAX_PLAN_TRANSFERS (multiple hits at once when several
    teams are eliminated together)."""
    owned = players.loc[[i for i in my_squad_ids if i in players.index]]
    if len(owned) < config.SQUAD_SIZE:
        raise ValueError(f"only {len(owned)}/{config.SQUAD_SIZE} squad ids found in player data")
    current_counts = owned["team"].value_counts()
    pool = players[~players.index.isin(owned.index) & (players.get("status", "available") != "out")]
    # PLAYTIME guarantee on buys: never even shortlist a player unlikely to start.
    _pp = pool["p_start"] if "p_start" in pool.columns else pd.Series(1.0, index=pool.index)
    pool = pool[_pp >= config.BUY_PSTART_FLOOR]
    # "Only safe players" buy gates (owned players untouched): must have PLAYED EVERY completed
    # round (a consistent main) and be owned by at least OWNERSHIP_MIN_BUY% (crowd-confirmed).
    # Both are skipped only if the underlying data is entirely absent, so the search never starves.
    if config.REQUIRE_PLAYED_ALL and "played_all" in pool.columns and pool["played_all"].any():
        pool = pool[pool["played_all"]]
    if "ownership_pct" in pool.columns and pool["ownership_pct"].notna().any():
        pool = pool[pool["ownership_pct"].fillna(0.0) >= config.OWNERSHIP_MIN_BUY]
    if config.PRUNE_DOMINATED_BUYS and not pool.empty:
        pool = _pareto_buyable(pool, xp_col)   # value efficiency: never buy a dominated player

    def _candidates(pos):
        sub = pool[pool["position"] == pos]
        top = sub.sort_values(xp_col, ascending=False).head(shortlist_size)        # the upgrade targets
        # ENABLERS for budget reallocation, all NAILED-ON starters (ENABLER_MIN_PSTART):
        # the BEST-VALUE cheap ones (xP/£M under a price ceiling) are the reliable, decent
        # fillers; plus the single cheapest per position as near-free BENCH fodder to free
        # budget for stars. (A cheap filler may be low-owned, but the XI_PSTART_FLOOR at
        # FIELDING time keeps any sub-floor pick on the bench — never started.)
        pstart = sub["p_start"] if "p_start" in sub.columns else pd.Series(1.0, index=sub.index)
        nailed = sub[pstart >= config.ENABLER_MIN_PSTART]
        cheap = nailed[nailed["price"] <= config.ENABLER_PRICE_CEILING]
        value = (cheap.assign(_v=cheap[xp_col] / cheap["price"].clip(lower=0.1))
                 .sort_values("_v", ascending=False).head(config.ENABLER_VALUE_COUNT))
        cheapest = nailed.sort_values("price").head(config.ENABLER_COUNT)
        return pd.concat([top, value.drop(columns="_v"), cheapest]).loc[lambda df: ~df.index.duplicated()]
    shortlist = {pos: _candidates(pos) for pos in ("GK", "DEF", "MID", "FWD")}

    info = {pid: (row["position"], float(row[xp_col]), float(row["price"]), row["team"],
                  float(row["p_start"]) if "p_start" in row and row["p_start"] == row["p_start"] else 1.0)
            for pid, row in pd.concat([owned, *shortlist.values()]).iterrows()}
    owned_ids = list(owned.index)
    owned_set = set(owned_ids)
    base_value = _fast_squad_value(owned_ids, info)

    # league-aware tilt: cover rivals' stars when ahead, find differentials when behind
    own_frac = {}
    if rival_squads:
        n_r = max(1, len(rival_squads))
        from collections import Counter
        _c = Counter(pid for s in rival_squads for pid in s)
        own_frac = {pid: _c[pid] / n_r for pid in _c}
    hitm = config.HIT_MARGIN if hit_margin is None else hit_margin

    def league_tilt(outs: list[str], ins: list[str]) -> float:
        if not own_frac or regime not in ("leader", "chaser"):
            return 0.0
        if regime == "chaser":          # reward low-ownership upside in, high-ownership out
            gi = sum((1 - own_frac.get(i, 0.0)) * info[i][1] for i in ins)
            go = sum((1 - own_frac.get(o, 0.0)) * info[o][1] for o in outs)
            return config.DIFF_LAMBDA * (gi - go)
        gi = sum(own_frac.get(i, 0.0) * info[i][1] for i in ins)   # leader: cover rivals' picks
        go = sum(own_frac.get(o, 0.0) * info[o][1] for o in outs)
        return config.COVER_LAMBDA * (gi - go)

    def hit_cost(n_transfers: int) -> int:
        return max(0, n_transfers - free_transfers) * config.EXTRA_TRANSFER_COST

    cur_counts = current_counts.to_dict()
    base_over = sum(max(0, c - team_cap) for c in cur_counts.values())   # players over the soft cap now

    def evaluate(outs: list[str], ins: list[str]) -> dict | None:
        out_price = sum(info[o][2] for o in outs)
        in_price = sum(info[i][2] for i in ins)
        if in_price > out_price + bank + 1e-9:
            return None
        counts = dict(cur_counts)
        for o in outs:
            counts[info[o][3]] = counts.get(info[o][3], 0) - 1
        in_teams = set()
        for i in ins:
            team = info[i][3]
            counts[team] = counts.get(team, 0) + 1
            in_teams.add(team)
        # HARD rule: any team you BUY INTO must finish within the soft cap. Existing
        # over-stacks (set before the cap) are grandfathered — you may HOLD or TRIM
        # them — but you can't ADD to one and you can't CHURN within it (sell one,
        # buy another of the same team to stay at 3). So a transfer touching an
        # over-stacked team must reduce it. (Teams you don't buy into can only fall
        # via `outs`, so they never exceed their grandfathered count.) In the
        # knockouts soft_cap == TV2 max (3), so this naturally relaxes.
        for team in in_teams:
            if counts[team] > team_cap:
                return None
        new_ids = [pid for pid in owned_ids if pid not in outs] + ins
        value = _fast_squad_value(new_ids, info)
        cost = hit_cost(len(outs))
        net = round(value - cost - base_value, 2)
        new_over = sum(max(0, c - team_cap) for c in counts.values())
        diversify = round(config.CONCENTRATION_CREDIT * (base_over - new_over), 2)   # >0 if it trims a stack
        return {
            "outs": [(players.loc[o, "name"], players.loc[o, "team"]) for o in outs],
            "ins": [(players.loc[i, "name"], players.loc[i, "team"]) for i in ins],
            "out_ids": outs, "in_ids": ins,
            "n_transfers": len(outs), "hit_cost": cost,
            "net_gain": net, "diversify_credit": diversify,
            "league_gain": round(net + league_tilt(outs, ins) + diversify, 2),
            "new_bank": round(bank + out_price - in_price, 1),
        }

    plans = [{"outs": [], "ins": [], "out_ids": [], "in_ids": [], "n_transfers": 0, "hit_cost": 0,
              "net_gain": 0.0, "diversify_credit": 0.0, "league_gain": 0.0, "new_bank": round(bank, 1)}]

    singles: list[dict] = []
    for out_id in owned.index:
        pos = owned.loc[out_id, "position"]
        for in_id in shortlist[pos].index:
            plan = evaluate([out_id], [in_id])
            if plan:
                singles.append(plan)
    plans.extend(singles)

    for out_a, out_b in combinations(owned.index, 2):
        pos_a, pos_b = owned.loc[out_a, "position"], owned.loc[out_b, "position"]
        if pos_a == pos_b:
            # which "in" replaces which "out" is irrelevant for same-position
            # swaps - unordered pairs avoid duplicate plans
            in_pairs = combinations(shortlist[pos_a].index, 2)
        else:
            in_pairs = ((ia, ib) for ia in shortlist[pos_a].index for ib in shortlist[pos_b].index)
        for in_a, in_b in in_pairs:
            plan = evaluate([out_a, out_b], [in_a, in_b])
            if plan:
                plans.append(plan)

    _key = "league_gain"   # = net_gain + league tilt + diversify credit (diversify=0 at cap 3)
    plans.sort(key=lambda p: p[_key], reverse=True)

    # Greedily extend toward more transfers (each an extra -4 hit). Keep adding
    # the best marginal single swap while it raises the net (post-hit) gain by
    # more than the (regime-tuned) hit margin - the -4 ROI simulation. A leader
    # demands a fat margin (protect the cushion); a chaser takes hits readily.
    anchor = next((p for p in plans if p["n_transfers"] == 2), None) or plans[0]
    while anchor["n_transfers"] < config.MAX_PLAN_TRANSFERS:
        remaining = [i for i in owned.index if i not in anchor["out_ids"]]
        best_ext = None
        paid = (anchor["n_transfers"] + 1) > free_transfers      # the new transfer costs a -4
        for out_id in remaining:
            pos = owned.loc[out_id, "position"]
            for in_id in shortlist[pos].index:
                if in_id in anchor["in_ids"]:
                    continue
                # PAID (-4) swaps: only a LIGHT sanity floor here — the incoming player must
                # improve whole-cup value, so we don't generate dominated hits. Whether the
                # -4 is actually worth taking is decided downstream by the TITLE-probability
                # sim (which deducts the hit and folds in the standings), per "play for the
                # title". This lets a 3rd/4th transfer through when the new players make up
                # for the -4 over the cup, instead of blocking it on next-round value alone.
                if paid:
                    marg = (float(players.loc[in_id, "xp_tournament"]) - float(players.loc[out_id, "xp_tournament"])
                            if in_id in players.index and out_id in players.index else 0.0)
                    if marg <= 0:
                        continue
                ext = evaluate(anchor["out_ids"] + [out_id], anchor["in_ids"] + [in_id])
                if ext and (best_ext is None or ext["net_gain"] > best_ext["net_gain"]):
                    best_ext = ext
        if best_ext and best_ext["net_gain"] > anchor["net_gain"] + hitm:
            plans.append(best_ext)
            anchor = best_ext
        else:
            break

    plans.sort(key=lambda p: p[_key], reverse=True)
    # top-plan re-rank: regime variance tilt (shed SD leading / buy it chasing)
    # + bench-cover bonus (reward a bench that can actually auto-sub in)
    if regime in ("leader", "chaser") or cover:
        from src import analytics as _an
        sign = -1.0 if regime == "leader" else 1.0
        pp = players["p_play"] if "p_play" in players.columns else None
        xpn = players["xp_next"] if "xp_next" in players.columns else None
        head = max(top_n * 2, 12)
        for p in plans[:head]:
            new_ids = [pid for pid in owned_ids if pid not in p["out_ids"]] + p["in_ids"]
            rows = players.loc[[i for i in new_ids if i in players.index]]
            xi = best_xi(rows, "xp_next")
            adj = p["league_gain"]
            if regime in ("leader", "chaser"):
                sd = _an.xi_sd(rows.loc[[i for i in xi["xi_ids"] if i in rows.index]], xi["captain_id"])
                adj += sign * config.K_VAR * sd
            if cover and pp is not None and xpn is not None:
                bench = [i for i in new_ids if i not in set(xi["xi_ids"]) and i in players.index]
                cov = sum(float(pp.get(b, 0.0)) * max(float(xpn.get(b, 0.0)), 0.0) for b in bench)
                p["bench_cover"] = round(cov, 2)
                adj += config.COVER_WEIGHT * cov
            p["adj_gain"] = round(adj, 2)
        plans[:head] = sorted(plans[:head], key=lambda p: p.get("adj_gain", p["league_gain"]), reverse=True)
    out = plans[:top_n]
    # always keep the no-transfer baseline in the returned set, even when many
    # positive swaps outrank it — the UI needs its win-prob ('from X% if you keep')
    # and a 'Keep squad' reference bar, and rank_sim only scores plans it's handed.
    if not any(p["n_transfers"] == 0 for p in out):
        keep = next((p for p in plans if p["n_transfers"] == 0), None)
        if keep is not None:
            out = out[:max(0, top_n - 1)] + [keep]
    return out
