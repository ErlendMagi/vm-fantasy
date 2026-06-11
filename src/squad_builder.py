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
        if best_move:
            best, best_val = best_move
            improved = True
    return best, best_val


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

    best_squad, best_val = None, -1.0
    for _ in range(restarts):
        start = _greedy_start(pool, budget, value_col, rng)
        if start is None:
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
