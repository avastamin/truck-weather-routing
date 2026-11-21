"""End-to-end plan building with a fake routing provider and fake weather (no network)."""

from datetime import UTC, datetime, timedelta

import pytest

from api.domain.types import GeoPoint, Route
from api.services.planner import PlanError, PlanRequest, build_plan, check_departure, forecast_end
from api.services.weather import HourlySeries, grid_key, hour_ceil, hour_floor

NOW = datetime(2026, 11, 21, 15, 30, tzinfo=UTC)
DEPART = NOW + timedelta(hours=2)
ORIGIN = GeoPoint(35.0, -101.0, "Start, TX")
DEST = GeoPoint(35.0, -100.0, "End, TX")


def east_route(miles, hours, lat=35.0):
    """Straight route along a parallel, 11 vertices."""
    coords = [(lat, -101.0 + i * 0.1) for i in range(11)]
    return Route(
        id="X",
        coords=coords,
        cum_miles=[miles * i / 10 for i in range(11)],
        cum_seconds=[hours * 3600 * i / 10 for i in range(11)],
    )


class FakeProvider:
    def __init__(self, routes, places=None):
        self._routes = routes
        self.places = places or {"start": ORIGIN, "end": DEST}

    def geocode(self, query):
        return self.places[query]

    def routes(self, origin, destination, departure, load_lb, via=None):
        if via is not None:
            return [self._routes[0]]  # same as the first -> fallback adds nothing
        return self._routes


