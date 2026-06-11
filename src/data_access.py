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
    unfinished = [m["fantasy_round"] for m in fixtures
                  if m.get("fantasy_round") and m.get("status") != "finished"]
    return min(unfinished) if unfinished else max(m.get("fantasy_round") or 0 for m in fixtures)


def round_fixtures(fixtures: list[dict], round_no: int) -> list[dict]:
    return [m for m in fixtures if m.get("fantasy_round") == round_no]
