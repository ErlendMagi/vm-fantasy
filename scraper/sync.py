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


def backfill_player_points(players: list[dict], league: dict) -> int:
    """TV2 stops sending per-player match scores (playerMatchScores) once the knockouts start, so
    every player comes back with total_points 0. Reconstruct each player's points from the LEAGUE
    round data (which DOES carry them), de-doubling the captain — base points are identical for
    every owner, so the first entry seen per round wins. Only fills players whose points are empty,
    so it never overwrites real data TV2 still provides. Returns how many players were filled."""
    base: dict[str, dict] = {}
    for lg in league.get("leagues", []):
        for m in lg.get("members", []):
            for r in (m.get("rounds") or []):
                rn, cap = r.get("number"), r.get("captain_id")
                if rn is None:
                    continue
                for pid, v in (r.get("scores") or {}).items():
                    if v is not None:
                        base.setdefault(pid, {}).setdefault(rn, (v / 2) if pid == cap else v)
    filled = 0
    for p in players:
        if p.get("total_points"):                     # keep any real data TV2 does still provide
            continue
        rp = base.get(p["id"])
        if rp:
            p["round_points"] = {str(k): int(round(x)) for k, x in rp.items()}
            p["total_points"] = int(round(sum(rp.values())))
            filled += 1
    return filled


def validate(players: list[dict], my_team: dict) -> tuple[list[str], list[str]]:
    """Returns (fatal, warnings). FATAL = a broken/partial payload — do NOT write. WARNINGS =
    tolerable knockout-phase realities that must NOT block the sync, or the site freezes for the
    rest of the cup: once a team is eliminated TV2 drops its players from the pool, so a few of
    your squad ids legitimately go missing (they're kept as-is and ignored everywhere downstream)."""
    fatal, warn = [], []
    if len(players) < 30:              # a real pool stays >=~50 even at the final; below = broken fetch
        fatal.append(f"only {len(players)} players - partial/broken payload?")
    ids = {p["id"] for p in players}
    if len(ids) != len(players):
        fatal.append(f"{len(players) - len(ids)} duplicate player ids in payload")
    if any(not p.get("name") for p in players):
        fatal.append("players with empty names")
    bad_own = [p["name"] for p in players
               if p["ownership_pct"] is not None and not 0 <= p["ownership_pct"] <= 100]
    if bad_own:
        fatal.append(f"ownership out of range: {bad_own[:5]}")
    bad_price = [p["name"] for p in players if not 3.0 <= p["price"] <= 20.0]
    if len(bad_price) > 20:
        fatal.append(f"{len(bad_price)} players with implausible prices, e.g. {bad_price[:5]}")
    bad_pos = {p["position"] for p in players} - {"GK", "DEF", "MID", "FWD"}
    if bad_pos:
        fatal.append(f"unmapped positions: {bad_pos} - extend POSITION_MAP in tv2_client.py")
    unknown_teams = {p["team"] for p in players if data_access.normalize_team(p["team"]) == p["team"]
                     and p["team"] not in data_access.load_team_meta()}
    if unknown_teams:
        fatal.append(f"team names that didn't normalize: {unknown_teams} - extend team_names.json")
    # squad checks — tolerant of the knockout phase (eliminated players leave the pool)
    sq = my_team["squad"]
    if len(set(sq)) != len(sq):
        fatal.append("duplicate ids in squad")            # a player can't be owned twice -> parse bug
    by_id = {p["id"]: p for p in players}
    shape: dict[str, int] = {}
    for pid in sq:
        if pid in by_id:                                  # only present players (eliminated ones can't be looked up)
            shape[by_id[pid]["position"]] = shape.get(by_id[pid]["position"], 0) + 1
    over = {pos: n for pos, n in shape.items() if n > config.SQUAD_SHAPE.get(pos, 0)}
    if over:                                              # MORE than allowed of a position -> broken payload
        fatal.append(f"squad shape over limit {over} vs {config.SQUAD_SHAPE}")
    missing = [pid for pid in sq if pid not in by_id]
    if missing:
        warn.append(f"{len(missing)} squad player(s) no longer in the pool (team eliminated) — "
                    "kept as-is, ignored downstream")
    if len(sq) != config.SQUAD_SIZE:
        warn.append(f"squad has {len(sq)} ids (expected {config.SQUAD_SIZE})")
    return fatal, warn


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

    _league = raw.get("_league") or {}
    if _league.get("leagues") and not any(p.get("total_points") for p in players):
        _filled = backfill_player_points(players, _league)
        if _filled:
            print(f"backfilled points for {_filled} players from league round data "
                  "(TV2 omits per-player match scores in the knockouts)")

    fatal, warnings = validate(players, my_team)
    for w in warnings:
        print(f"  ~ {w}", file=sys.stderr)
    if fatal:
        print("VALIDATION FAILED - nothing written/committed:", file=sys.stderr)
        for e in fatal:
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
        cur_round = ((raw.get("transfer_info") or {}).get("targetRound") or {}).get("number")
        if cur_round is None:  # derive from the rounds payload: first not-yet-finished round
            rounds = sorted(raw.get("fixtures") or [], key=lambda r: r.get("number", 0))
            now_iso = now
            cur_round = next((r["number"] for r in rounds if (r.get("endsAt") or "") > now_iso),
                             rounds[-1]["number"] if rounds else None)
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
