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
        "next_round": data_access.next_round(fixtures),     # live round (being played)
        "target_round": data_access.target_round(fixtures),  # editable round (planning)
    }


def _project_round(b, p_plays, rnd):
    from src import analytics
    proj = projections.project(b["players"], b["fixtures"], b["match_odds"], b["outrights"],
                               b["completed"], rnd, p_plays)
    fixtures_next = proj.attrs.get("fixtures_next", [])
    proj = analytics.add_kpis(proj)
    proj.attrs["fixtures_next"] = fixtures_next
    return proj, fixtures_next


@st.cache_data(show_spinner="Crunching odds, weather and simulations...")
def _computed(sig: tuple, weather_bucket: str) -> dict:
    b = _bundle(sig)
    if b["players"] is None:
        return {"proj": None, "proj_plan": None, "adv": None, "fixtures_next": [], "fixtures_plan": []}
    from src import analytics
    adv = advancement.advancement_table(b["fixtures"], b["match_odds"], b["outrights"])
    p_plays = advancement.p_plays_lookup(adv)
    # live round: 'what's happening now' (race, games to watch, importance)
    proj, fixtures_next = _project_round(b, p_plays, b["next_round"])
    # editable round: planning your next team (My Team, Transfers, captain)
    if b["target_round"] == b["next_round"]:
        proj_plan, fixtures_plan = proj, fixtures_next
    else:
        proj_plan, fixtures_plan = _project_round(b, p_plays, b["target_round"])
    ranks = analytics.position_ranks(proj_plan, "xp_tournament")
    return {"proj": proj, "proj_plan": proj_plan, "adv": adv,
            "fixtures_next": fixtures_next, "fixtures_plan": fixtures_plan, "ranks": ranks}


def get_data() -> dict:
    sig = _data_sig()
    return {**_bundle(sig), **_computed(sig, _weather_bucket())}


@st.cache_data(show_spinner="Searching transfer plans (single + double swaps)...")
def _plans(sig: tuple, weather_bucket: str, squad: tuple, bank: float, free: int) -> list[dict]:
    from src import optimizer
    # transfers apply to the EDITABLE round you can still change (proj_plan),
    # NOT the live round that's already locked and scoring.
    proj = _computed(sig, weather_bucket)["proj_plan"]
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


def _fm_stat(blocks, key: str, exact: bool = False):
    """Pull a numeric from FotMob playerStats blocks. exact=True matches the
    label exactly (so 'goals' doesn't grab 'expected goals (xg)')."""
    kl = key.lower()
    for b in blocks or []:
        for label, payload in (b.get("stats") or {}).items():
            ll = label.strip().lower()
            if (ll == kl) if exact else (kl in ll):
                v = payload
                if isinstance(v, dict):
                    v = v.get("stat", v)
                    if isinstance(v, dict):
                        v = v.get("value")
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
    return None


