"""Repro for the claimed differentials sort-key bug. Not committed; delete after."""
import ast
import math

import pandas as pd

from src import template_team

# --- 1. precedence: '-x or 0' parses as '(-x) or 0' ---
print("AST of '-x or 0':", ast.dump(ast.parse("-x or 0", mode="eval").body))

nan = float("nan")
print("bool(-nan) =", bool(-nan), "| (-nan) or 0 =", (-nan) or 0)

# --- 2. mimic load_players: list of dicts, some ownership null (None) ---
rows = []
# 15 high-ownership template players (2 GK / 5 DEF / 5 MID / 3 FWD)
shape = [("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)]
pid = 0
for pos, n in shape:
    for k in range(n):
        pid += 1
        rows.append({"id": f"t{pid}", "name": f"Tmpl{pid}", "team": "Spain",
                     "position": pos, "price": 5.0, "ownership_pct": 90.0 - pid,
                     "total_points": 10, "xp_next": 3.0, "xp_horizon": 9.0})
# my non-template players: C=30%, A=5%, B=NaN (scraper had no ownership for B)
rows.append({"id": "A", "name": "LowOwn", "team": "Norway", "position": "MID",
             "price": 6.0, "ownership_pct": 5.0, "total_points": 4, "xp_next": 2.0, "xp_horizon": 6.0})
rows.append({"id": "B", "name": "NoData", "team": "Norway", "position": "FWD",
             "price": 7.0, "ownership_pct": None, "total_points": 3, "xp_next": 2.0, "xp_horizon": 6.0})
rows.append({"id": "C", "name": "HighOwn", "team": "Norway", "position": "DEF",
             "price": 5.5, "ownership_pct": 30.0, "total_points": 6, "xp_next": 2.0, "xp_horizon": 6.0})

players = pd.DataFrame(rows).set_index("id", drop=False)
print("ownership_pct dtype:", players["ownership_pct"].dtype)
print("value for B via row.get:", repr(players.loc["B"].get("ownership_pct")))

my_squad_ids = [f"t{i}" for i in range(1, 13)] + ["A", "B", "C"]  # 12 template + 3 diffs

result = template_team.differentials(players, my_squad_ids)
assert result is not None
mine_only, tmpl_only = result
print("\nmine_only (displayed order on Home.py 'My differentials'):")
print(mine_only[["name", "ownership_pct"]].to_string())

order = list(mine_only["name"])
print("\nGot order:", order)
print("Intended (desc, NaN treated as 0):", ["HighOwn", "LowOwn", "NoData"])
print("Wrong order?", order != ["HighOwn", "LowOwn", "NoData"])

# also show the raw sorted() keys behaviour on this exact set
mine = set(my_squad_ids)
tmpl = set(template_team.template_squad(players).index)
keys = {i: (-players.loc[i].get("ownership_pct") or 0) for i in (mine - tmpl)}
print("\nkeys used by sorted():", keys)
