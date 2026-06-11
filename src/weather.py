"""Open-Meteo client: apparent temperature at a venue around kickoff.

Free, keyless, 16-day hourly horizon. Returns None for kickoffs beyond the
forecast window (callers treat None as 'no heat adjustment yet').
"""
import os
from datetime import datetime, timedelta, timezone

from src.http_fetch import fetch_json

_API = "https://api.open-meteo.com/v1/forecast"
_cache: dict[tuple, float | None] = {}


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

    key = (round(lat, 3), round(lon, 3), kickoff.strftime("%Y-%m-%dT%H"))
    if key in _cache:
        return _cache[key]

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
            times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in hourly["time"]]
            temps = hourly["apparent_temperature"]
            window = [
                temp for t, temp in zip(times, temps)
                if temp is not None and kickoff - timedelta(minutes=30) <= t <= kickoff + timedelta(hours=2)
            ]
            if window:
                result = round(sum(window) / len(window), 1)
    except (KeyError, ValueError, TypeError):
        result = None
    if result is not None:  # don't cache failures - retry on the next compute
        _cache[key] = result
    return result