@st.cache_data(ttl=60, show_spinner=False)
def _live_stats(sig: tuple, fixtures_key: tuple) -> dict:
    """LIVE match state for in-progress games from FotMob: the real score, a
    finished/started flag, and per-player live stats (minutes/rating/goals/
    assists/xg/shots/POTM). Keyed by TV2 match_id; players matched to TV2 ids by
    team + fuzzy name. Best-effort: returns {} on failure so the panel degrades."""
    try:
        from src.http_fetch import fetch_json
        from scraper.enrich_stats import _sim, find_match
    except Exception:
        return {}
    players = data_access.load_players()
    if players is None:
        return {}
    by_team = {}
    for pid, row in players.iterrows():
        by_team.setdefault(row["team"], []).append((pid, row["name"]))
    FM = "https://www.fotmob.com/api/data"
    out = {}
    for match_id, home, away, ko_date in fixtures_key:
        try:
            fm_id = find_match(ko_date, home, away)
            if not fm_id:
                continue
            md, _ = fetch_json(f"{FM}/matchDetails", {"matchId": fm_id}, timeout=20)
            if not md:
                continue
            header = md.get("header") or {}
            status = header.get("status") or {}
            finished = bool(status.get("finished"))
            started = bool(status.get("started"))
            teams = header.get("teams") or []
            score = None
            if len(teams) >= 2 and teams[0].get("score") is not None and teams[1].get("score") is not None:
                t0 = teams[0].get("name", "")
                if _sim(t0, home) >= _sim(t0, away):       # orient to our home/away
                    score = (teams[0].get("score"), teams[1].get("score"))
                else:
                    score = (teams[1].get("score"), teams[0].get("score"))
            content = md.get("content") or {}
            potm = (((content.get("matchFacts") or {}).get("playerOfTheMatch") or {}).get("id"))
            pmap = {}
            for fm_pid, p in (content.get("playerStats") or {}).items():
                blocks = p.get("stats") or []
                minutes = _fm_stat(blocks, "minutes played")
                if minutes is None:
                    continue
                line = {"name": p.get("name"), "team": p.get("teamName"), "minutes": minutes,
                        "rating": _fm_stat(blocks, "fotmob rating"),
                        "goals": _fm_stat(blocks, "goals", exact=True),
                        "assists": _fm_stat(blocks, "assists", exact=True),
                        "xg": _fm_stat(blocks, "expected goals (xg)"),
                        "shots": _fm_stat(blocks, "total shots"),
                        "is_potm": str(p.get("id")) == str(potm)}
                cands = by_team.get(data_access.normalize_team(line["team"] or ""), [])
                best, bpid = 0.6, None
                for pid, nm in cands:
                    s = _sim(nm, line["name"] or "")
                    if s > best:
                        best, bpid = s, pid
                if bpid:
                    pmap[bpid] = line
            out[match_id] = {"players": pmap, "score": score, "finished": finished, "started": started}
        except Exception:
            continue
    return out


def get_live_stats(in_progress_fixtures: list[dict]) -> dict:
    """in_progress_fixtures -> {match_id: {players: {pid: {minutes,rating,xg,...}}}}."""
    from datetime import datetime as _dt
    key = tuple(sorted(
        (fx["match_id"], fx["home"], fx["away"],
         _dt.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00")).strftime("%Y%m%d"))
        for fx in in_progress_fixtures))
    if not key:
        return {}
    return _live_stats(_data_sig(), key)


@st.cache_data(ttl=60, show_spinner=False)
def _live_league(_token: str) -> dict | None:
    """Live private-league standings straight from the TV 2 API (scores update
    during matches). For small leagues it also pulls each member's per-round
    squad detail (per-player scores, starters, captain, vice) LIVE — so the
    points race, the model-check and the standings all move together during
    matches, not just on the hourly sync."""
    from src.http_fetch import fetch_json
    base = "https://vm-fantasyapi-production.up.railway.app"
    h = {"Authorization": f"Bearer {_token}", "Accept": "application/json"}
    try:
        summary, _ = fetch_json(f"{base}/leagues/summary", {"tournamentId": "vm-2026"}, headers=h, timeout=10)
        if not summary:
            return None
        from scraper.tv2_client import Tv2Client  # pure parser; no playwright at import
        leagues = []
        for lg in summary:
            if lg.get("leagueType") == "MAIN":
                continue
            lb, _ = fetch_json(f"{base}/leagues/{lg['leagueId']}/leaderboard",
                               {"page": 1, "limit": 100}, headers=h, timeout=10)
            lb = lb or {}
            entries = lb.get("entries", [])
            fetch_squads = len(entries) <= config.LEAGUE_SQUAD_FETCH_MAX
            members = []
            for e in entries:
                m = {"manager": e.get("managerName"), "squad_name": e.get("squadName"),
                     "squad_id": e.get("squadId"), "rank": e.get("rank"),
                     "total_points": e.get("totalPoints", 0),
                     "latest_round_points": e.get("latestRoundPoints", 0),
                     "round_scores": e.get("roundScores", [])}
                if fetch_squads and e.get("squadId"):
                    try:
                        view, _ = fetch_json(f"{base}/squad/view/{e['squadId']}", headers=h, timeout=10)
                        m.update(Tv2Client._parse_rival_view(view or {}))
                    except Exception:
                        pass
                members.append(m)
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
