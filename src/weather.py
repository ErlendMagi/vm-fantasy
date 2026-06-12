"""Open-Meteo client: apparent temperature at a venue around kickoff.

Free, keyless, 16-day hourly horizon. Returns None for kickoffs beyond the
forecast window (callers treat None as 'no heat adjustment yet').

prefetch() pulls ALL outdoor venues' hourly forecasts in ONE multi-location
request (Open-Meteo accepts comma-separated coordinates), so projecting two
full rounds costs 1 API call instead of ~48 - first page load stays fast even
if the API is slow or rate-limiting.
"""
import os
from datetime import datetime, timedelta, timezone

from src.http_fetch import fetch_json

_API = "https://api.open-meteo.com/v1/forecast"
_cache: dict[tuple, float | None] = {}
# (lat3, lon3) -> {"2026-06-12T19": temp, ...} filled by prefetch()
_hourly: dict[tuple, dict[str, float]] = {}


def _coord_key(lat: float, lon: float) -> tuple:
    return (round(lat, 3), round(lon, 3))


def prefetch(locations: list[tuple[float, float]], start_date: str, end_date: str) -> None:
    """One bulk request for many venues' hourly apparent temperature."""
    if os.environ.get("VMFANTASY_NO_WEATHER"):
        return
    todo = [(la, lo) for la, lo in dict.fromkeys(_coord_key(*p) for p in locations)
            if (la, lo) not in _hourly]
    if not todo:
        return
    payload, _ = fetch_json(_API, params={
        "latitude": ",".join(str(la) for la, _ in todo),
        "longitude": ",".join(str(lo) for _, lo in todo),
        "hourly": "apparent_temperature", "timezone": "UTC",
        "start_date": start_date, "end_date": end_date,
    }, timeout=25)
    if payload is None:
        return
    blocks = payload if isinstance(payload, list) else [payload]
    for (la, lo), block in zip(todo, blocks):
        try:
            hourly = block["hourly"]
            _hourly[(la, lo)] = {t[:13]: v for t, v in zip(hourly["time"], hourly["apparent_temperature"])
                                 if v is not None}
        except (KeyError, TypeError):
            continue


def _window_mean(series: dict[str, float], kickoff: datetime) -> float | None:
    vals = []
    for h in range(0, 3):  # kickoff hour + 2h
        t = (kickoff + timedelta(hours=h)).strftime("%Y-%m-%dT%H")
        if t in series:
            vals.append(series[t])
    return round(sum(vals) / len(vals), 1) if vals else None


def apparent_temp_at_kickoff(lat: float, lon: float, kickoff_utc: str) -> float | None:
    """Mean apparent temperature (deg C) over kickoff hour + 2h, or None if
    out of forecast range / fetch failure."""
    if os.environ.get("VMFANTASY_NO_WEATHER"):   # fast local testing (no heat adj.)
        return None
    kickoff = datetime.fromisoformat(kickoff_utc)
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if kickoff > now + timedelta(days=15) or kickoff < now - timedelta(days=2):
        return None

    ckey = _coord_key(lat, lon)
    key = (*ckey, kickoff.strftime("%Y-%m-%dT%H"))
    if key in _cache:
        return _cache[key]
    if ckey in _hourly:                       # served from the bulk prefetch
        result = _window_mean(_hourly[ckey], kickoff)
        if result is not None:
            _cache[key] = result
        return result

    day = kickoff.date().isoformat()
    end_day = (kickoff + timedelta(hours=3)).date().isoformat()
    payload, _ = fetch_json(_API, params={
        "latitude": lat, "longitude": lon,
        "hourly": "apparent_temperature",
        "timezone": "UTC",
        "start_date": day, "end_date": end_day,
    }, timeout=15)
    result = None
    try:
        if payload:
            hourly = payload["hourly"]
            series = {t[:13]: v for t, v in zip(hourly["time"], hourly["apparent_temperature"])
                      if v is not None}
            result = _window_mean(series, kickoff)
    except (KeyError, ValueError, TypeError):
        result = None
    if result is not None:  # don't cache failures - retry on the next compute
        _cache[key] = result
    return result
