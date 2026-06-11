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
    missing = [pid for pid in my_team["squad"] if pid not in ids]
    if len(my_team["squad"]) != config.SQUAD_SIZE:
        errors.append(f"squad has {len(my_team['squad'])} ids (expected {config.SQUAD_SIZE})")
    if missing:
        errors.append(f"squad ids not in player list: {missing}")
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-odds", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--outrights", action="store_true", help="also refresh outright odds")
    args = parser.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    client = Tv2Client()
    print("fetching TV 2 data through logged-in browser session...")
    raw = client.fetch_raw()
    players = client.normalize_players(raw["players"])
    my_team = client.normalize_my_team(raw["my_team"])

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
    if "fixtures" in raw:
        # fixtures normalization depends on the discovered payload shape; until
        # then the app falls back to data/static/fixtures_fallback.json
        (tv2 / "fixtures_raw.json").write_text(
            json.dumps(raw["fixtures"], indent=1, ensure_ascii=False)[:2_000_000], encoding="utf-8")
    (tv2 / "meta.json").write_text(json.dumps({
        "last_synced": now,
        "scraper_mode": "xhr",
        "player_count": len(players),
    }, indent=1), encoding="utf-8")
    print(f"wrote {len(players)} players, squad of {len(my_team['squad'])}")

    if not args.skip_odds:
        cmd = [sys.executable, str(ROOT / "scraper" / "refresh_odds.py")]
        if args.outrights:
            cmd.append("--outrights")
        subprocess.run(cmd, check=True)

    if args.dry_run:
        print("dry run - skipping git")
        return
    git("add", "data/")
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
