"""Hourly forecasts from Open-Meteo for many points at once.

Points are snapped to a 0.1 degree grid (about 7 miles) so nearby checkpoints share one forecast,
then fetched in batches. Each grid cell's series is cached for a short time because forecasts
only update about once an hour.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from api.domain.forecast import to_inches

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
# Paid plans use their own host and an API key; free use is limited per IP address.
OPEN_METEO_CUSTOMER_URL = "https://customer-api.open-meteo.com/v1/forecast"
HOURLY_VARS = ("wind_speed_10m", "wind_gusts_10m", "rain", "showers", "snowfall")
GRID_STEP_DEG = 0.1
BATCH_SIZE = 100  # keeps the GET URL a reasonable length
MAX_PARALLEL_REQUESTS = 4
REQUEST_TIMEOUT_S = 30
CACHE_TTL_S = 30 * 60


class WeatherError(Exception):
    """The forecast couldn't be fetched or understood; the message is safe to show."""


@dataclass(frozen=True)
class HourlySeries:
    """One location's forecast. Lists line up with `times` (unix seconds, UTC, hourly).
    Values can be None where the forecast has gaps."""

    times: list[int]
    wind_mph: list[float | None]
    gust_mph: list[float | None]
    rain_in: list[float | None]  # rain + showers, inches in the preceding hour
    snow_in: list[float | None]  # inches in the preceding hour


GridKey = tuple[float, float]


def grid_key(lat: float, lon: float) -> GridKey:
    return (
        round(round(lat / GRID_STEP_DEG) * GRID_STEP_DEG, 1),
        round(round(lon / GRID_STEP_DEG) * GRID_STEP_DEG, 1),
    )


def hour_floor(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def hour_ceil(dt: datetime) -> datetime:
    floor = hour_floor(dt)
    return floor if floor == dt else floor + timedelta(hours=1)


def _sum_or_none(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a + b


def parse_location(loc: dict[str, Any]) -> HourlySeries:
    units = loc["hourly_units"]
    hourly = loc["hourly"]
    for var in ("wind_speed_10m", "wind_gusts_10m"):
        if units.get(var) != "mp/h":
            raise WeatherError(f"Unexpected wind unit from forecast: {units.get(var)!r}")

    def inches(var: str) -> list[float | None]:
        unit = units[var]
        try:
            return [None if v is None else to_inches(v, unit) for v in hourly[var]]
        except ValueError as exc:
            raise WeatherError(str(exc)) from None

    return HourlySeries(
        times=list(hourly["time"]),
        wind_mph=list(hourly["wind_speed_10m"]),
        gust_mph=list(hourly["wind_gusts_10m"]),
        rain_in=[
            _sum_or_none(r, s) for r, s in zip(inches("rain"), inches("showers"), strict=True)
        ],
        snow_in=inches("snowfall"),
    )


class OpenMeteoClient:
    def __init__(
        self, cache=None, session: requests.Session | None = None, api_key: str | None = None
    ):
        if cache is None:
            from django.core.cache import cache as django_cache

            cache = django_cache
        if api_key is None:
            from django.conf import settings

            api_key = settings.OPEN_METEO_API_KEY
        self.cache = cache
        self.session = session or requests.Session()
        self.api_key = api_key

    def hourly(
        self, points: list[tuple[float, float]], start: datetime, end: datetime
    ) -> dict[GridKey, HourlySeries]:
        """Forecast covering [start, end] for every point, keyed by `grid_key(lat, lon)`."""
        start_h, end_h = hour_floor(start), hour_ceil(end)
        keys = list(dict.fromkeys(grid_key(lat, lon) for lat, lon in points))
        cache_keys = {k: self._cache_key(k, start_h, end_h) for k in keys}

        cached = self.cache.get_many(list(cache_keys.values()))
        result = {k: cached[ck] for k, ck in cache_keys.items() if ck in cached}
        missing = [k for k in keys if k not in result]
        if missing:
            batches = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as pool:
                fetched = pool.map(lambda b: self._fetch(b, start_h, end_h), batches)
                for batch, series_list in zip(batches, fetched, strict=True):
                    result.update(zip(batch, series_list, strict=True))
            self.cache.set_many({cache_keys[k]: result[k] for k in missing}, CACHE_TTL_S)
        return result

    @staticmethod
    def _cache_key(key: GridKey, start: datetime, end: datetime) -> str:
        return f"wx:{key[0]}:{key[1]}:{int(start.timestamp())}:{int(end.timestamp())}"

    def _fetch(self, keys: list[GridKey], start: datetime, end: datetime) -> list[HourlySeries]:
        params = {
            "latitude": ",".join(f"{lat:.1f}" for lat, _ in keys),
            "longitude": ",".join(f"{lon:.1f}" for _, lon in keys),
            "hourly": ",".join(HOURLY_VARS),
            "wind_speed_unit": "mph",
            "timezone": "UTC",
            "timeformat": "unixtime",
            "start_hour": start.strftime("%Y-%m-%dT%H:%M"),
            "end_hour": end.strftime("%Y-%m-%dT%H:%M"),
        }
        url = OPEN_METEO_URL
        if self.api_key:
            url = OPEN_METEO_CUSTOMER_URL
            params["apikey"] = self.api_key
        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT_S)
        except requests.RequestException as exc:
            raise WeatherError(f"Weather service unreachable ({type(exc).__name__}).") from None
        try:
            body = resp.json()
        except ValueError:
            raise WeatherError(f"Weather service returned HTTP {resp.status_code}.") from None
        if resp.status_code != 200 or (isinstance(body, dict) and body.get("error")):
            reason = body.get("reason", "") if isinstance(body, dict) else ""
            raise WeatherError(f"Weather request failed: {reason or resp.status_code}")
        locations = body if isinstance(body, list) else [body]
        if len(locations) != len(keys):
            raise WeatherError("Weather service returned the wrong number of locations.")
        return [parse_location(loc) for loc in locations]
