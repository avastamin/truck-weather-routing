import pytest

from api.domain.geo import haversine_miles, offset_midpoint, simplify


def test_haversine_one_degree_of_latitude():
    assert haversine_miles((35.0, -100.0), (36.0, -100.0)) == pytest.approx(69.09, abs=0.05)


class TestOffsetMidpoint:
    def test_zero_offset_is_midpoint(self):
        assert offset_midpoint((30.0, -100.0), (40.0, -100.0), 0) == pytest.approx((35.0, -100.0))

    def test_positive_is_left_of_direction(self):
        # Heading north, left is west (more negative longitude).
        lat, lon = offset_midpoint((30.0, -100.0), (40.0, -100.0), 0.2)
        assert lat == pytest.approx(35.0)
        assert lon < -100.0

    def test_offset_distance_is_fraction_of_trip(self):
        a, b = (30.0, -100.0), (40.0, -100.0)
        mid = offset_midpoint(a, b, 0)
        moved = offset_midpoint(a, b, -0.2)
        assert moved[1] > -100.0  # right of a northbound trip is east
        assert haversine_miles(mid, moved) == pytest.approx(0.2 * haversine_miles(a, b), rel=0.02)


class TestSimplify:
    def test_collinear_points_are_dropped(self):
        line = [(35.0, -100.0 + i * 0.01) for i in range(50)]
        assert simplify(line, 1e-4) == [line[0], line[-1]]

    def test_corner_is_kept(self):
        path = [(35.0, -100.0), (35.0, -99.5), (35.0, -99.0), (35.5, -99.0), (36.0, -99.0)]
        assert simplify(path, 1e-4) == [(35.0, -100.0), (35.0, -99.0), (36.0, -99.0)]

    def test_small_wiggles_within_tolerance_are_removed(self):
        path = [(35.0, -100.0), (35.00001, -99.5), (35.0, -99.0)]
        assert simplify(path, 1e-4) == [(35.0, -100.0), (35.0, -99.0)]

    def test_short_paths_unchanged(self):
        assert simplify([(1.0, 2.0), (3.0, 4.0)], 1e-4) == [(1.0, 2.0), (3.0, 4.0)]
