"""One-off: normalize the openfootball WC2026 schedule into data/static/fixtures_fallback.json.

Usage:  python scraper/build_static.py [path-to-openfootball-json]
Default input: %TEMP%/openfootball_2026.json (downloaded during project setup).
Re-run if openfootball updates results (it lags live matches by up to a day).
"""
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STAGE_MAP = {
    "Round of 32": ("r32", 4),
    "Round of 16": ("r16", 5),
    "Quarter-final": ("qf", 6),
    "Semi-final": ("sf", 7),
    "Match for third place": ("third", 8),
    "Final": ("final", 8),
}


def ascii_fold(name: str) -> str:
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()


def team_name(raw) -> str:
    # knockout placeholders arrive as dicts or strings depending on openfootball vintage
    if isinstance(raw, dict):
        raw = raw.get("name", str(raw))
    return ascii_fold(str(raw).strip())


def parse_kickoff(date_str: str, time_str: str | None) -> str:
    """'2026-06-11' + '13:00 UTC-6' -> UTC ISO string."""
    if not time_str:
        return f"{date_str}T18:00:00+00:00"  # placeholder midday-ish in NA
    m = re.match(r"(\d{1,2}):(\d{2})\s*UTC([+-]\d{1,2})?", time_str)
    if not m:
        return f"{date_str}T18:00:00+00:00"
    hh, mm = int(m.group(1)), int(m.group(2))
    offset = int(m.group(3) or 0)
    local = datetime.fromisoformat(date_str).replace(
        hour=hh, minute=mm, tzinfo=timezone(timedelta(hours=offset))
    )
    return local.astimezone(timezone.utc).isoformat()


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ.get("TEMP", "/tmp")) / "openfootball_2026.json"
    raw = json.loads(src.read_text(encoding="utf-8"))

    matches_per_team: dict[str, int] = {}
    out = []
    for i, m in enumerate(raw["matches"], start=1):
        home, away = team_name(m["team1"]), team_name(m["team2"])
        round_label = m.get("round", "")
        group = (m.get("group") or "").replace("Group ", "") or None
        if group:
            stage = "group"
            matches_per_team[home] = matches_per_team.get(home, 0) + 1
            matches_per_team[away] = matches_per_team.get(away, 0) + 1
            # both teams are on the same group-match number by construction
            fantasy_round = matches_per_team[home]
        else:
            stage, fantasy_round = STAGE_MAP.get(round_label, ("unknown", None))
        out.append({
            "match_id": f"M{i:03d}",
            "stage": stage,
            "fantasy_round": fantasy_round,
            "group": group,
            "home": home,
            "away": away,
            "kickoff_utc": parse_kickoff(m["date"], m.get("time")),
            "venue_id": m.get("ground"),
            "status": "finished" if m.get("score1") is not None else "scheduled",
            "score_home": m.get("score1"),
            "score_away": m.get("score2"),
        })

    dest = ROOT / "data" / "static" / "fixtures_fallback.json"
    dest.write_text(json.dumps({"source": "openfootball", "matches": out}, indent=1, ensure_ascii=False), encoding="utf-8")

    groups = sorted({m["group"] for m in out if m["group"]})
    teams = sorted({m["home"] for m in out if m["stage"] == "group"} | {m["away"] for m in out if m["stage"] == "group"})
    print(f"wrote {len(out)} matches -> {dest}")
    print(f"groups: {groups}")
    print(f"teams ({len(teams)}): {teams}")
    bad_rounds = [m for m in out if m["stage"] == "group" and m["fantasy_round"] not in (1, 2, 3)]
    print(f"group matches with bad fantasy_round: {len(bad_rounds)}")


if __name__ == "__main__":
    main()
