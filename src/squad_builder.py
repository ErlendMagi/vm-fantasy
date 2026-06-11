"""Build an optimal 15-man squad FROM SCRATCH under the game constraints.

The transfer optimizer only does incremental swaps; this picks a whole team to
maximize projected squad value (best XI + captain, via optimizer.squad_xp)
subject to: 2 GK / 5 DEF / 5 MID / 3 FWD, total price <= budget, <= 3 per team.

Approach: randomized greedy initialization + hill-climbing local search over
single same-position swaps, several restarts, keep the best. Exact ILP is
overkill for a one-off team build and this reliably finds a strong squad.
"""
import numpy as np
import pandas as pd

from src import config, optimizer

# limit the search to plausible picks per position (by forward-looking value)
# plus cheap fillers so the bench/budget stay feasible
SHORTLIST_PER_POS = 40
CHEAP_FILLERS = 12


def _candidate_pool(players: pd.DataFrame, value_col: str) -> dict[str, pd.DataFrame]:
    pool = {}
    avail = players[players.get("status", "available") != "out"]
    for pos in config.SQUAD_SHAPE:
        p = avail[avail["position"] == pos]
        top = p.nlargest(SHORTLIST_PER_POS, value_col)
        cheap = p.nsmallest(CHEAP_FILLERS, "price")
        pool[pos] = pd.concat([top, cheap]).drop_duplicates(subset="id")
    return pool


def _greedy_start(pool: dict, budget: float, value_col: str, rng: np.random.Generator) -> list[str] | None:
    """Feasible squad: fill each position picking among the best by value with a
    little randomness, reserving each remaining slot's true minimum price so the
    squad always completes within budget and the per-team cap."""
    pos_min = {pos: float(pool[pos]["price"].min()) for pos in config.SQUAD_SHAPE}
    need_left = dict(config.SQUAD_SHAPE)
    chosen: list[str] = []
    team_counts: dict[str, int] = {}
    spent = 0.0
    for pos in config.SQUAD_SHAPE:
        cands = pool[pos].sort_values(value_col, ascending=False)
        for _ in range(config.SQUAD_SHAPE[pos]):
            need_left[pos] -= 1
            reserve = sum(need_left[p] * pos_min[p] for p in config.SQUAD_SHAPE)
            ok = cands[
                ~cands["id"].isin(chosen)
                & (cands["price"] <= budget - spent - reserve + 1e-9)
                & cands["team"].map(lambda t: team_counts.get(t, 0) < config.MAX_PER_TEAM)
            ]
            if ok.empty:
                return None
            head = ok.head(6)  # randomize among the best affordable to diversify restarts
            row = head.iloc[int(rng.integers(0, len(head)))]
            chosen.append(row["id"])
            team_counts[row["team"]] = team_counts.get(row["team"], 0) + 1
            spent += float(row["price"])
    return chosen


def _formation_seed(info: dict, pool_ids: dict, formation: tuple, budget: float) -> list[str] | None:
    """A premium-XI-plus-cheap-bench seed for one formation: cheapest legal
    bench first, then fill the starting XI with the highest-VALUE affordable
    players (reserving each remaining slot's minimum price). This lands the
    search near the strong-attacker optimum instead of a cheap local one."""
    d, m, f = formation
    xi_need = {"GK": 1, "DEF": d, "MID": m, "FWD": f}
    bench_need = {"GK": 1, "DEF": 5 - d, "MID": 5 - m, "FWD": 3 - f}
    chosen, counts, spent = [], {}, 0.0

    for pos, n in bench_need.items():
        taken = 0
        for cid in sorted(pool_ids[pos], key=lambda i: info[i][2]):  # cheapest first
            if taken >= n:
                break
            t = info[cid][3]
            if cid in chosen or counts.get(t, 0) >= config.MAX_PER_TEAM:
                continue
            chosen.append(cid); counts[t] = counts.get(t, 0) + 1; spent += info[cid][2]; taken += 1
        if taken < n:
            return None

    xi_min = {pos: min(info[i][2] for i in pool_ids[pos]) for pos in xi_need}
    need = dict(xi_need)
    for cid in sorted((i for pos in xi_need for i in pool_ids[pos] if i not in chosen),
                      key=lambda i: -info[i][1]):  # highest value first
        pos, _, price, t = info[cid]
        if need.get(pos, 0) <= 0 or counts.get(t, 0) >= config.MAX_PER_TEAM:
            continue
        after = dict(need); after[pos] -= 1
        reserve = sum(after[p] * xi_min[p] for p in after)
        if spent + price + reserve > budget + 1e-9:
            continue
        chosen.append(cid); counts[t] = counts.get(t, 0) + 1; spent += price; need[pos] -= 1
        if not any(need.values()):
            break
    return chosen if not any(need.values()) else None


