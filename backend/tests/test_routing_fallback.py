"""Topping up to 3 routes with via points when the provider returns fewer."""

from datetime import UTC, datetime

from api.domain.types import GeoPoint, Route
from api.services.routing import NoRouteError, get_routes

ORIGIN = GeoPoint(32.78, -96.80, "Dallas")
DEST = GeoPoint(39.74, -104.99, "Denver")
DEPART = datetime(2026, 11, 22, 8, tzinfo=UTC)


def make_route(miles, hours, bend=0.0, route_id="X"):
    """Route from ORIGIN to DEST through a midpoint shifted `bend` degrees of longitude."""
    mid = ((ORIGIN.lat + DEST.lat) / 2, (ORIGIN.lon + DEST.lon) / 2 + bend)
    return Route(
        id=route_id,
        coords=[(ORIGIN.lat, ORIGIN.lon), mid, (DEST.lat, DEST.lon)],
        cum_miles=[0, miles / 2, miles],
        cum_seconds=[0, hours * 1800, hours * 3600],
    )


class FakeProvider:
    """Returns `base` for the plain request and the next item of `via_results` per via call."""

    def __init__(self, base, via_results):
        self.base = base
        self.via_results = list(via_results)
        self.via_calls = []

    def geocode(self, query):
        raise NotImplementedError

    def routes(self, origin, destination, departure, load_lb, via=None):
        if via is None:
            return self.base
        self.via_calls.append(via)
        result = self.via_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return [result]


def test_three_routes_from_provider_need_no_via_calls():
    provider = FakeProvider(
        [make_route(800, 12), make_route(820, 12.5, bend=1), make_route(850, 13, bend=-1)], []
    )
    routes = get_routes(provider, ORIGIN, DEST, DEPART, 30_000)
    assert [r.id for r in routes] == ["A", "B", "C"]
    assert provider.via_calls == []


def test_extra_alternatives_are_trimmed_to_three():
    base = [make_route(800 + i, 12, bend=i) for i in range(5)]
    routes = get_routes(FakeProvider(base, []), ORIGIN, DEST, DEPART, 30_000)
    assert len(routes) == 3


def test_one_route_is_topped_up_with_distinct_via_routes():
    provider = FakeProvider(
        [make_route(800, 12)], [make_route(870, 13, bend=1), make_route(910, 14, bend=-1)]
    )
    routes = get_routes(provider, ORIGIN, DEST, DEPART, 30_000)
    assert [r.id for r in routes] == ["A", "B", "C"]
    assert [r.distance_miles for r in routes] == [800, 870, 910]
    assert len(provider.via_calls) == 2


def test_via_route_on_the_same_road_is_skipped():
    # Same geometry as route A but longer, like a detour to the via point and back: not a real
    # alternative even though its distance and time differ.
    provider = FakeProvider(
        [make_route(800, 12)],
        [make_route(860, 13), make_route(870, 13, bend=1), make_route(910, 14, bend=-1)],
    )
    routes = get_routes(provider, ORIGIN, DEST, DEPART, 30_000)
    assert [r.distance_miles for r in routes] == [800, 870, 910]


def test_failed_via_requests_are_tolerated():
    provider = FakeProvider(
        [make_route(800, 12)],
        [NoRouteError("x"), make_route(870, 13, bend=1), NoRouteError("x"), NoRouteError("x")],
    )
    routes = get_routes(provider, ORIGIN, DEST, DEPART, 30_000)
    assert [r.distance_miles for r in routes] == [800, 870]


def test_via_points_alternate_sides():
    provider = FakeProvider([make_route(800, 12)], [make_route(800, 12)] * 4)
    get_routes(provider, ORIGIN, DEST, DEPART, 30_000)
    first, second = provider.via_calls[:2]
    # Dallas -> Denver heads north-west; left and right offsets land on opposite sides.
    assert (first.lat - second.lat) * (first.lon - second.lon) > 0
    assert first.lat != second.lat
