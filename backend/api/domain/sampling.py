"""Checkpoints along a route and the ETA at each one.

Checkpoints go at mile 0, N, 2N, ... plus the destination. Each one covers half the gap to each
neighbour, so the covered miles add up to the route length.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta

from api.domain.types import Route

ALLOWED_INTERVALS_MILES = (10, 25, 50)
DEFAULT_INTERVAL_MILES = 25

# A gap to the destination smaller than this (~5 ft) is float noise, not a real checkpoint.
_END_TOLERANCE_MILES = 1e-3


@dataclass(frozen=True)
class Checkpoint:
    mile: float
    lat: float
    lon: float
    eta: datetime
    covers_miles: float


def checkpoint_miles(total_miles: float, interval_miles: float) -> list[float]:
    if interval_miles not in ALLOWED_INTERVALS_MILES:
        raise ValueError(f"interval must be one of {ALLOWED_INTERVALS_MILES} miles")
    if total_miles <= 0:
        raise ValueError("route length must be positive")
    miles: list[float] = []
    k = 0
    while k * interval_miles < total_miles - _END_TOLERANCE_MILES:
        miles.append(float(k * interval_miles))
        k += 1
    miles.append(total_miles)
    return miles


def coverage_miles(miles: list[float]) -> list[float]:
    """Miles each checkpoint represents: half the gap to each neighbour."""
    if len(miles) < 2:
        raise ValueError("need at least 2 checkpoints")
    gaps = [b - a for a, b in zip(miles, miles[1:])]
    return [
        (gaps[i - 1] if i > 0 else 0.0) / 2 + (gaps[i] if i < len(gaps) else 0.0) / 2
        for i in range(len(miles))
    ]


def point_at_mile(route: Route, mile: float) -> tuple[float, float, float]:
    """(lat, lon, seconds since departure) at a distance along the route, interpolated linearly
    between the surrounding vertices."""
    cum = route.cum_miles
    if mile < 0 or mile > cum[-1] + _END_TOLERANCE_MILES:
        raise ValueError(f"mile {mile} is outside the route (0..{cum[-1]})")
    mile = min(mile, cum[-1])
    i = min(max(bisect_right(cum, mile) - 1, 0), len(cum) - 2)
    span = cum[i + 1] - cum[i]
    frac = (mile - cum[i]) / span if span > 0 else 0.0
    (lat0, lon0), (lat1, lon1) = route.coords[i], route.coords[i + 1]
    s0, s1 = route.cum_seconds[i], route.cum_seconds[i + 1]
    return lat0 + (lat1 - lat0) * frac, lon0 + (lon1 - lon0) * frac, s0 + (s1 - s0) * frac


def sample_route(route: Route, interval_miles: float, departure: datetime) -> list[Checkpoint]:
    if departure.tzinfo is None:
        raise ValueError("departure must be timezone-aware")
    miles = checkpoint_miles(route.distance_miles, interval_miles)
    checkpoints = []
    for mile, covers in zip(miles, coverage_miles(miles)):
        lat, lon, seconds = point_at_mile(route, mile)
        checkpoints.append(
            Checkpoint(
                mile=mile,
                lat=lat,
                lon=lon,
                eta=departure + timedelta(seconds=seconds),
                covers_miles=covers,
            )
        )
    return checkpoints