def _hill_climb(squad: list[str], info: dict, pool_ids: dict, budget: float) -> tuple[list[str], float]:
    """Best-improvement local search over single same-position swaps, using the
    fast tuple evaluator. info[pid]=(pos, xp, price, team)."""
    best = list(squad)
    best_val = optimizer._fast_squad_value(best, info)
    improved = True
    while improved:
        improved = False
        owned = set(best)
        spent = sum(info[i][2] for i in best)
        counts: dict[str, int] = {}
        for i in best:
            counts[info[i][3]] = counts.get(info[i][3], 0) + 1
        best_move = None
        for out_id in best:
            o_pos, _, o_price, o_team = info[out_id]
            for cid in pool_ids[o_pos]:
                if cid in owned:
                    continue
                c_team, c_price = info[cid][3], info[cid][2]
                if spent - o_price + c_price > budget + 1e-9:
                    continue
                if c_team != o_team and counts.get(c_team, 0) + 1 > config.MAX_PER_TEAM:
                    continue
                trial = [cid if x == out_id else x for x in best]
                val = optimizer._fast_squad_value(trial, info)
                if val > best_val + 1e-9 and (best_move is None or val > best_move[1]):
                    best_move = (trial, val)
        # paired reallocation: downgrade one player to a cheap filler so an
        # upgrade elsewhere becomes affordable (single swaps can't see this)
        if not best_move:
            best_move = _reallocation_move(best, best_val, info, pool_ids, budget)
        if best_move:
            best, best_val = best_move
            improved = True
    return best, best_val


def _reallocation_move(best, best_val, info, pool_ids, budget):
    owned = set(best)
    spent = sum(info[i][2] for i in best)
    by_val = sorted(best, key=lambda i: info[i][1])  # lowest value first
    # cheapest unowned filler per position (to free budget)
    cheapest = {pos: min((c for c in pool_ids[pos] if c not in owned),
                         key=lambda i: info[i][2], default=None) for pos in config.SQUAD_SHAPE}
    move = None
    for drop in by_val[:6]:                       # a low-value player to downgrade
        fp = cheapest[info[drop][0]]
        if fp is None or info[fp][2] >= info[drop][2]:
            continue
        freed = info[drop][2] - info[fp][2]
        for up in by_val:                         # a player to upgrade with the freed cash
            if up == drop:
                continue
            up_pos = info[up][0]
            for cid in pool_ids[up_pos][:20]:     # best-value candidates that pos
                if cid in owned or cid == fp:
                    continue
                if info[cid][2] > info[up][2] + freed + 1e-9:
                    continue
                trial = [fp if x == drop else (cid if x == up else x) for x in best]
                if len(set(trial)) != config.SQUAD_SIZE:
                    continue
                counts = {}
                for i in trial:
                    counts[info[i][3]] = counts.get(info[i][3], 0) + 1
                if max(counts.values()) > config.MAX_PER_TEAM:
                    continue
                if sum(info[i][2] for i in trial) > budget + 1e-9:
                    continue
                val = optimizer._fast_squad_value(trial, info)
                if val > best_val + 1e-9 and (move is None or val > move[1]):
                    move = (trial, val)
    return move


def build_optimal_squad(players: pd.DataFrame, budget: float = config.BUDGET,
                        value_col: str = "xp_horizon", restarts: int = 6,
                        seed: int = 7) -> dict:
    """Returns {squad_ids, best_xi(dict), value, price, by_position}."""
    rng = np.random.default_rng(seed)
    pool = _candidate_pool(players, value_col)
    # tuple view for the fast evaluator + per-position candidate id lists
    union = pd.concat(pool.values()).drop_duplicates(subset="id")
    info = {r["id"]: (r["position"], float(r[value_col]), float(r["price"]), r["team"])
            for _, r in union.iterrows()}
    pool_ids = {pos: list(df["id"]) for pos, df in pool.items()}

    # seed from every formation's premium-XI build, plus a few randomized greedy
    # starts for diversity; hill-climb each and keep the best
    seeds = [_formation_seed(info, pool_ids, fm, budget) for fm in config.FORMATIONS]
    seeds += [_greedy_start(pool, budget, value_col, rng) for _ in range(restarts)]

    best_squad, best_val = None, -1.0
    for start in seeds:
        if start is None or len(set(start)) != config.SQUAD_SIZE:
            continue
        squad, val = _hill_climb(start, info, pool_ids, budget)
        if val > best_val:
            best_squad, best_val = squad, val
    if best_squad is None:
        raise RuntimeError("could not build a feasible squad - check budget/pool")

    xi = optimizer.best_xi(players.loc[best_squad], value_col)
    return {
        "squad_ids": best_squad,
        "best_xi": xi,
        "value": round(best_val, 2),
        "price": round(float(players.loc[best_squad, "price"].sum()), 1),
        "by_position": players.loc[best_squad, "position"].value_counts().to_dict(),
    }
