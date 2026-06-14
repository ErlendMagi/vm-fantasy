"""Pre-deadline lineup signal: pull FotMob predicted/confirmed XIs for the
imminent round's fixtures and write data/tv2/predicted_lineups.json, mapping each
of our players to a role: 'start' (in the XI), 'bench' (named sub), or 'out'
(absent from the matchday squad -> injured / suspended / dropped).

This is the highest-leverage accuracy signal: before games the model otherwise
only has a price-rank prior and cannot tell a nailed starter from a benched one
(the round-1 Germany rotation that cost a clean sheet + two benched defenders).
Confirmed XIs land ~1h before kickoff, inside the autopilot's deadline window, so
captain/lineup decisions act on the real XI. Best-effort; writes nothing on failure.

Run by the cloud workflow just before the autopilot step.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import config, data_access  # noqa: E402
from src.http_fetch import fetch_json  # noqa: E402
from scraper.enrich_stats import _sim, find_match  # noqa: E402

FM = "https://www.fotmob.com/api/data"
OUT = ROOT / "data" / "tv2" / "predicted_lineups.json"


def _role(name: str, starters: list[str], subs: list[str]) -> str | None:
    """Best fuzzy match of our player's name against the FotMob XI / subs."""
    bs = max((_sim(name, s) for s in starters), default=0.0)
    bb = max((_sim(name, s) for s in subs), default=0.0)
    if max(bs, bb) < 0.6:
        return "out"            # not in the 26-man matchday squad -> unavailable
    return "start" if bs >= bb else "bench"


def main() -> None:
    players = data_access.load_players()
    fixtures = data_access.load_fixtures()
    if players is None:
        sys.exit("no players.json - run sync first")
    by_team = {}
    for pid, row in players.iterrows():
        by_team.setdefault(row["team"], []).append((pid, row["name"]))

    now = datetime.now(timezone.utc)
    window = now + timedelta(hours=config.LINEUP_WINDOW_HOURS)
    upcoming = []
    for fx in fixtures:
        if not fx.get("fantasy_round") or fx.get("status") == "finished":
            continue
        ko = datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00"))
        if now - timedelta(hours=1) < ko < window:
            upcoming.append(fx)

    out = {"updated": now.isoformat(), "players": {}}
    matched = 0
    for fx in sorted(upcoming, key=lambda f: f["kickoff_utc"]):
        try:
            mid = find_match(fx["kickoff_utc"][:10].replace("-", ""), fx["home"], fx["away"])
            if not mid:
                continue
            md, _ = fetch_json(f"{FM}/matchDetails", {"matchId": mid}, timeout=20)
            lineup = ((md or {}).get("content") or {}).get("lineup")
            if not lineup or not lineup.get("homeTeam"):
                continue
            ltype = "standard" if lineup.get("lineupType") == "standard" else "predicted"
            for side in ("homeTeam", "awayTeam"):
                tm = lineup.get(side) or {}
                starters = [p.get("name", "") for p in (tm.get("starters") or [])]
                subs = [p.get("name", "") for p in (tm.get("subs") or [])]
                if len(starters) < 11:
                    continue                      # not a real XI yet
                our_team = data_access.normalize_team(tm.get("name") or "")
                for pid, nm in by_team.get(our_team, []):
                    role = _role(nm, starters, subs)
                    # only trust 'out' from a CONFIRMED lineup (predicted omissions are noisy)
                    if role == "out" and ltype != "standard":
                        continue
                    out["players"][pid] = {"role": role, "type": ltype,
                                           "round": fx["fantasy_round"], "ko": fx["kickoff_utc"]}
                    matched += 1
        except Exception as exc:
            print(f"lineup fetch skipped for {fx['home']}-{fx['away']}: {exc}", file=sys.stderr)

    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"predicted lineups: {len(upcoming)} fixtures in window, {matched} player roles written")


if __name__ == "__main__":
    main()
