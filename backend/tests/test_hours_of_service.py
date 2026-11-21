"""Driver breaks and rests added to a route's ETAs."""

import pytest

from api.domain.hours_of_service import (
    BREAK_SECONDS,
    REST_SECONDS,
    add_rest_stops,
    stop_times,
)
from api.domain.sampling import point_at_mile
from api.domain.types import Route

H = 3600


def straight_route(hours, mph=50.0, vertices=21):
    """East-west route driven at a constant speed."""
    miles = hours * mph
    coords = [(35.0, -100.0 + i * 0.5) for i in range(vertices)]
    return Route(
        id="A",
        coords=coords,
        cum_miles=[miles * i / (vertices - 1) for i in range(vertices)],
        cum_seconds=[hours * H * i / (vertices - 1) for i in range(vertices)],
    )


class TestStopTimes:
    def test_short_trip_needs_no_stops(self):
        assert stop_times(7.9 * H) == []

    def test_trip_ending_exactly_at_eight_hours_needs_no_break(self):
        assert stop_times(8 * H) == []

    def test_break_after_eight_hours_of_driving(self):
        assert stop_times(9 * H) == [(8 * H, "break")]

    def test_rest_after_eleven_hours_of_driving(self):
        assert stop_times(12 * H) == [(8 * H, "break"), (11 * H, "rest")]

    def test_pattern_repeats_every_eleven_driving_hours(self):
        assert stop_times(23 * H) == [
            (8 * H, "break"),
            (11 * H, "rest"),
            (19 * H, "break"),
            (22 * H, "rest"),
        ]


class TestAddRestStops:
    def test_short_route_is_unchanged(self):
        route = straight_route(5)
        assert add_rest_stops(route) == route

    def test_total_time_includes_stops_and_driving_time_does_not(self):
        route = add_rest_stops(straight_route(12))
        assert route.driving_seconds == pytest.approx(12 * H)
        assert route.duration_seconds == pytest.approx(12 * H + BREAK_SECONDS + REST_SECONDS)
        assert route.distance_miles == pytest.approx(600)

    def test_stops_are_where_the_driving_time_runs_out(self):
        route = add_rest_stops(straight_route(12))  # 50 mph
        brk, rest = route.rest_stops
        assert (brk.kind, rest.kind) == ("break", "rest")
        assert brk.mile == pytest.approx(400)
        assert rest.mile == pytest.approx(550)
        assert brk.arrive_seconds == pytest.approx(8 * H)
        assert brk.duration_seconds == BREAK_SECONDS
        # The rest starts after 11 h driving plus the 30 min break.
        assert rest.arrive_seconds == pytest.approx(11 * H + BREAK_SECONDS)

    def test_etas_before_a_stop_are_untouched_and_after_it_are_shifted(self):
        route = add_rest_stops(straight_route(12))
        assert point_at_mile(route, 300)[2] == pytest.approx(6 * H)
        assert point_at_mile(route, 450)[2] == pytest.approx(9 * H + BREAK_SECONDS)
        assert point_at_mile(route, 600)[2] == pytest.approx(12 * H + BREAK_SECONDS + REST_SECONDS)

    def test_checkpoint_at_a_stop_gets_the_time_the_truck_leaves(self):
        route = add_rest_stops(straight_route(12))
        assert point_at_mile(route, 550)[2] == pytest.approx(11 * H + BREAK_SECONDS + REST_SECONDS)

    def test_stop_position_is_on_the_route(self):
        route = add_rest_stops(straight_route(12))
        brk = route.rest_stops[0]
        lat, lon, _ = point_at_mile(route, brk.mile)
        assert (brk.lat, brk.lon) == pytest.approx((lat, lon))

    def test_cumulative_arrays_stay_monotonic(self):
        route = add_rest_stops(straight_route(30))
        assert all(b >= a for a, b in zip(route.cum_miles, route.cum_miles[1:], strict=False))
        assert all(b >= a for a, b in zip(route.cum_seconds, route.cum_seconds[1:], strict=False))
