"""TV 2 VM Fantasy client: replays the game's internal JSON endpoints using the
logged-in Playwright session (cookies live in playwright-profile/).

Backend discovered 2026-06-11: vm-fantasyapi-production.up.railway.app, a plain
REST API. Endpoints in scraper/endpoints.json. The parsers below target that
API's real payload shapes; price is in cents (priceCents / 1e6 = game M unit),
positions already come as GK/DEF/MID/FWD, ownership as a percentage.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "playwright-profile"
ENDPOINTS_FILE = Path(__file__).parent / "endpoints.json"
sys.path.insert(0, str(ROOT))
from src import config, data_access  # noqa: E402
from src.http_fetch import fetch_json  # noqa: E402

PRICE_DIVISOR = 1_000_000  # priceCents -> game "M" unit (budget 100)

FINISHED_STATUSES = {"FINISHED", "FT", "AET", "PEN", "ENDED", "COMPLETE", "AWARDED"}


class Tv2Client:
    def __init__(self):
        if not ENDPOINTS_FILE.exists():
            raise FileNotFoundError(
                f"{ENDPOINTS_FILE} missing. Run discover_endpoints.py first and fill in the URLs."
            )
        self.endpoints = json.loads(ENDPOINTS_FILE.read_text(encoding="utf-8"))
        for key in ("players", "my_team", "fixtures"):
            if self.endpoints.get(key, "https://...") == "https://...":
                raise ValueError(f"endpoints.json: '{key}' URL not filled in yet.")

    def fetch_raw(self) -> dict[str, dict]:
        """All configured endpoints + private-league data. Token mode
        (TV2_TOKEN env) uses plain HTTP for the cloud; otherwise the logged-in
        browser channel (reliable for the large payloads behind local TLS
        interception). Both go through one `get(url)` closure."""
        token = os.environ.get("TV2_TOKEN")
        if token:
            headers = {"Authorization": f"Bearer {token}",
                       "User-Agent": "Mozilla/5.0", "Accept": "application/json"}

            def get(url):
                return fetch_json(url, timeout=30, headers=headers)[0]

            return self._collect(get)

        from playwright.sync_api import sync_playwright  # lazy: scraper-only dep
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(PROFILE), headless=True, ignore_https_errors=True)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            cap: dict[str, str] = {}
            page.on("request", lambda rq: cap.__setitem__("a", rq.headers.get("authorization"))
                    if rq.headers.get("authorization") and "railway.app" in rq.url else None)
            page.goto("https://vmfantasy.tv2.no/", wait_until="networkidle")
            auth = {"Authorization": cap["a"]} if "a" in cap else {}

            def get(url):
                r = ctx.request.get(url, headers=auth)
                return r.json() if r.ok else None

            try:
                return self._collect(get)
            finally:
                ctx.close()

    def _collect(self, get) -> dict[str, dict]:
        raw = {}
        for key, url in self.endpoints.items():
            if key.startswith("_") or url == "https://...":
                continue
            payload = get(url)
            if payload is None:
                raise RuntimeError(f"{key}: fetch failed from {url} - token expired or session lost?")
            raw[key] = payload
        raw["_league"] = self._fetch_league(get)
        return raw

    def _fetch_league(self, get) -> dict:
        """Private-league standings + each member's per-round history and squad.
        Best-effort: returns {} on failure (rival squads are often hidden until
        the round locks)."""
        base = "https://vm-fantasyapi-production.up.railway.app"
        try:
            summary = get(f"{base}/leagues/summary?tournamentId=vm-2026")
            if not isinstance(summary, list):
                return {}
            leagues = []
            for lg in summary:
                if lg.get("leagueType") == "MAIN":      # skip the 60k-member global league
                    continue
                lid = lg.get("leagueId")
                lb = get(f"{base}/leagues/{lid}/leaderboard?page=1&limit=100")
                if not lb:
                    continue
                entries = lb.get("entries", [])
                # only pull each rival's full squad for small friend leagues -
                # fetching a squad-view per member of a 100-strong league is costly
                fetch_squads = len(entries) <= config.LEAGUE_SQUAD_FETCH_MAX
                members = []
                for e in entries:
                    view = get(f"{base}/squad/view/{e.get('squadId')}") if fetch_squads else {}
                    members.append({
                        "manager": e.get("managerName"), "squad_name": e.get("squadName"),
                        "squad_id": e.get("squadId"),
                        "rank": e.get("rank"), "total_points": e.get("totalPoints", 0),
                        "latest_round_points": e.get("latestRoundPoints", 0),
                        "round_scores": e.get("roundScores", []),
                        **self._parse_rival_view(view or {}),
                    })
                leagues.append({"name": lg.get("leagueName"), "league_id": lid,
                                "my_rank": (lb.get("myRank") or {}).get("rank"), "members": members})
            return {"leagues": leagues}
        except Exception as exc:  # never let league fetching break the core sync
            print(f"league fetch skipped: {exc}", file=sys.stderr)
            return {}

    @staticmethod
    def _parse_rival_view(view: dict) -> dict:
        """squad/view returns {rounds:[{number,formation,starters,bench,...}]}.
        Use the latest round for the current squad/lineup/captain, and keep a
        per-round history of formation + points."""
        if not isinstance(view, dict):
            return {"squad": [], "starter_ids": [], "bench_ids": [], "captain_id": None,
                    "formation": None, "rounds": []}
        rounds = view.get("rounds") or []
        latest = rounds[-1] if rounds else {}
        starters = latest.get("starters") or []
        bench = latest.get("bench") or []

        def pid(p):
            return str(p.get("playerId") or p.get("id") or "")

        starter_ids = [pid(p) for p in starters if pid(p)]
        bench_ids = [pid(p) for p in bench if pid(p)]
        captain = next((pid(p) for p in starters if p.get("isCaptain")), None)
        hist = [{"number": r.get("number"), "formation": r.get("formation"),
                 "points": r.get("roundTotal"), "transfer_hit": r.get("transferHit", 0)}
                for r in rounds]
        return {
            "squad": starter_ids + bench_ids,
            "starter_ids": starter_ids, "bench_ids": bench_ids,
            "captain_id": captain, "formation": latest.get("formation"),
            "rounds": hist,
        }

    # ------------------------------------------------------------ players

    @staticmethod
    def _round_points_from_scores(match_scores) -> tuple[dict[str, int], int]:
        """playerMatchScores -> ({round_number: points}, total). Tolerant of the
        exact key names since the populated shape is unseen pre-tournament."""
        by_round: dict[str, int] = {}
        if not isinstance(match_scores, list):
            return by_round, 0
        for s in match_scores:
            if not isinstance(s, dict):
                continue
            rnd = s.get("roundNumber") or s.get("round") or s.get("roundId")
            pts = s.get("points") if s.get("points") is not None else s.get("totalPoints")
            if rnd is not None and pts is not None:
                by_round[str(rnd)] = by_round.get(str(rnd), 0) + int(pts)
        return by_round, sum(by_round.values())

    def normalize_players(self, payload) -> list[dict]:
        if not isinstance(payload, list):
            raise ValueError("players payload is not a list - endpoint changed?")
        out = []
        for r in payload:
            prices = r.get("prices") or []
            price = (prices[-1]["priceCents"] / PRICE_DIVISOR) if prices else 0.0
            ownership = r.get("ownershipPercent")
            by_round, total = self._round_points_from_scores(r.get("playerMatchScores"))
            out.append({
                "id": str(r["id"]),
                "name": r.get("name"),
                "team": (r.get("team") or {}).get("name", ""),
                "position": r.get("position", ""),
                "price": round(float(price), 2),
                "ownership_pct": round(float(ownership), 3) if ownership is not None else None,
                "total_points": total,
                "round_points": by_round,
                "status": "available" if r.get("isAvailable", True) else "out",
            })
        return out

    # ------------------------------------------------------------ my team

    def normalize_my_team(self, payload, transfer_info=None) -> dict:
        picks = payload.get("players") or payload.get("picks") or payload.get("squad") or []
        squad = []
        for p in picks:
            if isinstance(p, dict):
                pid = p.get("playerId") or p.get("id") or p.get("element")
                if pid is None:
                    raise ValueError(f"squad pick without a recognizable id key: {p}")
                squad.append(str(pid))
            else:
                squad.append(str(p))  # plain id
        bank = float(payload.get("budgetRemainingCents") or 0) / PRICE_DIVISOR

        free = 2
        if transfer_info:
            if transfer_info.get("unlimitedTransfers"):
                free = config.SQUAD_SIZE  # pre-tournament: effectively unlimited
            else:
                avail = transfer_info.get("freeTransfersAvailable")
                free = max(int(avail), 0) if avail is not None and avail >= 0 else 2

        return {
            "squad": squad,
            "starting_xi": squad[:11],          # app recomputes the suggested XI/captain
            "captain_id": None,                 # TV 2 lineup/captain not exposed pre-lock
            "bank": round(bank, 2),
            "free_transfers": free,
            "squad_name": payload.get("name"),
            "round_history": {},
        }

    # ------------------------------------------------------------ fixtures

    def normalize_fixtures(self, rounds_payload) -> list[dict]:
        """Merge TV 2 live status/scores onto the openfootball schedule (which
        has venues, groups and knockout fixtures TV 2 hasn't published yet).
        Joins on (fantasy_round, unordered team pair)."""
        fallback = json.loads(
            (ROOT / "data" / "static" / "fixtures_fallback.json").read_text(encoding="utf-8")
        )["matches"]
        merged = [dict(m) for m in fallback]
        index = {}
        for m in merged:
            if m.get("fantasy_round"):
                key = (m["fantasy_round"], frozenset({
                    data_access.normalize_team(m["home"]), data_access.normalize_team(m["away"])}))
                index[key] = m

        for rnd in rounds_payload or []:
            number = rnd.get("number")
            for fx in rnd.get("fixtures", []):
                home = data_access.normalize_team((fx.get("homeTeam") or {}).get("name", ""))
                away = data_access.normalize_team((fx.get("awayTeam") or {}).get("name", ""))
                target = index.get((number, frozenset({home, away})))
                if target is None:
                    continue  # knockout placeholder or name mismatch - keep fallback row
                status = str(fx.get("status", "")).upper()
                target["status"] = "finished" if status in FINISHED_STATUSES else "scheduled"
                if fx.get("homeScore") is not None and fx.get("awayScore") is not None:
                    # orient scores to the fallback row's home/away
                    if data_access.normalize_team(target["home"]) == home:
                        target["score_home"], target["score_away"] = fx["homeScore"], fx["awayScore"]
                    else:
                        target["score_home"], target["score_away"] = fx["awayScore"], fx["homeScore"]
                if fx.get("kickoffAt"):
                    target["kickoff_utc"] = fx["kickoffAt"]
        return merged
