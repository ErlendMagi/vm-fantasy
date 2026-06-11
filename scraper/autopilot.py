"""Fully automatic team management - the no-hands mode.

Run on a schedule (GitHub Actions). Each run:
  1. Fetches live TV 2 state (players, squad, transfer window, deadline).
  2. If the next deadline is NOT within --window-hours, does nothing (so the
     team only changes shortly before it locks, on the freshest odds).
  3. Decides the move:
       - transfers UNLIMITED (pre-tournament): rebuild the optimal 15 from scratch
       - normal rounds: apply the optimizer's best transfer plan (respects free
         transfers; takes a -4 hit only when it clearly pays for itself)
  4. Always (re)sets the best lineup, captain and vice for the coming round.
  5. PUTs to TV 2 and verifies the result.

    python scraper/autopilot.py                    # dry run
    python scraper/autopilot.py --confirm           # write for real
    python scraper/autopilot.py --confirm --force   # ignore the deadline window

Auth: TV2_TOKEN env (cloud) or the saved browser session (local).
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import advancement, data_access, optimizer, projections, squad_builder  # noqa: E402
from apply_team import apply_and_verify, compose_lineup, print_team  # noqa: E402
from tv2_client import Tv2Client  # noqa: E402


def players_frame(players: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(players)
    df["team"] = df["team"].map(data_access.normalize_team)
    df["round_points"] = df["round_points"].apply(lambda d: {int(k): v for k, v in (d or {}).items()})
    return df.set_index("id", drop=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--force", action="store_true", help="act even if far from the deadline")
    ap.add_argument("--window-hours", type=float, default=8.0,
                    help="only act when the deadline is within this many hours")
    args = ap.parse_args()

    client = Tv2Client()
    raw = client.fetch_raw()
    ti = raw.get("transfer_info") or {}
    target_round = ti.get("targetRound") or {}
    deadline = target_round.get("deadlineAt")

    if deadline and not args.force:
        dl = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        hours_left = (dl - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours_left <= 0:
            print(f"deadline passed {-hours_left:.1f}h ago - waiting for the next round to open")
            return
        if hours_left > args.window_hours:
            print(f"{hours_left:.1f}h until deadline (window {args.window_hours}h) - too early, doing nothing")
            return
        print(f"{hours_left:.1f}h until deadline - acting on round "
              f"{target_round.get('number')} ({target_round.get('name')})")

    players = players_frame(client.normalize_players(raw["players"]))
    my_team = client.normalize_my_team(raw["my_team"], ti)
    fixtures = client.normalize_fixtures(raw["fixtures"]) if raw.get("fixtures") else data_access.load_fixtures()
    match_odds, outrights = data_access.load_match_odds(), data_access.load_outrights()
    completed = data_access.completed_rounds(fixtures)
    next_rnd = data_access.next_round(fixtures)
    adv = advancement.advancement_table(fixtures, match_odds, outrights)
    p_plays = advancement.p_plays_lookup(adv)
    proj = projections.project(players, fixtures, match_odds, outrights, completed, next_rnd, p_plays)

    if ti.get("unlimitedTransfers"):
        print("transfers are unlimited - rebuilding the optimal squad from scratch")
        res = squad_builder.build_optimal_squad(proj, value_col="xp_tournament")
        target_ids = res["squad_ids"]
    else:
        free = my_team["free_transfers"]
        plans = optimizer.transfer_plans(proj, my_team["squad"], my_team["bank"], free_transfers=free)
        best = plans[0]
        if best["n_transfers"] == 0:
            print("best plan: keep the squad (no transfer clears the bar) - refreshing lineup/captain only")
        else:
            outs = ", ".join(n for n, _ in best["outs"])
            ins = ", ".join(n for n, _ in best["ins"])
            print(f"best plan: {best['n_transfers']} transfer(s) "
                  f"(hit -{best['hit_cost']}): OUT {outs}  ->  IN {ins}  "
                  f"(+{best['net_gain']} projected)")
        target_ids = [p for p in my_team["squad"] if p not in best["out_ids"]] + best["in_ids"]

    t = compose_lineup(proj, target_ids)
    print_team(t, proj)

    if not args.confirm:
        print("\n[dry run] nothing sent.")
        return
    print("\napplying to TV 2...")
    apply_and_verify(t, round_id=target_round.get("id"))


if __name__ == "__main__":
    main()
