"""Single loader for every JSON file the app reads. Pure (no Streamlit) so the
scraper, tests and app all share it; Streamlit caching lives in src/services.py.
"""
import difflib
import json
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src import config


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _fold(name: str) -> str:
    return unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().strip().lower()


# ---------------------------------------------------------------- static data

def load_team_meta() -> dict:
    return _read_json(config.STATIC_DIR / "team_names.json")["teams"]


def _alias_map() -> dict[str, str]:
    aliases = {}
    for canonical, info in load_team_meta().items():
        for alias in [canonical, info["tv2"], info["code"], *info.get("odds_aliases", [])]:
            aliases[_fold(alias)] = canonical
    return aliases


_ALIASES: dict[str, str] | None = None


def normalize_team(name: str) -> str:
    """Any spelling (Norwegian, odds-API, FIFA code) -> canonical English name."""
    global _ALIASES
    if _ALIASES is None:
        _ALIASES = _alias_map()
    folded = _fold(name)
    if folded in _ALIASES:
        return _ALIASES[folded]
    close = difflib.get_close_matches(folded, _ALIASES.keys(), n=1, cutoff=0.85)
    return _ALIASES[close[0]] if close else str(name)


def load_stadiums() -> dict[str, dict]:
    data = _read_json(config.STATIC_DIR / "stadiums.json")
    return {s["venue_id"]: s for s in data["stadiums"]}


def load_climate() -> dict[str, str]:
    return _read_json(config.STATIC_DIR / "team_climate.json")["climate"]


# ---------------------------------------------------------------- tv2 data

def load_players() -> pd.DataFrame | None:
    data = _read_json(config.TV2_DIR / "players.json")
    if not data:
        return None
    df = pd.DataFrame(data["players"])
    df["team"] = df["team"].map(normalize_team)
    df["round_points"] = df["round_points"].apply(lambda d: {int(k): v for k, v in (d or {}).items()})
    df.attrs["synced_at"] = data.get("synced_at")
    df.attrs["source"] = data.get("source", "unknown")
    return df.set_index("id", drop=False)


def load_my_team() -> dict | None:
    return _read_json(config.TV2_DIR / "my_team.json")


def load_fixtures() -> list[dict]:
    """TV 2 fixtures if synced, else the openfootball fallback (same schema)."""
    data = _read_json(config.TV2_DIR / "fixtures.json") or _read_json(config.STATIC_DIR / "fixtures_fallback.json")
    fixtures = data["matches"]
    for m in fixtures:
        # knockout placeholders ("Winner Group A") pass through unchanged -
        # normalize_team returns unknown names as-is
        m["home"] = normalize_team(m["home"])
        m["away"] = normalize_team(m["away"])
    return fixtures


def load_league() -> dict | None:
    return _read_json(config.TV2_DIR / "league.json")


def load_league_history() -> dict:
    return _read_json(config.TV2_DIR / "league_history.json") or {}


def load_player_stats() -> dict:
    """FotMob-enriched per-round per-player stats (minutes/rating/xg/xa), or {}."""
    return _read_json(config.TV2_DIR / "player_stats.json") or {}


def load_duties() -> dict[str, dict]:
    data = _read_json(config.STATIC_DIR / "duties.json")
    return (data or {}).get("duties", {})


def duty_rank(folded_name: str, duty_list: list[str]) -> int | None:
    """Rank of a player in a duty list. Match: exact folded name, exact last
    name, or a distinctive (>=6 char) substring."""
    last = folded_name.split()[-1] if folded_name else ""
    for rank, key in enumerate(duty_list):
        if key == folded_name or key == last or (len(key) >= 6 and key in folded_name):
            return rank
    return None


def load_meta() -> dict:
    meta = _read_json(config.TV2_DIR / "meta.json") or {}
    synced = meta.get("last_synced")
    stale = True
    if synced:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(synced)
        stale = age > timedelta(hours=config.STALE_AFTER_HOURS)
        meta["age_hours"] = round(age.total_seconds() / 3600, 1)
    meta["is_stale"] = stale
    return meta


# ---------------------------------------------------------------- odds data

def load_match_odds() -> dict | None:
    return _read_json(config.ODDS_DIR / "match_odds.json")


def load_outrights() -> dict | None:
    return _read_json(config.ODDS_DIR / "outrights.json")


def load_player_odds() -> dict[tuple[str, str], dict]:
    """(canonical_team, folded_name) -> {anytime_goal, assist} decimal odds.
    A player is indexed under both fixture sides so lookup by their own team
    works regardless of home/away."""
    data = _read_json(config.ODDS_DIR / "player_odds.json")
    if not data:
        return {}
    out: dict[tuple[str, str], dict] = {}
    for p in data.get("players", []):
        rec = {"anytime_goal": p.get("anytime_goal"), "assist": p.get("assist")}
        for team in (p.get("home"), p.get("away")):
            if team:
                out[(normalize_team(team), _fold(p["name"]))] = rec
    return out


# ---------------------------------------------------------------- round helpers

def completed_rounds(fixtures: list[dict]) -> list[int]:
    rounds: dict[int, list[str]] = {}
    for m in fixtures:
        if m.get("fantasy_round"):
            rounds.setdefault(m["fantasy_round"], []).append(m.get("status", "scheduled"))
    return sorted(r for r, statuses in rounds.items() if all(s == "finished" for s in statuses))


def next_round(fixtures: list[dict]) -> int:
    """The LIVE round = the earliest round still being played (has a match not
    yet finished). This is what 'happening now' refers to: live points race,
    games to watch, importance. While round 1's matches run, this stays 1."""
    unfinished = [m["fantasy_round"] for m in fixtures
                  if m.get("fantasy_round") and m.get("status") != "finished"]
    return min(unfinished) if unfinished else max((m.get("fantasy_round") or 0 for m in fixtures), default=1)


def target_round(fixtures: list[dict]) -> int:
    """The EDITABLE round = the earliest round whose first kickoff is still in
    the future (it locks at its first match, like TV 2's deadline). This is the
    round to plan/captain/transfer for; while round 1 plays, this is round 2."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    first_ko: dict[int, datetime] = {}
    for m in fixtures:
        r, ko_s = m.get("fantasy_round"), m.get("kickoff_utc")
        if not r or not ko_s:
            continue
        ko = datetime.fromisoformat(ko_s.replace("Z", "+00:00"))
        if r not in first_ko or ko < first_ko[r]:
            first_ko[r] = ko
    upcoming = [r for r, ko in first_ko.items() if ko > now]
    return min(upcoming) if upcoming else next_round(fixtures)


def round_fixtures(fixtures: list[dict], round_no: int) -> list[dict]:
    return [m for m in fixtures if m.get("fantasy_round") == round_no]
