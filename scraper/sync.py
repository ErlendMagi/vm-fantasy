"""The sync pipeline: TV 2 scrape -> validate -> write -> odds -> git push.

Run this daily (and always shortly before a transfer deadline):

    python scraper/sync.py                # full sync + push
    python scraper/sync.py --dry-run      # write files, no git
    python scraper/sync.py --skip-odds    # don't spend odds credits
    python scraper/sync.py --no-push      # commit locally only

On ANY validation failure nothing is committed - the cloud app keeps serving
the last good snapshot.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import config, data_access  # noqa: E402
from tv2_client import Tv2Client  # noqa: E402


def validate(players: list[dict], my_team: dict) -> list[str]:
    errors = []
    if len(players) < 400:
        errors.append(f"only {len(players)} players (expected 400+) - partial payload?")
    ids = {p["id"] for p in players}
    if len(ids) != len(players):
        errors.append(f"{len(players) - len(ids)} duplicate player ids in payload")
    if any(not p.get("name") for p in players):
        errors.append("players with empty names")
    missing = [pid for pid in my_team["squad"] if pid not in ids]
    if len(my_team["squad"]) != config.SQUAD_SIZE:
        errors.append(f"squad has {len(my_team['squad'])} ids (expected {config.SQUAD_SIZE})")
    if len(set(my_team["squad"])) != len(my_team["squad"]):
        errors.append("duplicate ids in squad")
    if missing:
        errors.append(f"squad ids not in player list: {missing}")
    else:
        by_id = {p["id"]: p for p in players}
        shape: dict[str, int] = {}
        for pid in my_team["squad"]:
            pos = by_id[pid]["position"]
            shape[pos] = shape.get(pos, 0) + 1
        if shape != config.SQUAD_SHAPE:
            errors.append(f"squad shape {shape} != expected {config.SQUAD_SHAPE}")
    bad_own = [p["name"] for p in players
               if p["ownership_pct"] is not None and not 0 <= p["ownership_pct"] <= 100]
    if bad_own:
        errors.append(f"ownership out of range: {bad_own[:5]}")
    bad_price = [p["name"] for p in players if not 3.0 <= p["price"] <= 20.0]
    if len(bad_price) > 20:
        errors.append(f"{len(bad_price)} players with implausible prices, e.g. {bad_price[:5]}")
    bad_pos = {p["position"] for p in players} - {"GK", "DEF", "MID", "FWD"}
    if bad_pos:
        errors.append(f"unmapped positions: {bad_pos} - extend POSITION_MAP in tv2_client.py")
    unknown_teams = {p["team"] for p in players if data_access.normalize_team(p["team"]) == p["team"]
                     and p["team"] not in data_access.load_team_meta()}
    if unknown_teams:
        errors.append(f"team names that didn't normalize: {unknown_teams} - extend team_names.json")
    return errors


def git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def _append_league_history(tv2, league, cur_round, now) -> None:
    """Accumulate a per-round snapshot of every rival's squad so the app can show
    what changed between rounds. Keyed by round number; the latest snapshot for a
    round wins (so a round freezes once it advances)."""
    if cur_round is None:
        return
    path = tv2 / "league_history.json"
    hist = {}
    if path.exists():
        try:
            hist = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            hist = {}
    rounds = hist.setdefault("rounds", {})
    snap = {}
    for lg in league["leagues"]:
        for m in lg["members"]:
            if m.get("squad"):  # only snapshot once squads are revealed
                snap[m["squad_name"]] = {
                    "manager": m["manager"], "squad": m["squad"],
                    "starter_ids": m.get("starter_ids", []), "captain_id": m.get("captain_id"),
                    "formation": m.get("formation"), "total_points": m.get("total_points", 0),
                }
    if snap:
        rounds[str(cur_round)] = {"synced_at": now, "members": snap}
        path.write_text(json.dumps(hist, indent=1, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-odds", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--outrights", action="store_true", help="also refresh outright odds")
    parser.add_argument("--props", action="store_true", help="also refresh player goalscorer props")
    args = parser.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    client = Tv2Client()
    print("fetching TV 2 data through logged-in browser session...")
    raw = client.fetch_raw()
    players = client.normalize_players(raw["players"])
    my_team = client.normalize_my_team(raw["my_team"], raw.get("transfer_info"))

    errors = validate(players, my_team)
    if errors:
        print("VALIDATION FAILED - nothing written/committed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    tv2 = ROOT / "data" / "tv2"
    tv2.mkdir(parents=True, exist_ok=True)
    (tv2 / "players.json").write_text(
        json.dumps({"synced_at": now, "source": "xhr", "players": players},
                   indent=1, ensure_ascii=False), encoding="utf-8")
    (tv2 / "my_team.json").write_text(
        json.dumps({"synced_at": now, **my_team}, indent=1, ensure_ascii=False), encoding="utf-8")
    fixtures_written = 0
    if "fixtures" in raw:
        fixtures = client.normalize_fixtures(raw["fixtures"])
        if fixtures:  # never overwrite the good schedule with an empty list
            (tv2 / "fixtures.json").write_text(
                json.dumps({"source": "tv2+openfootball", "matches": fixtures},
                           indent=1, ensure_ascii=False), encoding="utf-8")
            fixtures_written = sum(1 for m in fixtures if m.get("status") == "finished")

    league = raw.get("_league") or {}
    if league.get("leagues"):
        cur_round = (raw.get("transfer_info") or {}).get("targetRound", {}).get("number")
        (tv2 / "league.json").write_text(
            json.dumps({"synced_at": now, "current_round": cur_round, **league},
                       indent=1, ensure_ascii=False), encoding="utf-8")
        _append_league_history(tv2, league, cur_round, now)
    (tv2 / "meta.json").write_text(json.dumps({
        "last_synced": now,
        "scraper_mode": "xhr",
        "player_count": len(players),
        "squad_name": my_team.get("squad_name"),
        "finished_fixtures": fixtures_written,
    }, indent=1), encoding="utf-8")
    print(f"wrote {len(players)} players, squad of {len(my_team['squad'])} "
          f"('{my_team.get('squad_name')}'), bank {my_team['bank']}M")

    odds_refreshed = False
    if not args.skip_odds:
        cmd = [sys.executable, str(ROOT / "scraper" / "refresh_odds.py")]
        if args.outrights:
            cmd.append("--outrights")
        if args.props:
            cmd.append("--props")
        odds_refreshed = subprocess.run(cmd).returncode == 0
        if not odds_refreshed:
            print("WARNING: odds refresh failed - committing TV 2 data only", file=sys.stderr)

    if args.dry_run:
        print("dry run - skipping git")
        return
    # stage only what this run produced and validated - never the whole data/ tree
    git("add", "data/tv2")
    if odds_refreshed:
        git("add", "data/odds")
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if result.returncode == 0:
        print("no data changes - nothing to commit")
        return
    git("commit", "-m", f"sync {now}")
    if not args.no_push:
        git("push")
        print("pushed - Streamlit Cloud will pick it up within a minute")


if __name__ == "__main__":
    main()
