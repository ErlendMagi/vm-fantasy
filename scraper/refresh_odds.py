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
        if "world_cup" not in k or "women" in k:
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
        totals = None
        for bm in bms:  # find the most common totals line
            for market in bm.get("markets", []):
                if market["key"] == "totals" and market["outcomes"]:
                    line = market["outcomes"][0].get("point", 2.5)
                    totals = {
                        "line": line,
                        "over": _best_price(bms, "totals", "Over"),
                        "under": _best_price(bms, "totals", "Under"),
                    }
                    break
            if totals:
                break
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outrights", action="store_true", help="also fetch tournament winner odds (1 credit)")
    args = parser.parse_args()

    key = _key()
    match_key, outright_key = _find_sport_keys(key)
    if not match_key:
        sys.exit("No World Cup sport key found on The Odds API - check their /sports list manually.")

    odds_dir = ROOT / "data" / "odds"
    odds_dir.mkdir(parents=True, exist_ok=True)

    data = fetch_match_odds(key, match_key)
    (odds_dir / "match_odds.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"match odds: {len(data['matches'])} matches, credits remaining: {data['credits_remaining']}")

    if args.outrights:
        if not outright_key:
            print("no outright sport key found - skipping")
        else:
            data = fetch_outrights(key, outright_key)
            (odds_dir / "outrights.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
            print(f"outrights: {len(data['prices'])} teams, credits remaining: {data['credits_remaining']}")


if __name__ == "__main__":
    main()
