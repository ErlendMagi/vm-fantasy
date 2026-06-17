"""Fetch World Cup odds from The Odds API into data/odds/*.json.

Free tier: 500 credits/month. One h2h+totals call for ALL matches = 2 credits;
outrights = 1 credit. Daily sync ≈ 80 credits/tournament. The Streamlit app
never calls this API - only this script does, locally.

Setup: put ODDS_API_KEY=... in a .env file at the repo root
(free key from https://the-odds-api.com).

Usage:
    python scraper/refresh_odds.py              # match odds (2 credits)
    python scraper/refresh_odds.py --outrights  # also tournament winner (1 credit)
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import data_access  # noqa: E402
from src.http_fetch import fetch_json  # noqa: E402

API = "https://api.the-odds-api.com/v4"


def _remaining(headers: dict) -> str | None:
    return next((v for k, v in headers.items() if k.lower() == "x-requests-remaining"), None)


def _key() -> str:
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        sys.exit("ODDS_API_KEY not set - create .env with ODDS_API_KEY=... (see README)")
    return key


def _find_sport_keys(key: str) -> tuple[str | None, str | None]:
    """Locate the World Cup sport keys (match + winner-outright)."""
    sports, _ = fetch_json(f"{API}/sports", params={"apiKey": key, "all": "true"}, timeout=20)
    if sports is None:
        sys.exit("could not reach The Odds API (network/TLS) - check connectivity and key")
    match_key = outright_key = None
    for s in sports:
        k = s["key"]
        # strictly the men's FIFA World Cup - not cricket/rugby world cups,
        # the Club World Cup, qualifiers or youth tournaments
        if not k.startswith("soccer_fifa_world_cup"):
            continue
        if any(bad in k for bad in ("women", "club", "qualifier", "u20", "u17")):
            continue
        if s.get("has_outrights") or k.endswith("_winner"):
            outright_key = outright_key or k
        else:
            match_key = match_key or k
    return match_key, outright_key


def _best_price(bookmakers: list, market_key: str, outcome_name: str) -> float | None:
    """Median price across bookmakers for an outcome (median resists outliers)."""
    prices = []
    for bm in bookmakers:
        for market in bm.get("markets", []):
            if market["key"] != market_key:
                continue
            for o in market["outcomes"]:
                if o["name"] == outcome_name:
                    prices.append(o["price"])
    if not prices:
        return None
    prices.sort()
    return prices[len(prices) // 2]


def _totals_consensus(bookmakers: list) -> dict | None:
    """Modal totals line across bookmakers, with over/under medians taken ONLY
    from bookmakers quoting that line (mixing prices across different lines
    would corrupt the odds->xG fit)."""
    quotes = []  # one (point, over, under) per bookmaker
    for bm in bookmakers:
        for market in bm.get("markets", []):
            if market["key"] != "totals":
                continue
            point = over = under = None
            for o in market["outcomes"]:
                if o["name"] == "Over":
                    over, point = o.get("price"), o.get("point", point)
                elif o["name"] == "Under":
                    under, point = o.get("price"), o.get("point", point)
            if point is not None and over and under:
                quotes.append((point, over, under))
            break  # first totals market per bookmaker
    if not quotes:
        return None
    line = Counter(q[0] for q in quotes).most_common(1)[0][0]
    overs = sorted(q[1] for q in quotes if q[0] == line)
    unders = sorted(q[2] for q in quotes if q[0] == line)
    return {"line": line, "over": overs[len(overs) // 2], "under": unders[len(unders) // 2]}


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[len(xs) // 2]


def _credits_remaining(key: str) -> int | None:
    """Cheap credit-balance check (the /sports list is free)."""
    _, headers = fetch_json(f"{API}/sports", params={"apiKey": key}, timeout=15)
    rem = _remaining(headers)
    return int(rem) if rem is not None and str(rem).isdigit() else None


def fetch_player_props(key: str, sport_key: str, days: int = 3) -> dict:
    """Anytime-goalscorer (+assist) odds per player for matches kicking off
    within `days`. Stops before dipping under the credit floor - so the core
    sync can never be starved by props. 1 region keeps it ~1-2 credits/match."""
    from src import config

    events, _ = fetch_json(f"{API}/sports/{sport_key}/events", params={"apiKey": key}, timeout=20)
    if not events:
        return {"players": [], "note": "no events"}
    now = datetime.now(timezone.utc)
    upcoming = [e for e in events
                if 0 <= (datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) - now).days <= days]

    players, fetched, skipped_low = [], 0, False
    for e in upcoming:
        remaining = _credits_remaining(key)
        if remaining is not None and remaining <= config.ODDS_CREDIT_FLOOR:
            skipped_low = True
            break
        od, _ = fetch_json(f"{API}/sports/{sport_key}/events/{e['id']}/odds", params={
            "apiKey": key, "regions": "eu", "markets": config.PLAYER_PROPS_MARKETS,
            "oddsFormat": "decimal",
        }, timeout=30)
        if not od:
            continue
        fetched += 1
        home = data_access.normalize_team(e["home_team"])
        away = data_access.normalize_team(e["away_team"])
        goal_q: dict[str, list[float]] = {}
        assist_q: dict[str, list[float]] = {}
        for bm in od.get("bookmakers", []):
            for m in bm.get("markets", []):
                bucket = goal_q if m["key"] == "player_goal_scorer_anytime" else (
                    assist_q if m["key"] == "player_assists" else None)
                if bucket is None:
                    continue
                for o in m.get("outcomes", []):
                    if o.get("name") in ("Yes", "Over") and o.get("description") and o.get("price"):
                        bucket.setdefault(o["description"], []).append(o["price"])
        names = set(goal_q) | set(assist_q)
        for name in names:
            players.append({
                "name": name, "home": home, "away": away,
                "anytime_goal": round(_median(goal_q[name]), 2) if name in goal_q else None,
                "assist": round(_median(assist_q[name]), 2) if name in assist_q else None,
            })
    return {
        "fetched_at": now.isoformat(),
        "credits_remaining": _credits_remaining(key),
        "matches_covered": fetched,
        "stopped_at_credit_floor": skipped_low,
        "players": players,
    }


def fetch_match_odds(key: str, sport_key: str) -> dict:
    events, headers = fetch_json(f"{API}/sports/{sport_key}/odds", params={
        "apiKey": key, "regions": "eu", "markets": "h2h,totals", "oddsFormat": "decimal",
    }, timeout=30)
    if events is None:
        sys.exit("match odds fetch failed (network/TLS or out of credits)")
    remaining = _remaining(headers)
    matches = []
    for ev in events:
        home = data_access.normalize_team(ev["home_team"])
        away = data_access.normalize_team(ev["away_team"])
        bms = ev.get("bookmakers", [])
        h2h = {
            "home": _best_price(bms, "h2h", ev["home_team"]),
            "draw": _best_price(bms, "h2h", "Draw"),
            "away": _best_price(bms, "h2h", ev["away_team"]),
        }
        totals = _totals_consensus(bms)
        if all(h2h.values()):
            matches.append({"home": home, "away": away,
                            "kickoff_utc": ev["commence_time"], "h2h": h2h, "totals": totals})
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "credits_remaining": remaining,
        "sport_key": sport_key,
        "matches": matches,
    }


def fetch_outrights(key: str, sport_key: str) -> dict:
    events, headers = fetch_json(f"{API}/sports/{sport_key}/odds", params={
        "apiKey": key, "regions": "eu", "markets": "outrights", "oddsFormat": "decimal",
    }, timeout=30)
    if events is None:
        sys.exit("outrights fetch failed (network/TLS or out of credits)")
    prices = {}
    for ev in events:
        for bm in ev.get("bookmakers", []):
            for market in bm.get("markets", []):
                for o in market.get("outcomes", []):
                    team = data_access.normalize_team(o["name"])
                    prices.setdefault(team, []).append(o["price"])
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "credits_remaining": _remaining(headers),
        "sport_key": sport_key,
        "prices": {t: sorted(ps)[len(ps) // 2] for t, ps in prices.items()},
    }


def _fresh(path: Path, max_age_hours: float) -> bool:
    """Throttle by the snapshot's OWN fetched_at, not the file mtime — in CI the repo
    is checked out fresh every run, so mtime is always 'now' and an mtime check would
    make the scheduled sync skip the refresh forever (odds only ever refreshed when the
    autopilot forced it near a deadline). fetched_at is the true age and survives checkout."""
    if not path.exists():
        return False
    try:
        ts = json.loads(path.read_text(encoding="utf-8")).get("fetched_at")
        if not ts:
            return False
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 3600
        return age < max_age_hours
    except (ValueError, OSError, json.JSONDecodeError):
        return False


def main() -> None:
    from src import config

    parser = argparse.ArgumentParser()
    parser.add_argument("--outrights", action="store_true", help="also fetch tournament winner odds (1 credit)")
    parser.add_argument("--props", action="store_true", help="also fetch player goalscorer/assist props")
    parser.add_argument("--props-min-age", type=float, default=None,
                        help="skip props if player_odds.json is younger than this many hours "
                             "(default: config.PROPS_REFRESH_HOURS — weekly, to protect the credit budget)")
    parser.add_argument("--force", action="store_true",
                        help="ignore freshness throttles (used right before transfer decisions); "
                             "the credit floor still applies")
    args = parser.parse_args()
    if args.props_min_age is None:
        args.props_min_age = config.PROPS_REFRESH_HOURS
    if args.force:
        args.props_min_age = 0.0

    key = _key()
    balance = _credits_remaining(key)
    if balance is not None and balance <= config.ODDS_CREDIT_FLOOR:
        print(f"odds credits low ({balance} <= floor {config.ODDS_CREDIT_FLOOR}) - "
              "keeping existing odds, fetching nothing this run")
        return

    match_key, outright_key = _find_sport_keys(key)
    if not match_key:
        sys.exit("No World Cup sport key found on The Odds API - check their /sports list manually.")

    odds_dir = ROOT / "data" / "odds"
    odds_dir.mkdir(parents=True, exist_ok=True)

    # throttle so the frequent sync doesn't burn the monthly budget: refresh match
    # odds ~2x/week (the autopilot bypasses this with --force right before each deadline)
    if not args.force and _fresh(odds_dir / "match_odds.json", config.ODDS_REFRESH_HOURS):
        print(f"match odds still fresh (<{config.ODDS_REFRESH_HOURS}h) - skipping")
    else:
        data = fetch_match_odds(key, match_key)
        if not data["matches"]:
            sys.exit(f"0 usable matches from '{match_key}' - refusing to overwrite the existing snapshot")
        (odds_dir / "match_odds.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        print(f"match odds: {len(data['matches'])} matches, credits remaining: {data['credits_remaining']}")

    if args.outrights and outright_key and (args.force or not _fresh(odds_dir / "outrights.json", 48.0)):
        data = fetch_outrights(key, outright_key)
        if data["prices"]:
            (odds_dir / "outrights.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
            print(f"outrights: {len(data['prices'])} teams, credits remaining: {data['credits_remaining']}")

    if args.props:
        if _fresh(odds_dir / "player_odds.json", args.props_min_age):
            print(f"player props still fresh (<{args.props_min_age}h) - skipping to save credits")
        else:
            props = fetch_player_props(key, match_key)
            if props["players"]:
                (odds_dir / "player_odds.json").write_text(json.dumps(props, indent=1, ensure_ascii=False),
                                                           encoding="utf-8")
                note = " (stopped at credit floor)" if props["stopped_at_credit_floor"] else ""
                print(f"player props: {len(props['players'])} player-quotes over "
                      f"{props['matches_covered']} matches, credits left {props['credits_remaining']}{note}")
            else:
                print("player props: none available - keeping any existing file")


if __name__ == "__main__":
    main()
