"""Verify (and optionally fix) captain + vice-captain on the live TV 2 team,
using the current squad — does NOT change your players, only the armband and
the best legal XI for the coming round.

    python scraper/set_captain.py            # show current vs recommended
    python scraper/set_captain.py --confirm  # apply the recommended lineup
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import advancement, analytics, data_access, optimizer, projections  # noqa: E402
from apply_team import apply_and_verify, compose_lineup  # noqa: E402
from tv2_client import Tv2Client  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    client = Tv2Client()
    raw = client.fetch_raw()
    ti = raw.get("transfer_info") or {}
    players = pd.DataFrame(client.normalize_players(raw["players"]))
    players["team"] = players["team"].map(data_access.normalize_team)
    players["round_points"] = players["round_points"].apply(lambda d: {int(k): v for k, v in (d or {}).items()})
    players = players.set_index("id", drop=False)
    my = client.normalize_my_team(raw["my_team"], ti)

    fixtures = data_access.load_fixtures()
    mo, ou = data_access.load_match_odds(), data_access.load_outrights()
    completed = data_access.completed_rounds(fixtures)
    # project the round TV 2 is actually editing (its target round), not the
    # model's fixture-derived next_round which can lag behind real deadlines
    nxt = (ti.get("targetRound") or {}).get("number") or data_access.next_round(fixtures)
    adv = advancement.advancement_table(fixtures, mo, ou)
    pp = advancement.p_plays_lookup(adv)
    proj = projections.project(players, fixtures, mo, ou, completed, nxt, pp)
    proj = analytics.add_kpis(proj)

    owned = proj.loc[[i for i in my["squad"] if i in proj.index]]
    regime, field_own = None, None
    ls = analytics.league_state(data_access.load_league(), my.get("squad_name"), completed)
    if ls:
        risk = analytics.squad_risk(proj, my["squad"], None, "xp_next",
                                    gap_to_field=ls["gap_to_field"], rounds_left=ls["rounds_left"])
        regime = risk["regime"] if risk else None
        field_own = analytics.field_ownership(ls["rival_squads"])
        print(f"league regime: {regime} (gap {ls['gap_to_field']:+d}, {ls['rounds_left']} rounds left)")
    t = compose_lineup(proj, list(owned.index), regime=regime, field_own=field_own)
    cap, vice = t["captainId"], t["viceCaptainId"]

    def nm(pid):
        return proj.loc[pid, "name"] if pid in proj.index else str(pid)

    cur_cap = my.get("captain_id")
    print(f"Next round: {nxt}")
    print(f"CURRENT on TV 2  — captain: {nm(cur_cap) if cur_cap else '?'}")
    print(f"MODEL recommends — captain: {nm(cap)} ({proj.loc[cap, 'xp_next']:.2f} xP)  |  "
          f"vice: {nm(vice)} ({proj.loc[vice, 'xp_next']:.2f} xP)")
    top = owned.sort_values("xp_next", ascending=False).head(4)
    print("\nTop XI players by expected points (captain candidates):")
    for pid, r in top.iterrows():
        tag = "  <- CAPTAIN" if pid == cap else ("  <- vice" if pid == vice else "")
        print(f"  {r['name']:20} {r['team']:11} {r['xp_next']:.2f} xP{tag}")

    if not args.confirm:
        print("\n[dry run] re-run with --confirm to set this captain + vice on TV 2.")
        return
    print("\napplying lineup (players unchanged, captain/vice + best XI set)...")
    apply_and_verify(t, round_id=(ti.get("targetRound") or {}).get("id"))


if __name__ == "__main__":
    main()
