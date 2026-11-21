"""Checkpoint placement, miles covered per checkpoint, and position/ETA interpolation."""

from datetime import UTC, datetime, timedelta

import pytest

from api.domain.sampling import checkpoint_miles, coverage_miles, point_at_mile, sample_route
from api.domain.types import Route

DEPART = datetime(2026, 11, 22, 8, 0, tzinfo=UTC)


def straight_route(miles, hours, vertices=11):
    """Straight east-west route with uniform speed."""
    coords = [(35.0, -100.0 + i * 0.1) for i in range(vertices)]
    cum_m = [miles * i / (vertices - 1) for i in range(vertices)]
    cum_s = [hours * 3600 * i / (vertices - 1) for i in range(vertices)]
    return Route(id="A", coords=coords, cum_miles=cum_m, cum_seconds=cum_s)


class TestCheckpointMiles:
    def test_60_miles_every_25(self):
        assert checkpoint_miles(60, 25) == [0, 25, 50, 60]

    def test_exact_multiple_has_no_duplicate_end(self):
        assert checkpoint_miles(50, 25) == [0, 25, 50]

    def test_float_noise_at_end_has_no_duplicate(self):
        assert checkpoint_miles(50.0000001, 25) == [0, 25, 50.0000001]

    def test_route_shorter_than_interval_gets_both_endpoints(self):
        assert checkpoint_miles(7, 10) == [0, 7]

    @pytest.mark.parametrize("interval", [10, 25, 50])
    def test_spacing_equals_interval_except_last(self, interval):
        miles = checkpoint_miles(237.4, interval)
        gaps = [b - a for a, b in zip(miles, miles[1:], strict=False)]
        assert all(g == pytest.approx(interval) for g in gaps[:-1])
        assert 0 < gaps[-1] <= interval
        assert miles[0] == 0 and miles[-1] == 237.4

    @pytest.mark.parametrize("interval", [0, 5, 30, -10])
    def test_only_10_25_50_allowed(self, interval):
        with pytest.raises(ValueError):
            checkpoint_miles(100, interval)


class TestCoverage:
    def test_coverage_60_miles_every_25(self):
        assert coverage_miles([0, 25, 50, 60]) == [12.5, 25, 17.5, 5]

    @pytest.mark.parametrize("total", [3.2, 50, 99.9, 812.37])
    @pytest.mark.parametrize("interval", [10, 25, 50])
    def test_coverage_sums_to_route_length(self, total, interval):
        assert sum(coverage_miles(checkpoint_miles(total, interval))) == pytest.approx(total)


class TestInterpolation:
    def test_point_at_vertex_and_midpoint(self):
        route = straight_route(100, 2)
        lat, lon, secs = point_at_mile(route, 10)
        assert (lat, lon) == pytest.approx((35.0, -99.9))
        assert secs == pytest.approx(720)
        lat, lon, secs = point_at_mile(route, 15)
        assert lon == pytest.approx(-99.85)
        assert secs == pytest.approx(1080)

    def test_eta_follows_uneven_speed(self):
        # First 10 mi take 1 h (slow), next 90 mi take 1 h (fast).
        route = Route(
            id="A",
            coords=[(35.0, -100.0), (35.0, -99.9), (35.0, -98.0)],
            cum_miles=[0, 10, 100],
            cum_seconds=[0, 3600, 7200],
        )
        assert point_at_mile(route, 5)[2] == pytest.approx(1800)
        assert point_at_mile(route, 55)[2] == pytest.approx(5400)

    def test_zero_length_edge_does_not_divide_by_zero(self):
        route = Route(
            id="A",
            coords=[(35.0, -100.0), (35.0, -100.0), (35.0, -99.0)],
            cum_miles=[0, 0, 50],
            cum_seconds=[0, 0, 3600],
        )
        assert point_at_mile(route, 0)[2] == 0
        assert point_at_mile(route, 25)[2] == pytest.approx(1800)

    def test_mile_outside_route_rejected(self):
        route = straight_route(100, 2)
        with pytest.raises(ValueError):
            point_at_mile(route, 100.5)
        with pytest.raises(ValueError):
            point_at_mile(route, -1)


class TestSampleRoute:
    def test_checkpoints_have_mile_position_eta_and_coverage(self):
        route = straight_route(60, 1.2)  # 50 mph
        cps = sample_route(route, 25, DEPART)
        assert [c.mile for c in cps] == [0, 25, 50, 60]
        assert [c.covers_miles for c in cps] == [12.5, 25, 17.5, 5]
        assert cps[0].eta == DEPART
        assert cps[1].eta == DEPART + timedelta(minutes=30)
        assert cps[-1].eta == DEPART + timedelta(minutes=72)
        assert (cps[0].lat, cps[0].lon) == pytest.approx(route.coords[0])
        assert (cps[-1].lat, cps[-1].lon) == pytest.approx(route.coords[-1])

    def test_naive_departure_rejected(self):
        with pytest.raises(ValueError):
            sample_route(straight_route(60, 1), 25, datetime(2026, 11, 22, 8, 0))
