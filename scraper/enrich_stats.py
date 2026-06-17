"""Post-match enrichment: pull per-player minutes / match-rating / xG / xA /
shots from FotMob's free public API for FINISHED fixtures, map them to our
player ids, and accumulate into data/tv2/player_stats.json.

Verified (2026-06-12) free + keyless + reachable from GitHub Actions; responses
are CloudFront-edge-cached 15 min, so hourly polling is safe. This is the
mathematical-edge feed: minutes are the single most predictive fantasy signal
and the FotMob rating is a clean Man-of-the-Match / form proxy that TV 2's
fantasy points alone don't capture.

Best-effort by design: any failure (FotMob change, unmapped name) is logged and
skipped — it never blocks the sync. Run after sync.py in the workflow.
"""
import json
import sys
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import data_access  # noqa: E402
from src.http_fetch import fetch_json  # noqa: E402

FM = "https://www.fotmob.com/api/data"
OUT = ROOT / "data" / "tv2" / "player_stats.json"


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _fold(a), _fold(b)).ratio()


def _stat(stats_blocks, key):
    """FotMob playerStats[*]['stats'] is a list of titled groups, each with a
    'stats' dict of {label: {'stat': {'value': X}}}. Pull a numeric by label."""
    for block in stats_blocks or []:
        for label, payload in (block.get("stats") or {}).items():
            if key.lower() in label.lower():
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


_MATCHES_ON_DATE: dict = {}    # date -> FotMob /matches listing; match IDs are stable, so cache it


def _wc_matches_on(date_yyyymmdd: str) -> dict:
    """The FotMob /matches listing for a date, fetched once per date per process
    (several fixtures share a kickoff date, and the listing only resolves stable
    match IDs — scores come from /matchDetails, which is never cached here). Only
    NON-EMPTY listings are cached: a transient empty/failed fetch must retry on the
    next call, else a long-lived Streamlit process would show no live cards all day."""
    cached = _MATCHES_ON_DATE.get(date_yyyymmdd)
    if cached:
        return cached
    data, _ = fetch_json(f"{FM}/matches", {"date": date_yyyymmdd}, timeout=20)
    if data:
        _MATCHES_ON_DATE[date_yyyymmdd] = data
    return data or {}


def find_match(date_yyyymmdd: str, home: str, away: str) -> int | None:
    data = _wc_matches_on(date_yyyymmdd)
    if not data:
        return None
    best, best_id = 0.55, None
    for lg in data.get("leagues", []):
        if "world cup" not in _fold(lg.get("name", "")):
            continue
        for m in lg.get("matches", []):
            h, a = m.get("home", {}).get("name", ""), m.get("away", {}).get("name", "")
            score = (_sim(h, home) + _sim(a, away)) / 2
            if score > best:
                best, best_id = score, m.get("id")
    return best_id


def player_lines(match_id: int) -> list[dict]:
    md, _ = fetch_json(f"{FM}/matchDetails", {"matchId": match_id}, timeout=25)
    if not md:
        return []
    ps = (md.get("content") or {}).get("playerStats") or {}
    potm = (((md.get("content") or {}).get("matchFacts") or {}).get("playerOfTheMatch") or {}).get("id")
    out = []
    for pid, p in ps.items():
        blocks = p.get("stats") or []
        minutes = _stat(blocks, "minutes played")
        if minutes is None and not p.get("shotmap"):
            continue  # didn't feature / no data
        out.append({
            "fm_id": pid, "name": p.get("name"), "team": p.get("teamName"),
            "minutes": minutes, "rating": _stat(blocks, "fotmob rating"),
            "xg": _stat(blocks, "expected goals (xg)"), "xa": _stat(blocks, "expected assists"),
            "shots": _stat(blocks, "total shots"), "sot": _stat(blocks, "shots on target"),
            "is_potm": str(p.get("id")) == str(potm),
        })
    return out


def main() -> None:
    players = data_access.load_players()
    fixtures = data_access.load_fixtures()
    if players is None:
        sys.exit("no players.json - run sync first")
    # name -> id within each team, for mapping FotMob names back to our ids
    by_team = {}
    for pid, row in players.iterrows():
        by_team.setdefault(row["team"], []).append((pid, row["name"]))

    store = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"rounds": {}, "updated": None}
    finished = [fx for fx in fixtures if fx.get("status") == "finished" and fx.get("fantasy_round")]
    matched = enriched = 0
    for fx in finished:
        rnd = str(fx["fantasy_round"])
        if fx["match_id"] in store["rounds"].get(rnd, {}).get("_done", []):
            continue
        ko = datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00"))
        mid = find_match(ko.strftime("%Y%m%d"), fx["home"], fx["away"])
        if not mid:
            continue
        matched += 1
        rd = store["rounds"].setdefault(rnd, {"_done": [], "players": {}})
        for line in player_lines(mid):
            cands = by_team.get(data_access.normalize_team(line["team"] or ""), [])
            best, best_pid = 0.6, None
            for pid, nm in cands:
                s = _sim(nm, line["name"] or "")
                if s > best:
                    best, best_pid = s, pid
            if best_pid:
                rd["players"][best_pid] = {k: line[k] for k in
                                           ("minutes", "rating", "xg", "xa", "shots", "sot", "is_potm")}
                enriched += 1
        rd["_done"].append(fx["match_id"])
    store["updated"] = datetime.now(timezone.utc).isoformat()
    OUT.write_text(json.dumps(store, indent=1), encoding="utf-8")
    print(f"enriched {enriched} player-lines across {matched} newly-finished matches")


if __name__ == "__main__":
    main()
