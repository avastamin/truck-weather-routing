"""Data shapes shared by the routing service and the domain logic."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float
    label: str = ""


@dataclass(frozen=True)
class Route:
    """A route as a polyline with cumulative distance and travel time at every vertex.

    coords, cum_miles and cum_seconds have the same length; cum_* start at 0 and never
    decrease. The last cum_miles / cum_seconds equal distance_miles / duration_seconds.
    """

    id: str
    coords: list[tuple[float, float]]  # (lat, lon)
    cum_miles: list[float]
    cum_seconds: list[float]

    def __post_init__(self) -> None:
        n = len(self.coords)
        if n < 2 or len(self.cum_miles) != n or len(self.cum_seconds) != n:
            raise ValueError("Route needs >= 2 vertices and matching cumulative arrays")

    @property
    def distance_miles(self) -> float:
        return self.cum_miles[-1]

    @property
    def duration_seconds(self) -> float:
        return self.cum_seconds[-1]
