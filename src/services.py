"""Streamlit-cached orchestration layer shared by all pages.

Caches are keyed on the content signature of the data files (so a synced push
invalidates instantly) plus a 6-hour weather bucket (so forecasts refresh).
"""
from datetime import datetime, timezone

import streamlit as st

from src import advancement, config, data_access, projections


def _data_sig() -> tuple:
    files = []
    for d in (config.TV2_DIR, config.ODDS_DIR, config.STATIC_DIR):
        files.extend(sorted(d.glob("*.json")))
    return tuple((f.name, f.stat().st_mtime_ns) for f in files)


def _weather_bucket() -> str:
    now = datetime.now(timezone.utc)
    return f"{now:%Y%m%d}-{now.hour // 6}"


@st.cache_data(show_spinner=False)
def _bundle(sig: tuple) -> dict:
    fixtures = data_access.load_fixtures()
    return {
        "players": data_access.load_players(),
        "my_team": data_access.load_my_team(),
        "fixtures": fixtures,
        "meta": data_access.load_meta(),
        "match_odds": data_access.load_match_odds(),
        "outrights": data_access.load_outrights(),
        "completed": data_access.completed_rounds(fixtures),
        "next_round": data_access.next_round(fixtures),
    }


@st.cache_data(show_spinner="Crunching odds, weather and simulations...")
def _computed(sig: tuple, weather_bucket: str) -> dict:
    b = _bundle(sig)
    if b["players"] is None:
        return {"proj": None, "adv": None, "fixtures_next": []}
    adv = advancement.advancement_table(b["fixtures"], b["match_odds"], b["outrights"])
    p_plays = advancement.p_plays_lookup(adv)
    proj = projections.project(
        b["players"], b["fixtures"], b["match_odds"], b["outrights"],
        b["completed"], b["next_round"], p_plays,
    )
    return {"proj": proj, "adv": adv, "fixtures_next": proj.attrs.get("fixtures_next", [])}


def get_data() -> dict:
    sig = _data_sig()
    return {**_bundle(sig), **_computed(sig, _weather_bucket())}


@st.cache_data(show_spinner="Searching transfer plans (single + double swaps)...")
def _plans(sig: tuple, weather_bucket: str, squad: tuple, bank: float, free: int) -> list[dict]:
    from src import optimizer
    proj = _computed(sig, weather_bucket)["proj"]
    return optimizer.transfer_plans(proj, list(squad), bank, free_transfers=free)


def get_transfer_plans(squad: list[str], bank: float, free: int) -> list[dict]:
    return _plans(_data_sig(), _weather_bucket(), tuple(squad), float(bank), int(free))


@st.cache_data(show_spinner="Building the model's optimal squad...")
def _optimal(sig: tuple, weather_bucket: str, value_col: str) -> dict:
    from src import squad_builder
    proj = _computed(sig, weather_bucket)["proj"]
    if proj is None:
        return {}
    return squad_builder.build_optimal_squad(proj, value_col=value_col)


def get_optimal_squad(value_col: str = "xp_tournament") -> dict:
    return _optimal(_data_sig(), _weather_bucket(), value_col)


@st.cache_data(ttl=120, show_spinner=False)
def _live_league(_token: str) -> dict | None:
    """Live private-league standings straight from the TV 2 API (scores update
    during matches). Light: leaderboard only, no per-member squad fetches —
    squads/formations come from the synced league.json."""
    import requests
    base = "https://vm-fantasyapi-production.up.railway.app"
    h = {"Authorization": f"Bearer {_token}", "Accept": "application/json"}
    try:
        summary = requests.get(f"{base}/leagues/summary", params={"tournamentId": "vm-2026"},
                               headers=h, timeout=10).json()
        leagues = []
        for lg in summary:
            if lg.get("leagueType") == "MAIN":
                continue
            lb = requests.get(f"{base}/leagues/{lg['leagueId']}/leaderboard",
                              params={"page": 1, "limit": 100}, headers=h, timeout=10).json()
            members = [{
                "manager": e.get("managerName"), "squad_name": e.get("squadName"),
                "rank": e.get("rank"), "total_points": e.get("totalPoints", 0),
                "latest_round_points": e.get("latestRoundPoints", 0),
                "round_scores": e.get("roundScores", []),
            } for e in lb.get("entries", [])]
            leagues.append({"name": lg.get("leagueName"), "league_id": lg.get("leagueId"),
                            "my_rank": (lb.get("myRank") or {}).get("rank"), "members": members})
        return {"leagues": leagues} if leagues else None
    except Exception:
        return None


def get_live_league() -> dict | None:
    """Returns live standings when a TV2_TOKEN is available (Streamlit secret
    or env), else None (the page falls back to the synced snapshot)."""
    import os
    token = None
    try:
        token = st.secrets.get("TV2_TOKEN")
    except Exception:
        token = None
    token = token or os.environ.get("TV2_TOKEN")
    return _live_league(token) if token else None


def render_banners(d: dict) -> None:
    """Shared warning banners: stale sync, seed data, unverified scoring."""
    meta, players = d["meta"], d["players"]
    if players is None:
        st.error("No player data yet - run `python scraper/sync.py` locally (see README).")
        return
    source = players.attrs.get("source", "unknown")
    if source == "seed":
        st.warning("⚠️ Running on **seed data** (estimated prices, no ownership). "
                   "Run the TV 2 sync to get real data: `python scraper/sync.py`")
    if d["my_team"] is None:
        st.error("No team data - run `python scraper/sync.py` (or `python scraper/manual_entry.py`) locally.")
    if meta.get("is_stale"):
        age = meta.get("age_hours")
        st.error(f"🕐 Data is stale ({age if age is not None else '?'}h old). "
                 "Run `python scraper/sync.py` on your PC.")
    if not config.SCORING_VERIFIED:
        st.info("ℹ️ Scoring table is FPL-style **default, not yet verified against TV 2's rules**. "
                "Verify after the first sync (see README) - projections may shift slightly.")
