"""TV 2 VM Fantasy client: replays the game's internal JSON endpoints using the
logged-in Playwright session (cookies live in playwright-profile/).

Backend discovered 2026-06-11: vm-fantasyapi-production.up.railway.app, a plain
REST API. Endpoints in scraper/endpoints.json. The parsers below target that
API's real payload shapes; price is in cents (priceCents / 1e6 = game M unit),
positions already come as GK/DEF/MID/FWD, ownership as a percentage.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "playwright-profile"
ENDPOINTS_FILE = Path(__file__).parent / "endpoints.json"
sys.path.insert(0, str(ROOT))
from src import config, data_access  # noqa: E402

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
        """GET every configured endpoint through the logged-in browser context."""
        from playwright.sync_api import sync_playwright  # lazy: scraper-only dep

        raw = {}
        with sync_playwright() as p:
            # ignore_https_errors: some local security software (e.g. Avast)
            # MITMs TLS with a cert Node's CA bundle doesn't trust; the browser
            # trusts it but APIRequestContext otherwise rejects it.
            ctx = p.chromium.launch_persistent_context(
                str(PROFILE), headless=True, ignore_https_errors=True)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            # the API authenticates with a Bearer token (not a cookie); capture
            # the Authorization header the app itself sends, then replay it
            captured: dict[str, str] = {}

            def grab_auth(req):
                auth = req.headers.get("authorization")
                if auth and "railway.app" in req.url:
                    captured["auth"] = auth

            page.on("request", grab_auth)
            page.goto("https://vmfantasy.tv2.no/", wait_until="networkidle")
            if "auth" not in captured:  # nudge the app into an authed call
                token = page.evaluate(
                    "() => { for (const k in localStorage) { const v = localStorage[k];"
                    " if (v && v.length > 40 && v.split('.').length === 3) return v; } return null; }")
                if token:
                    captured["auth"] = f"Bearer {token}"

            auth_headers = {"Authorization": captured["auth"]} if "auth" in captured else {}
            for key, url in self.endpoints.items():
                if key.startswith("_") or url == "https://...":
                    continue
                resp = ctx.request.get(url, headers=auth_headers)
                if not resp.ok:
                    raise RuntimeError(f"{key}: HTTP {resp.status} from {url} - session expired? "
                                       "Re-run discover_endpoints.py to log in again.")
                raw[key] = resp.json()
            ctx.close()
        return raw

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