class FakeWeather:
    """Constant weather everywhere, or per-latitude weather via `by_lat`."""

    def __init__(self, wind=5.0, rain=0.0, snow=0.0, by_lat=None):
        self.default = (wind, rain, snow)
        self.by_lat = by_lat or {}
        self.calls = []

    def hourly(self, points, start, end):
        self.calls.append((points, start, end))
        start_h, end_h = hour_floor(start), hour_ceil(end)
        hours = int((end_h - start_h).total_seconds() // 3600) + 1
        times = [int(start_h.timestamp()) + 3600 * i for i in range(hours)]
        out = {}
        for lat, lon in points:
            wind, rain, snow = self.by_lat.get(round(lat, 1), self.default)
            out[grid_key(lat, lon)] = HourlySeries(
                times=times,
                wind_mph=[wind] * hours,
                gust_mph=[wind * 1.4] * hours,
                rain_in=[rain] * hours,
                snow_in=[snow] * hours,
            )
        return out


def request(**overrides):
    base = dict(
        origin="start", destination="end", departure=DEPART, load_lb=30_000, interval_miles=25
    )
    return PlanRequest(**{**base, **overrides})


class TestDepartureWindow:
    def test_within_grace_period_is_allowed(self):
        check_departure(NOW - timedelta(minutes=14), NOW)

    def test_past_beyond_grace_is_rejected(self):
        with pytest.raises(PlanError, match="past"):
            check_departure(NOW - timedelta(minutes=16), NOW)

    def test_up_to_seven_days_ahead(self):
        check_departure(NOW + timedelta(days=7), NOW)
        with pytest.raises(PlanError, match="7 days"):
            check_departure(NOW + timedelta(days=7, minutes=1), NOW)

    def test_naive_departure_rejected(self):
        with pytest.raises(PlanError, match="timezone"):
            check_departure(datetime(2026, 11, 22, 8), NOW)

    def test_forecast_end_is_last_hour_of_day_16(self):
        assert forecast_end(NOW) == datetime(2026, 12, 6, 23, tzinfo=UTC)

    def test_trip_ending_after_forecast_is_rejected(self):
        # Leaves 7 days out and drives for 9 days: past the 16-day forecast.
        provider = FakeProvider([east_route(5000, 24 * 9)])
        with pytest.raises(PlanError, match="last available forecast hour"):
            build_plan(request(departure=NOW + timedelta(days=7)), provider, FakeWeather(), NOW)


class TestBuildPlan:
    def test_response_shape(self):
        provider = FakeProvider([east_route(60, 1.2), east_route(70, 1.5)])
        plan = build_plan(request(), provider, FakeWeather(), NOW)
        assert plan["recommended_route_id"] == "A"
        assert [r["id"] for r in plan["routes"]] == ["A", "B"]
        route = plan["routes"][0]
        assert route["rank"] == 1
        assert route["distance_miles"] == 60
        assert route["path"][0] == [-101.0, 35.0]  # [lon, lat]
        assert len(route["path"]) == 2  # straight line simplified to its endpoints
        cp = route["checkpoints"][1]
        assert set(cp) == {
            "mile",
            "lat",
            "lon",
            "eta",
            "covers_miles",
            "wind_mph",
            "gust_mph",
            "rain_in_hr",
            "snow_in_hr",
            "level",
            "triggered_by",
            "reasons",
        }
        assert [c["mile"] for c in route["checkpoints"]] == [0, 25, 50, 60]
        assert cp["eta"] == (DEPART + timedelta(minutes=30)).isoformat()

    def test_covered_miles_add_up_to_route_length(self):
        provider = FakeProvider([east_route(237.4, 4)])
        route = build_plan(request(interval_miles=10), provider, FakeWeather(), NOW)["routes"][0]
        assert sum(route["miles_by_level"].values()) == pytest.approx(237.4, abs=0.1)

    def test_weather_is_fetched_once_for_the_whole_trip_window(self):
        weather = FakeWeather()
        provider = FakeProvider([east_route(60, 1.2), east_route(70, 3)])
        build_plan(request(), provider, weather, NOW)
        assert len(weather.calls) == 1
        _, start, end = weather.calls[0]
        assert start == DEPART
        assert end == DEPART + timedelta(hours=3)

    def test_safer_route_is_recommended_over_faster_one(self):
        fast_windy = east_route(60, 1.0, lat=35.0)
        slow_calm = east_route(80, 2.0, lat=36.0)
        weather = FakeWeather(by_lat={35.0: (48, 0, 0), 36.0: (5, 0, 0)})
        plan = build_plan(
            request(load_lb=20_000), FakeProvider([fast_windy, slow_calm]), weather, NOW
        )
        assert plan["recommended_route_id"] == "B"
        assert plan["reason"] == "0 severe miles vs 60 on Route A"
        severe = plan["routes"][0]["checkpoints"][0]
        assert severe["level"] == "severe"
        assert severe["triggered_by"] == ["wind"]

    def test_heavier_load_turns_severe_wind_into_no_travel(self):
        provider = FakeProvider([east_route(60, 1.0)])
        weather = FakeWeather(wind=48)
        light = build_plan(request(load_lb=25_000), provider, weather, NOW)
        heavy = build_plan(request(load_lb=45_000), provider, weather, NOW)
        assert light["routes"][0]["checkpoints"][0]["level"] == "severe"
        assert heavy["routes"][0]["checkpoints"][0]["level"] == "no_travel"
        assert heavy["no_travel_warning"] is True

    def test_same_origin_and_destination_rejected(self):
        provider = FakeProvider([east_route(60, 1)], places={"start": ORIGIN, "end": ORIGIN})
        with pytest.raises(PlanError, match="same place"):
            build_plan(request(), provider, FakeWeather(), NOW)

    def test_missing_forecast_hour_is_a_plan_error(self):
        class GappyWeather(FakeWeather):
            def hourly(self, points, start, end):
                out = super().hourly(points, start, end)
                return {
                    k: HourlySeries(
                        s.times, [None] * len(s.times), s.gust_mph, s.rain_in, s.snow_in
                    )
                    for k, s in out.items()
                }

        with pytest.raises(PlanError, match="missing"):
            build_plan(request(), FakeProvider([east_route(60, 1)]), GappyWeather(), NOW)
