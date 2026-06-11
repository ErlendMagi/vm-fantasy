"""Best XI, captain and transfer search.

Squad value = best legal XI by projected points, captain counted double.
Transfer search is exhaustive over single swaps and pruned double swaps
(top candidates per position); a third transfer (-4 hit) is only recommended
when its marginal gain clears the hit cost plus a noise margin.
"""
from itertools import combinations

import pandas as pd

from src import config


def best_xi(squad: pd.DataFrame, xp_col: str = "xp_next") -> dict:
    """squad: 15-row frame with position + xp_col. Returns XI ids, formation,
    captain and total (captain doubled)."""
    by_pos = {
        pos: squad[squad["position"] == pos].sort_values(xp_col, ascending=False)
        for pos in ("GK", "DEF", "MID", "FWD")
    }
    best = None
    for d, m, f in config.FORMATIONS:
        if len(by_pos["DEF"]) < d or len(by_pos["MID"]) < m or len(by_pos["FWD"]) < f or by_pos["GK"].empty:
            continue
        xi = pd.concat([by_pos["GK"].head(1), by_pos["DEF"].head(d),
                        by_pos["MID"].head(m), by_pos["FWD"].head(f)])
        total = float(xi[xp_col].sum())
        if best is None or total > best["xi_xp"]:
            best = {"xi_ids": list(xi["id"]), "formation": f"{d}-{m}-{f}", "xi_xp": total,
                    "captain_id": xi.loc[xi[xp_col].idxmax(), "id"],
                    "captain_xp": float(xi[xp_col].max())}
    if best is None:
        return {"xi_ids": [], "formation": "-", "xi_xp": 0.0, "captain_id": None,
                "captain_xp": 0.0, "total": 0.0}
    best["total"] = best["xi_xp"] + (config.CAPTAIN_MULTIPLIER - 1) * best["captain_xp"]
    return best


def squad_xp(squad: pd.DataFrame, xp_col: str = "xp_next") -> float:
    return best_xi(squad, xp_col)["total"]


def captain_options(squad: pd.DataFrame, xp_col: str = "xp_next", n: int = 3) -> pd.DataFrame:
    cols = [c for c in ["name", "team", "position", "opponent", xp_col, "heat_mult"] if c in squad.columns]
    return squad.sort_values(xp_col, ascending=False).head(n)[cols]


def _fast_squad_value(ids: list[str], info: dict[str, tuple]) -> float:
    """Same result as squad_xp but on plain tuples - the transfer search calls
    this ~20k times, so no pandas here. info[pid] = (pos, xp, price, team).
    Captain = max xp in the XI; every formation fields the top player of each
    position, so the captain is formation-independent."""
    by_pos = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for pid in ids:
        p = info[pid]
        by_pos[p[0]].append(p[1])
    for v in by_pos.values():
        v.sort(reverse=True)
    if not by_pos["GK"]:
        return 0.0
    prefix = {}
    for pos, v in by_pos.items():
        acc, total = [0.0], 0.0
        for x in v:
            total += x
            acc.append(total)
        prefix[pos] = acc
    best = 0.0
    for d, m, f in config.FORMATIONS:
        if len(by_pos["DEF"]) < d or len(by_pos["MID"]) < m or len(by_pos["FWD"]) < f:
            continue
        val = by_pos["GK"][0] + prefix["DEF"][d] + prefix["MID"][m] + prefix["FWD"][f]
        best = max(best, val)
    captain = max(by_pos["GK"][0],
                  by_pos["DEF"][0] if by_pos["DEF"] else 0.0,
                  by_pos["MID"][0] if by_pos["MID"] else 0.0,
                  by_pos["FWD"][0] if by_pos["FWD"] else 0.0)
    return best + (config.CAPTAIN_MULTIPLIER - 1) * captain


def transfer_plans(players: pd.DataFrame, my_squad_ids: list[str], bank: float,
                   free_transfers: int = config.FREE_TRANSFERS_PER_ROUND,
                   xp_col: str = config.TRANSFER_VALUE_COL, top_n: int = 10,
                   shortlist_size: int = 14) -> list[dict]:
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
    shortlist = {
        pos: pool[pool["position"] == pos].sort_values(xp_col, ascending=False).head(shortlist_size)
        for pos in ("GK", "DEF", "MID", "FWD")
    }

    info = {pid: (row["position"], float(row[xp_col]), float(row["price"]), row["team"])
            for pid, row in pd.concat([owned, *shortlist.values()]).iterrows()}
    owned_ids = list(owned.index)
    owned_set = set(owned_ids)
    base_value = _fast_squad_value(owned_ids, info)

    def hit_cost(n_transfers: int) -> int:
        return max(0, n_transfers - free_transfers) * config.EXTRA_TRANSFER_COST

    def evaluate(outs: list[str], ins: list[str]) -> dict | None:
        out_price = sum(info[o][2] for o in outs)
        in_price = sum(info[i][2] for i in ins)
        if in_price > out_price + bank + 1e-9:
            return None
        counts = current_counts.to_dict()
        for o in outs:
            counts[info[o][3]] = counts.get(info[o][3], 0) - 1
        for i in ins:
            team = info[i][3]
            counts[team] = counts.get(team, 0) + 1
            # any team you buy INTO must end within the cap; teams not receiving
            # an "in" are never checked, so existing excess stays grandfathered
            if counts[team] > config.MAX_PER_TEAM:
                return None
        new_ids = [pid for pid in owned_ids if pid not in outs] + ins
        value = _fast_squad_value(new_ids, info)
        cost = hit_cost(len(outs))
        return {
            "outs": [(players.loc[o, "name"], players.loc[o, "team"]) for o in outs],
            "ins": [(players.loc[i, "name"], players.loc[i, "team"]) for i in ins],
            "out_ids": outs, "in_ids": ins,
            "n_transfers": len(outs), "hit_cost": cost,
            "net_gain": round(value - cost - base_value, 2),
            "new_bank": round(bank + out_price - in_price, 1),
        }

    plans = [{"outs": [], "ins": [], "out_ids": [], "in_ids": [], "n_transfers": 0,
              "hit_cost": 0, "net_gain": 0.0, "new_bank": round(bank, 1)}]

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

    plans.sort(key=lambda p: p["net_gain"], reverse=True)

    # Greedily extend toward more transfers (each an extra -4 hit). Keep adding
    # the best marginal single swap while it raises the net (post-hit) gain by
    # more than HIT_MARGIN - this is the -4 ROI simulation, and it stacks when
    # several teams are eliminated at once (post-group reshuffle).
    anchor = next((p for p in plans if p["n_transfers"] == 2), None) or plans[0]
    while anchor["n_transfers"] < config.MAX_PLAN_TRANSFERS:
        remaining = [i for i in owned.index if i not in anchor["out_ids"]]
        best_ext = None
        for out_id in remaining:
            pos = owned.loc[out_id, "position"]
            for in_id in shortlist[pos].index:
                if in_id in anchor["in_ids"]:
                    continue
                ext = evaluate(anchor["out_ids"] + [out_id], anchor["in_ids"] + [in_id])
                if ext and (best_ext is None or ext["net_gain"] > best_ext["net_gain"]):
                    best_ext = ext
        if best_ext and best_ext["net_gain"] > anchor["net_gain"] + config.HIT_MARGIN:
            plans.append(best_ext)
            anchor = best_ext
        else:
            break

    plans.sort(key=lambda p: p["net_gain"], reverse=True)
    return plans[:top_n]
