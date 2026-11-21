"""Builds a trip plan: routes, checkpoints with weather at each ETA, risk and a recommendation.

The routing provider and weather client are passed in, so the whole flow can be tested with
fakes and no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from api.domain.forecast import ForecastRangeError, interpolate_at
from api.domain.geo import haversine_miles, simplify
from api.domain.hours_of_service import add_rest_stops
from api.domain.recommend import RouteRisk, aggregate, recommend
from api.domain.risk import Assessment, RiskLevel, assess
from api.domain.sampling import Checkpoint, sample_route
from api.domain.types import GeoPoint, Route
from api.services.routing import RoutingProvider, get_routes
from api.services.weather import HourlySeries, OpenMeteoClient, grid_key, hour_ceil

DEPARTURE_GRACE = timedelta(minutes=15)  # allow for clock drift between browser and server
MAX_DAYS_AHEAD = 7
FORECAST_DAYS = 16  # Open-Meteo serves today plus 15 days, starting 00:00 UTC today
PATH_TOLERANCE_DEG = 1e-4  # ~10 m; simplification is invisible at any useful zoom
MIN_TRIP_MILES = 1.0


class PlanError(Exception):
    """A problem with the user's request; the message is shown to the user as is."""


@dataclass(frozen=True)
class PlanRequest:
    origin: str
    destination: str
    departure: datetime
    load_lb: float
    interval_miles: int


def forecast_end(now: datetime) -> datetime:
    """Last forecast hour Open-Meteo will serve."""
    today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return today + timedelta(days=FORECAST_DAYS) - timedelta(hours=1)


def check_departure(departure: datetime, now: datetime) -> None:
    if departure.tzinfo is None:
        raise PlanError("Departure time must include a timezone.")
    if departure < now - DEPARTURE_GRACE:
        raise PlanError("Departure time is in the past.")
    if departure > now + timedelta(days=MAX_DAYS_AHEAD):
        raise PlanError(f"Departure must be within the next {MAX_DAYS_AHEAD} days.")


def build_plan(
    req: PlanRequest, provider: RoutingProvider, weather: OpenMeteoClient, now: datetime
) -> dict[str, Any]:
    check_departure(req.departure, now)
    origin = provider.geocode(req.origin)
    destination = provider.geocode(req.destination)
    straight_line = haversine_miles((origin.lat, origin.lon), (destination.lat, destination.lon))
    if straight_line < MIN_TRIP_MILES:
        raise PlanError("Origin and destination are the same place.")

    routes = get_routes(provider, origin, destination, req.departure, req.load_lb)
    # Breaks and rests change when the truck reaches each checkpoint, and so the weather it meets.
    routes = [add_rest_stops(r) for r in routes]
    latest_arrival = req.departure + timedelta(seconds=max(r.duration_seconds for r in routes))
    if hour_ceil(latest_arrival) > forecast_end(now):
        raise PlanError(
            "The trip would end after the last available forecast hour "
            f"({forecast_end(now):%a %d %b %H:%M} UTC). Choose an earlier departure."
        )

    checkpoints = {r.id: sample_route(r, req.interval_miles, req.departure) for r in routes}
    points = [(cp.lat, cp.lon) for cps in checkpoints.values() for cp in cps]
    forecasts = weather.hourly(points, req.departure, latest_arrival)

    route_payloads, risks = [], []
    for route in routes:
        rows = []
        for cp in checkpoints[route.id]:
            values = _weather_at(forecasts[grid_key(cp.lat, cp.lon)], cp.eta)
            assessment = assess(
                wind_mph=values["wind_mph"],
                rain_in_hr=values["rain_in_hr"],
                snow_in_hr=values["snow_in_hr"],
                load_lb=req.load_lb,
            )
            rows.append((cp, values, assessment))
        segments = [(a.level, cp.covers_miles) for cp, _, a in rows]
        risk = aggregate(route.id, segments, route.duration_seconds)
        risks.append(risk)
        route_payloads.append(_route_payload(route, risk, rows, req.departure))

    rec = recommend(risks)
    rank = {route_id: i + 1 for i, route_id in enumerate(rec.ranking)}
    for payload in route_payloads:
        payload["rank"] = rank[payload["id"]]
    return {
        "origin": _point_payload(origin),
        "destination": _point_payload(destination),
        "departure": req.departure.isoformat(),
        "load_lb": req.load_lb,
        "interval_miles": req.interval_miles,
        "recommended_route_id": rec.route_id,
        "reason": rec.reason,
        "no_travel_warning": rec.no_travel_warning,
        "routes": route_payloads,
    }


def _weather_at(series: HourlySeries, eta: datetime) -> dict[str, float | None]:
    t = eta.timestamp()
    try:
        values: dict[str, float | None] = {
            "wind_mph": interpolate_at(series.times, series.wind_mph, t),
            "rain_in_hr": interpolate_at(series.times, series.rain_in, t),
            "snow_in_hr": interpolate_at(series.times, series.snow_in, t),
        }
    except ForecastRangeError:
        raise PlanError("Forecast data is missing for part of this trip.") from None
    try:
        values["gust_mph"] = interpolate_at(series.times, series.gust_mph, t)
    except ForecastRangeError:
        values["gust_mph"] = None  # gusts are only displayed, so a gap isn't fatal
    return values


def _point_payload(p: GeoPoint) -> dict[str, Any]:
    return {"lat": round(p.lat, 5), "lon": round(p.lon, 5), "label": p.label}


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _route_payload(
    route: Route,
    risk: RouteRisk,
    rows: list[tuple[Checkpoint, dict[str, float | None], Assessment]],
    departure: datetime,
) -> dict[str, Any]:
    path = simplify(route.coords, PATH_TOLERANCE_DEG)
    return {
        "id": route.id,
        "distance_miles": round(route.distance_miles, 1),
        "duration_seconds": round(route.duration_seconds),
        "driving_seconds": round(route.driving_seconds),
        "arrival": (departure + timedelta(seconds=route.duration_seconds)).isoformat(),
        "rest_stops": [
            {
                "kind": stop.kind,
                "mile": round(stop.mile, 1),
                "lat": round(stop.lat, 5),
                "lon": round(stop.lon, 5),
                "arrive": (departure + timedelta(seconds=stop.arrive_seconds)).isoformat(),
                "leave": (
                    departure + timedelta(seconds=stop.arrive_seconds + stop.duration_seconds)
                ).isoformat(),
                "duration_seconds": round(stop.duration_seconds),
            }
            for stop in route.rest_stops
        ],
        "miles_by_level": {_level_key(lvl): round(m, 1) for lvl, m in risk.miles_by_level.items()},
        "avg_risk": round(risk.avg_risk, 2),
        "has_no_travel": risk.has_no_travel,
        # [lon, lat] order, as map libraries expect
        "path": [[round(lon, 5), round(lat, 5)] for lat, lon in path],
        "checkpoints": [
            {
                "mile": round(cp.mile, 1),
                "lat": round(cp.lat, 5),
                "lon": round(cp.lon, 5),
                "eta": cp.eta.isoformat(),
                "covers_miles": round(cp.covers_miles, 2),
                "wind_mph": _round(values["wind_mph"], 1),
                "gust_mph": _round(values["gust_mph"], 1),
                "rain_in_hr": _round(values["rain_in_hr"], 3),
                "snow_in_hr": _round(values["snow_in_hr"], 3),
                "level": _level_key(a.level),
                "triggered_by": list(a.triggered_by),
                "reasons": list(a.reasons),
            }
            for cp, values, a in rows
        ],
    }


def _level_key(level: RiskLevel) -> str:
    return level.name.lower()
