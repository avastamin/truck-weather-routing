import pytest

from api.domain.geo import (
    corridor_grid,
    densify,
    haversine_miles,
    offset_midpoint,
    shared_fraction,
    simplify,
)


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


class TestDensify:
    def test_spacing_is_respected_and_endpoints_kept(self):
        path = [(35.0, -100.0), (35.0, -99.0)]  # ~57 miles
        points = densify(path, 10)
        assert points[0] == path[0] and points[-1] == path[-1]
        gaps = [haversine_miles(a, b) for a, b in zip(points, points[1:], strict=False)]
        assert max(gaps) <= 10

    def test_empty_path(self):
        assert densify([], 5) == []


class TestCorridorGrid:
    PATH = [(35.0, -101.0), (35.0, -99.0)]  # east-west, ~113 miles

    def test_cells_follow_the_route(self):
        cells = corridor_grid([self.PATH], 0.25, 15)
        lats = {lat for lat, _ in cells}
        lons = {lon for _, lon in cells}
        assert 35.0 in lats
        assert min(lons) <= -101.0 and max(lons) >= -99.0
        # 15 mi buffer + half a cell: never more than ~0.5 deg of latitude away
        assert all(abs(lat - 35.0) <= 0.5 for lat in lats)

    def test_cell_centres_sit_on_the_grid(self):
        for lat, lon in corridor_grid([self.PATH], 0.25, 15):
            assert (lat / 0.25).is_integer() and (lon / 0.25).is_integer()

    def test_every_route_point_is_inside_a_cell(self):
        cells = set(corridor_grid([self.PATH], 0.25, 15))
        for lat, lon in densify(self.PATH, 5):
            centre = (round(round(lat / 0.25) * 0.25, 4), round(round(lon / 0.25) * 0.25, 4))
            assert centre in cells

    def test_overlapping_routes_share_cells(self):
        one = corridor_grid([self.PATH], 0.25, 15)
        two = corridor_grid([self.PATH, self.PATH], 0.25, 15)
        assert one == two


class TestSharedFraction:
    ROAD = [(35.0, -101.0), (35.0, -100.0)]

    def test_same_road_is_fully_shared(self):
        assert shared_fraction(self.ROAD, [self.ROAD]) == 1.0

    def test_parallel_road_five_miles_away_shares_nothing(self):
        parallel = [(35.0725, -101.0), (35.0725, -100.0)]  # ~5 mi north
        assert shared_fraction(parallel, [self.ROAD]) == 0.0

    def test_route_that_leaves_halfway_shares_about_half(self):
        half = [(35.0, -101.0), (35.0, -100.5), (35.5, -100.0)]
        assert shared_fraction(half, [self.ROAD]) == pytest.approx(0.4, abs=0.1)

    def test_any_of_several_routes_counts(self):
        north = [(35.5, -101.0), (35.5, -100.0)]
        assert shared_fraction(self.ROAD, [north, self.ROAD]) == 1.0
