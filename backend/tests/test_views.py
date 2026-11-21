"""POST /api/plan: validation, error mapping and the stored plan."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from api import views
from api.services.routing import LocationNotFoundError, RoutingError
from tests.test_planner import DEST, ORIGIN, FakeProvider, FakeWeather, east_route


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def fakes(monkeypatch):
    provider = FakeProvider([east_route(60, 1.2)], places={"Start": ORIGIN, "End": DEST})
    monkeypatch.setattr(views, "get_routing_provider", lambda: provider)
    monkeypatch.setattr(views, "OpenMeteoClient", FakeWeather)
    return provider


def body(**overrides):
    departure = (timezone.now() + timedelta(hours=1)).isoformat()
    return {
        "origin": "Start",
        "destination": "End",
        "departure": departure,
        "load_lb": 30000,
        "interval_miles": 25,
        **overrides,
    }


def post(client, data):
    return client.post("/api/plan", data, format="json")


def test_successful_plan_is_stored_for_the_heatmap(client, fakes):
    resp = post(client, body())
    assert resp.status_code == 200
    data = resp.json()
    assert data["recommended_route_id"] == "A"
    stored = cache.get(views.plan_cache_key(data["plan_id"]))
    assert stored["load_lb"] == 30000
    assert stored["paths"] == [data["routes"][0]["path"]]


def test_interval_defaults_to_25(client, fakes):
    data = body()
    del data["interval_miles"]
    assert post(client, data).json()["interval_miles"] == 25


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"interval_miles": 30}, "interval_miles"),
        ({"load_lb": 0}, "load_lb"),
        ({"load_lb": 250000}, "load_lb"),
        ({"origin": ""}, "origin"),
        ({"departure": "2026-11-22T08:00:00"}, "departure"),  # no offset
        ({"departure": "tomorrow"}, "departure"),
    ],
)
def test_invalid_input_returns_field_errors(client, fakes, overrides, field):
    resp = post(client, body(**overrides))
    assert resp.status_code == 400
    assert field in resp.json()["fields"]


def test_departure_in_the_past_is_400(client, fakes):
    resp = post(client, body(departure=(timezone.now() - timedelta(hours=1)).isoformat()))
    assert resp.status_code == 400
    assert "past" in resp.json()["error"]


def test_unknown_location_is_400(client, fakes, monkeypatch):
    def not_found(query):
        raise LocationNotFoundError(f"Could not find a US location for '{query}'.")

    monkeypatch.setattr(fakes, "geocode", not_found)
    resp = post(client, body())
    assert resp.status_code == 400
    assert "Could not find" in resp.json()["error"]


def test_provider_failure_is_502(client, monkeypatch):
    def broken():
        raise RoutingError("Routing is not configured (HERE_API_KEY is missing).")

    monkeypatch.setattr(views, "get_routing_provider", broken)
    resp = post(client, body())
    assert resp.status_code == 502
    assert "HERE_API_KEY" in resp.json()["error"]


class TestHeatmapEndpoint:
    def test_unknown_or_expired_plan_is_404(self, client):
        resp = client.get("/api/heatmap/does-not-exist")
        assert resp.status_code == 404
        assert "expired" in resp.json()["error"]

    def test_heatmap_for_a_stored_plan_is_built_once(self, client, fakes, monkeypatch):
        plan_id = post(client, body()).json()["plan_id"]
        calls = []

        class CountingWeather(FakeWeather):
            def hourly(self, points, start, end):
                calls.append(len(points))
                return super().hourly(points, start, end)

        monkeypatch.setattr(views, "OpenMeteoClient", CountingWeather)
        first = client.get(f"/api/heatmap/{plan_id}")
        second = client.get(f"/api/heatmap/{plan_id}")
        assert first.status_code == 200
        assert first.json() == second.json()
        assert len(calls) == 1
        data = first.json()
        assert data["plan_id"] == plan_id
        assert len(data["risk"]) == len(data["cells"])
