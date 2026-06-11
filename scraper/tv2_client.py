"""TV 2 VM Fantasy client: replays the game's internal JSON endpoints using the
logged-in Playwright session (cookies live in playwright-profile/).

Requires scraper/endpoints.json - produced by you after running
discover_endpoints.py. The normalizers below try common fantasy-API field
names; after the first real sync, adjust FIELD_MAP to match the actual
MonkeyBytes payload (run sync.py --dry-run and inspect data/tv2/*.json).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "playwright-profile"
ENDPOINTS_FILE = Path(__file__).parent / "endpoints.json"

# candidate key names per logical field, tried in order
FIELD_MAP = {
    "id": ["id", "playerId", "player_id", "elementId"],
    "name": ["name", "fullName", "webName", "displayName", "full_name", "web_name"],
    "team": ["team", "teamName", "country", "nation", "team_name", "squad"],
    "position": ["position", "elementType", "pos", "element_type", "positionName"],
    "price": ["price", "cost", "nowCost", "now_cost", "value"],
    "ownership_pct": ["ownership", "selectedBy", "selected_by_percent", "ownershipPercentage", "pickedBy"],
    "total_points": ["totalPoints", "total_points", "points", "score"],
    "status": ["status", "availability", "chanceOfPlaying"],
}
POSITION_MAP = {
    "1": "GK", "2": "DEF", "3": "MID", "4": "FWD",
    "gk": "GK", "goalkeeper": "GK", "keeper": "GK", "målvakt": "GK", "keepere": "GK",
    "def": "DEF", "defender": "DEF", "forsvar": "DEF", "forsvarere": "DEF", "back": "DEF",
    "mid": "MID", "midfielder": "MID", "midtbane": "MID", "midtbanespillere": "MID",
    "fwd": "FWD", "forward": "FWD", "striker": "FWD", "angrep": "FWD", "angripere": "FWD", "spiss": "FWD",
}


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
            ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=True)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://vmfantasy.tv2.no/", wait_until="networkidle")  # refresh tokens
            for key, url in self.endpoints.items():
                if key.startswith("_") or url == "https://...":
                    continue
                resp = ctx.request.get(url)
                if not resp.ok:
                    raise RuntimeError(f"{key}: HTTP {resp.status} from {url} - session expired? "
                                       "Re-run discover_endpoints.py to log in again.")
                raw[key] = resp.json()
            ctx.close()
        return raw

    # ------------------------------------------------------------ normalizers

    @staticmethod
    def _get(obj: dict, field: str, default=None):
        for key in FIELD_MAP[field]:
            if key in obj:
                return obj[key]
        return default

    @staticmethod
    def _find_player_list(payload) -> list[dict]:
        """Locate the list of player dicts wherever it is nested in the payload."""
        if isinstance(payload, list) and len(payload) > 100 and isinstance(payload[0], dict):
            return payload
        if isinstance(payload, dict):
            for v in payload.values():
                found = Tv2Client._find_player_list(v)
                if found:
                    return found
        return []

    @staticmethod
    def _normalize_round_points(raw) -> dict[str, int]:
        """Accepts the three realistic shapes: {round: points} dict, list of
        per-round dicts, or a scalar (ignored - no round attribution)."""
        if isinstance(raw, dict):
            return {str(k): int(v) for k, v in raw.items() if v is not None}
        if isinstance(raw, list):
            out = {}
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                rnd = next((entry[k] for k in ("round", "event", "gameweek", "matchday")
                            if entry.get(k) is not None), None)
                pts = next((entry[k] for k in ("points", "score", "total")
                            if entry.get(k) is not None), None)
                if rnd is not None and pts is not None:
                    out[str(rnd)] = int(pts)
            return out
        return {}

    def normalize_players(self, payload) -> list[dict]:
        rows = self._find_player_list(payload)
        if not rows:
            raise ValueError("could not locate player list in payload - adjust _find_player_list / FIELD_MAP")
        out = []
        for r in rows:
            pos_raw = str(self._get(r, "position", "")).strip().lower()
            ownership = self._get(r, "ownership_pct")
            points_by_round = r.get("roundPoints") or r.get("round_points") or r.get("eventPoints") or {}
            out.append({
                "id": str(self._get(r, "id")),
                "name": self._get(r, "name"),
                "team": str(self._get(r, "team")),
                "position": POSITION_MAP.get(pos_raw, pos_raw.upper()[:3]),
                "price": float(self._get(r, "price", 0)),
                "ownership_pct": float(ownership) if ownership is not None else None,
                "total_points": int(self._get(r, "total_points", 0) or 0),
                "round_points": self._normalize_round_points(points_by_round),
                "status": str(self._get(r, "status", "available")),
            })
        return out

    def normalize_my_team(self, payload) -> dict:
        """Best-effort - inspect data/tv2/my_team.json after a --dry-run and
        adjust to the real payload shape."""
        picks = payload.get("picks") or payload.get("squad") or payload.get("players") or []
        squad = []
        for p in picks:
            if isinstance(p, dict):
                pid = p.get("id") or p.get("playerId") or p.get("element")
                if pid is None:
                    raise ValueError(f"squad pick without a recognizable id key: {p}")
                squad.append(str(pid))
            else:
                squad.append(str(p))  # plain id (int/string)
        return {
            "squad": squad,
            "starting_xi": squad[:11] if len(squad) >= 11 else squad,
            "captain_id": str(payload.get("captain") or payload.get("captainId") or ""),
            "bank": float(payload.get("bank") or payload.get("transfersBank") or 0),
            "free_transfers": int(payload.get("freeTransfers") or payload.get("free_transfers") or 2),
            "round_history": payload.get("roundHistory") or {},
        }
