"""HERE response parsing, using synthetic payloads (no network, no API key)."""

import flexpolyline
import pytest

from api.domain.geo import METERS_PER_MILE
from api.services.routing import (
    HereRoutingProvider,
    LocationNotFoundError,
    build_cumulative,
    parse_here_routes,
)

# Four points due north along a meridian, roughly equal spacing.
POINTS = [(32.0, -97.0), (32.1, -97.0), (32.2, -97.0), (32.3, -97.0)]


def section(points, length_m, duration_s, spans=None):
    sec = {
        "polyline": flexpolyline.encode(points),
        "summary": {"length": length_m, "duration": duration_s},
    }
    if spans is not None:
        sec["spans"] = spans
    return sec


def test_spans_drive_cumulative_duration():
    # First span (edges 0-1) is slow, second span (edge 2) is fast.
    spans = [
        {"offset": 0, "length": 2000, "duration": 200},
        {"offset": 2, "length": 1000, "duration": 50},
    ]
    cum_m, cum_s = build_cumulative(POINTS, spans, 3000, 250)
    assert cum_m[0] == 0 and cum_s[0] == 0
    assert cum_m[2] == pytest.approx(2000)
    assert cum_s[2] == pytest.approx(200)
    assert cum_m[-1] == pytest.approx(3000)
    assert cum_s[-1] == pytest.approx(250)
    assert cum_s[1] == pytest.approx(100, rel=1e-3)  # equal edges split the span evenly


def test_missing_spans_fall_back_to_section_totals():
    cum_m, cum_s = build_cumulative(POINTS, [], 3000, 300)
    assert cum_m[-1] == pytest.approx(3000)
    assert cum_s[-1] == pytest.approx(300)
    assert all(b >= a for a, b in zip(cum_s, cum_s[1:], strict=False))


def test_parse_concatenates_sections_without_duplicate_boundary():
    first, second = POINTS[:3], POINTS[2:]
    payload = {
        "routes": [
            {"sections": [section(first, 2000, 200, []), section(second, 1000, 100, [])]},
            {"sections": [section(POINTS, 3500, 400, [])]},
        ]
    }
    routes = parse_here_routes(payload)
    assert [r.id for r in routes] == ["A", "B"]
    a = routes[0]
    assert len(a.coords) == 4
    assert a.distance_miles == pytest.approx(3000 / METERS_PER_MILE)
    assert a.duration_seconds == pytest.approx(300)
    assert a.cum_seconds[2] == pytest.approx(200)


def test_parse_empty_response():
    assert parse_here_routes({"routes": []}) == []


class FakeGeocodeSession:
    def __init__(self, items):
        self.items = items

    def get(self, url, params, timeout):
        class Resp:
            status_code = 200

            def json(_):
                return {"items": self.items}

        return Resp()


def geocode_item(title, score):
    return {
        "title": title,
        "position": {"lat": 32.78, "lng": -96.8},
        "scoring": {"queryScore": score},
    }


class TestGeocode:
    def test_good_match_is_returned_with_its_label(self):
        session = FakeGeocodeSession([geocode_item("Dallas, TX, United States", 0.99)])
        point = HereRoutingProvider("key", session).geocode("dallas tx")
        assert (point.lat, point.lon, point.label) == (32.78, -96.8, "Dallas, TX, United States")

    def test_weak_match_is_rejected_with_the_closest_guess(self):
        session = FakeGeocodeSession([geocode_item("Nowhere, Fort Cobb, OK, United States", 0.54)])
        with pytest.raises(LocationNotFoundError, match="closest: Nowhere, Fort Cobb"):
            HereRoutingProvider("key", session).geocode("Qwxzzy Nowhere")

    def test_no_match(self):
        with pytest.raises(LocationNotFoundError):
            HereRoutingProvider("key", FakeGeocodeSession([])).geocode("asdfgh")
