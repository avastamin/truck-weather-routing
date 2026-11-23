"""Open-Meteo client: unit conversion, grid dedupe, batching, caching and error handling."""

from datetime import UTC, datetime

import pytest
import requests
from django.core.cache.backends.locmem import LocMemCache

from api.services import weather
from api.services.weather import OpenMeteoClient, WeatherError, grid_key, parse_location

START = datetime(2026, 11, 22, 8, 20, tzinfo=UTC)
END = datetime(2026, 11, 22, 10, 5, tzinfo=UTC)
T0 = int(datetime(2026, 11, 22, 8, tzinfo=UTC).timestamp())
METRIC_UNITS = {
    "time": "unixtime",
    "wind_speed_10m": "mp/h",
    "wind_gusts_10m": "mp/h",
    "rain": "mm",
    "showers": "mm",
    "snowfall": "cm",
}


def location(wind=10.0, rain_mm=2.54, showers_mm=0.0, snow_cm=2.54, hours=4, units=None):
    return {
        "hourly_units": units or METRIC_UNITS,
        "hourly": {
            "time": [T0 + 3600 * i for i in range(hours)],
            "wind_speed_10m": [wind] * hours,
            "wind_gusts_10m": [wind * 1.5] * hours,
            "rain": [rain_mm] * hours,
            "showers": [showers_mm] * hours,
            "snowfall": [snow_cm] * hours,
        },
    }


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


class FakeSession:
    """Answers each request with one generated location per requested point."""

    def __init__(self, status=200, body=None, error=None):
        self.calls = []
        self.urls = []
        self.status, self.body, self.error = status, body, error

    def get(self, url, params, timeout):
        self.calls.append(params)
        self.urls.append(url)
        if self.error:
            raise self.error
        if self.body is not None:
            return FakeResponse(self.body, self.status)
        n = len(params["latitude"].split(","))
        return FakeResponse([location() for _ in range(n)], self.status)


@pytest.fixture
def cache():
    c = LocMemCache("test-weather", {})
    c.clear()
    return c


class TestParseLocation:
    def test_rain_and_showers_are_added_and_converted(self):
        series = parse_location(location(rain_mm=2.54, showers_mm=3.81))
        assert series.rain_in[0] == pytest.approx(0.25)

    def test_snowfall_cm_converted_to_inches(self):
        series = parse_location(location(snow_cm=7.62))
        assert series.snow_in[0] == pytest.approx(3.0)

    def test_gaps_stay_none(self):
        loc = location()
        loc["hourly"]["showers"][1] = None
        loc["hourly"]["snowfall"][2] = None
        series = parse_location(loc)
        assert series.rain_in[1] is None and series.snow_in[2] is None
        assert series.rain_in[0] is not None

    def test_unknown_precip_unit_fails(self):
        with pytest.raises(WeatherError, match="unit"):
            parse_location(location(units={**METRIC_UNITS, "snowfall": "furlongs"}))

    def test_wind_not_in_mph_fails(self):
        with pytest.raises(WeatherError, match="wind unit"):
            parse_location(location(units={**METRIC_UNITS, "wind_speed_10m": "km/h"}))


def test_grid_key_snaps_to_tenth_of_a_degree():
    assert grid_key(32.7843, -96.8012) == (32.8, -96.8)
    assert grid_key(32.7843, -96.8012) == grid_key(32.81, -96.79)


class TestClient:
    def test_nearby_points_share_one_forecast(self, cache):
        session = FakeSession()
        client = OpenMeteoClient(cache=cache, api_key="", session=session)
        result = client.hourly([(32.78, -96.80), (32.81, -96.79), (35.2, -101.8)], START, END)
        assert set(result) == {(32.8, -96.8), (35.2, -101.8)}
        assert session.calls[0]["latitude"] == "32.8,35.2"

    def test_request_covers_whole_hours_around_the_trip(self, cache):
        session = FakeSession()
        OpenMeteoClient(cache=cache, api_key="", session=session).hourly(
            [(32.8, -96.8)], START, END
        )
        params = session.calls[0]
        assert params["start_hour"] == "2026-11-22T08:00"
        assert params["end_hour"] == "2026-11-22T11:00"
        assert params["wind_speed_unit"] == "mph"
        assert "precipitation_unit" not in params  # metric, converted by us

    def test_large_requests_are_batched(self, cache, monkeypatch):
        monkeypatch.setattr(weather, "BATCH_SIZE", 2)
        session = FakeSession()
        points = [(30.0 + i, -100.0) for i in range(5)]
        result = OpenMeteoClient(cache=cache, api_key="", session=session).hourly(
            points, START, END
        )
        assert len(session.calls) == 3
        assert len(result) == 5

    def test_second_request_is_served_from_cache(self, cache):
        session = FakeSession()
        client = OpenMeteoClient(cache=cache, api_key="", session=session)
        client.hourly([(32.8, -96.8)], START, END)
        client.hourly([(32.8, -96.8)], START, END)
        assert len(session.calls) == 1

    def test_only_uncached_points_are_fetched(self, cache):
        session = FakeSession()
        client = OpenMeteoClient(cache=cache, api_key="", session=session)
        client.hourly([(32.8, -96.8)], START, END)
        client.hourly([(32.8, -96.8), (35.2, -101.8)], START, END)
        assert session.calls[1]["latitude"] == "35.2"

    def test_api_error_reason_is_passed_on(self, cache):
        body = {"error": True, "reason": "Parameter 'start_hour' is out of allowed range"}
        client = OpenMeteoClient(
            cache=cache, api_key="", session=FakeSession(status=400, body=body)
        )
        with pytest.raises(WeatherError, match="out of allowed range"):
            client.hourly([(32.8, -96.8)], START, END)

    def test_network_failure_becomes_weather_error(self, cache):
        session = FakeSession(error=requests.ConnectionError("boom"))
        with pytest.raises(WeatherError, match="unreachable"):
            OpenMeteoClient(cache=cache, api_key="", session=session).hourly(
                [(32.8, -96.8)], START, END
            )

    def test_single_location_object_response_is_accepted(self, cache):
        session = FakeSession(body=location())
        result = OpenMeteoClient(cache=cache, api_key="", session=session).hourly(
            [(32.8, -96.8)], START, END
        )
        assert list(result) == [(32.8, -96.8)]

    def test_free_api_is_used_without_a_key(self, cache):
        session = FakeSession()
        OpenMeteoClient(cache=cache, session=session, api_key="").hourly(
            [(32.8, -96.8)], START, END
        )
        assert session.urls == [weather.OPEN_METEO_URL]
        assert "apikey" not in session.calls[0]

    def test_api_key_switches_to_the_customer_api(self, cache):
        session = FakeSession()
        client = OpenMeteoClient(cache=cache, session=session, api_key="k123")
        client.hourly([(32.8, -96.8)], START, END)
        assert session.urls == [weather.OPEN_METEO_CUSTOMER_URL]
        assert session.calls[0]["apikey"] == "k123"
