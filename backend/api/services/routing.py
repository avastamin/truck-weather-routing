"""Routing provider adapter.

Every provider returns the common `Route` shape (see api/domain/types.py), so the rest of the
app never touches provider-specific JSON. To add Mapbox, implement `RoutingProvider` and register
it in `get_routing_provider`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

import flexpolyline
import requests

from api.domain.geo import METERS_PER_MILE, haversine_miles
from api.domain.types import GeoPoint, Route

LB_TO_KG = 0.45359237
REQUEST_TIMEOUT_S = 20
MAX_ROUTES = 3


class RoutingError(Exception):
    """A routing or geocoding failure with a message that is safe to show the user."""


class RoutingProvider(Protocol):
    def geocode(self, query: str) -> GeoPoint: ...

    def routes(
        self, origin: GeoPoint, destination: GeoPoint, departure: datetime, load_lb: float
    ) -> list[Route]: ...


def get_routing_provider() -> RoutingProvider:
    from django.conf import settings

    if settings.ROUTING_PROVIDER == "here":
        if not settings.HERE_API_KEY:
            raise RoutingError("Routing is not configured (HERE_API_KEY is missing).")
        return HereRoutingProvider(settings.HERE_API_KEY)
    raise RoutingError(f"Unknown routing provider: {settings.ROUTING_PROVIDER}")


# --------------------------------------------------------------------------------------------
# HERE Routing v8 + Geocoding & Search v7
# --------------------------------------------------------------------------------------------

HERE_ROUTES_URL = "https://router.hereapi.com/v8/routes"
HERE_GEOCODE_URL = "https://geocode.search.hereapi.com/v1/geocode"


class HereRoutingProvider:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()

    def geocode(self, query: str) -> GeoPoint:
        payload = self._get(
            HERE_GEOCODE_URL, {"q": query, "in": "countryCode:USA", "limit": 1}, "Geocoding"
        )
        items = payload.get("items") or []
        if not items:
            raise RoutingError(f"Could not find a US location for '{query}'.")
        pos = items[0]["position"]
        return GeoPoint(lat=pos["lat"], lon=pos["lng"], label=items[0].get("title", query))

    def fetch_routes_raw(
        self, origin: GeoPoint, destination: GeoPoint, departure: datetime, load_lb: float
    ) -> dict:
        if departure.tzinfo is None:
            raise ValueError("departure must be timezone-aware")
        params = {
            "transportMode": "truck",
            "origin": f"{origin.lat},{origin.lon}",
            "destination": f"{destination.lat},{destination.lon}",
            "departureTime": departure.isoformat(timespec="seconds"),
            "alternatives": MAX_ROUTES - 1,
            "return": "polyline,summary",
            "spans": "length,duration",
            "vehicle[grossWeight]": round(load_lb * LB_TO_KG),
        }
        return self._get(HERE_ROUTES_URL, params, "Routing")

    def routes(
        self, origin: GeoPoint, destination: GeoPoint, departure: datetime, load_lb: float
    ) -> list[Route]:
        routes = parse_here_routes(self.fetch_routes_raw(origin, destination, departure, load_lb))
        if not routes:
            raise RoutingError("No truck route found between these locations.")
        return routes[:MAX_ROUTES]

    def _get(self, url: str, params: dict, what: str) -> dict:
        try:
            resp = self.session.get(
                url, params={**params, "apiKey": self.api_key}, timeout=REQUEST_TIMEOUT_S
            )
        except requests.RequestException as exc:
            # Don't include the URL: it contains the API key.
            raise RoutingError(f"{what} service unreachable ({type(exc).__name__}).") from None
        if resp.status_code != 200:
            try:
                body = resp.json()
                detail = body.get("title") or body.get("cause") or ""
            except ValueError:
                detail = ""
            raise RoutingError(f"{what} failed (HTTP {resp.status_code}) {detail}".strip())
        return resp.json()


def parse_here_routes(payload: dict) -> list[Route]:
    """Convert a HERE v8 /routes response into Route objects (sections concatenated)."""
    routes: list[Route] = []
    for index, raw in enumerate(payload.get("routes") or []):
        coords: list[tuple[float, float]] = []
        cum_m: list[float] = []
        cum_s: list[float] = []
        for section in raw["sections"]:
            points = [(p[0], p[1]) for p in flexpolyline.decode(section["polyline"])]
            summary = section["summary"]
            sec_m, sec_s = build_cumulative(
                points, section.get("spans") or [], summary["length"], summary["duration"]
            )
            base_m = cum_m[-1] if cum_m else 0.0
            base_s = cum_s[-1] if cum_s else 0.0
            # Consecutive sections share their boundary point; don't duplicate it.
            start = 1 if coords else 0
            coords.extend(points[start:])
            cum_m.extend(base_m + m for m in sec_m[start:])
            cum_s.extend(base_s + s for s in sec_s[start:])
        routes.append(
            Route(
                id=chr(ord("A") + index),
                coords=coords,
                cum_miles=[m / METERS_PER_MILE for m in cum_m],
                cum_seconds=cum_s,
            )
        )
    return routes


def build_cumulative(
    points: list[tuple[float, float]],
    spans: list[dict],
    total_m: float,
    total_s: float,
) -> tuple[list[float], list[float]]:
    """Cumulative meters and seconds at each polyline vertex.

    HERE spans give length/duration for runs of vertices (span i covers vertices
    offset_i..offset_{i+1}). Within a span, length and duration are split across edges in
    proportion to their straight-line length. Without usable spans, the section totals are
    split the same way over the whole polyline.
    """
    n = len(points)
    if n < 2:
        raise ValueError("polyline needs at least 2 points")
    usable = spans and spans[0].get("offset") == 0 and all(
        "length" in sp and "duration" in sp for sp in spans
    )
    if not usable:
        spans = [{"offset": 0, "length": total_m, "duration": total_s}]

    edge = [haversine_miles(points[i], points[i + 1]) for i in range(n - 1)]
    cum_m = [0.0] * n
    cum_s = [0.0] * n
    for k, span in enumerate(spans):
        start = span["offset"]
        end = spans[k + 1]["offset"] if k + 1 < len(spans) else n - 1
        if end <= start:
            continue
        span_edges = edge[start:end]
        geo_total = sum(span_edges)
        for j, e in enumerate(span_edges):
            frac = e / geo_total if geo_total > 0 else 1 / len(span_edges)
            i = start + j
            cum_m[i + 1] = cum_m[i] + span["length"] * frac
            cum_s[i + 1] = cum_s[i] + span["duration"] * frac
    return cum_m, cum_s
