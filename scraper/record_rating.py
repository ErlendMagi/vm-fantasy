"""Daily rating snapshot: computes today's squad/XI/position ratings from the
freshly synced data and upserts them into data/tv2/rating_history.json.

Run by the cloud workflow after each sync; one entry per calendar day (the
last run of the day wins, so the snapshot reflects the freshest odds/form).
The My Team page charts this history.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import advancement, analytics, data_access, optimizer, projections  # noqa: E402

HIST = ROOT / "data" / "tv2" / "rating_history.json"


def main() -> None:
    players = data_access.load_players()
    my = data_access.load_my_team()
    if players is None or my is None:
        sys.exit("no player/team data - run sync first")
    fixtures = data_access.load_fixtures()
    mo, ou = data_access.load_match_odds(), data_access.load_outrights()
    completed = data_access.completed_rounds(fixtures)
    adv = advancement.advancement_table(fixtures, mo, ou)
    p_plays = advancement.p_plays_lookup(adv)
    proj = projections.project(players, fixtures, mo, ou, completed,
                               data_access.next_round(fixtures), p_plays)
    proj = analytics.add_kpis(proj)
    ranks = analytics.position_ranks(proj, "xp_tournament")

    owned = proj.loc[[i for i in my["squad"] if i in proj.index]]
    xi = optimizer.best_xi(owned, "xp_next")
    tr = analytics.team_rating(proj, my["squad"], ranks)
    sq = analytics.squad_quality(proj, my["squad"])

    today = datetime.now(timezone.utc).date().isoformat()
    hist = json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else {"days": {}}
    hist["days"][today] = {
        "squad_rating": sq["rating"],
        "xi_rating": tr["rating"],
        "pos_rating": tr["pos_rating"],
        "exp_next": round(xi["total"], 1),
        "points_so_far": int(sum((my.get("round_history") or {}).values())
                             or owned["total_points"].sum()),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    HIST.write_text(json.dumps(hist, indent=1), encoding="utf-8")
    print(f"rating snapshot {today}: squad {sq['rating']} | XI {tr['rating']} | "
          f"pos {tr['pos_rating']}")


if __name__ == "__main__":
    main()
