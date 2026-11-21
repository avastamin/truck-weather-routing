import uuid
from datetime import datetime

from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.serializers import PlanInputSerializer
from api.services.heatmap import build_heatmap
from api.services.planner import PlanError, PlanRequest, build_plan
from api.services.routing import (
    LocationNotFoundError,
    NoRouteError,
    RoutingError,
    get_routing_provider,
)
from api.services.weather import OpenMeteoClient, WeatherError

PLAN_TTL_S = 2 * 60 * 60  # the heatmap endpoint reads the plan back for this long


def plan_cache_key(plan_id: str) -> str:
    return f"plan:{plan_id}"


def heatmap_cache_key(plan_id: str) -> str:
    return f"heatmap:{plan_id}"


def error(message: str, code: int, **extra) -> Response:
    return Response({"error": message, **extra}, status=code)


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


@api_view(["POST"])
def plan(request):
    serializer = PlanInputSerializer(data=request.data)
    if not serializer.is_valid():
        return error("Invalid input.", status.HTTP_400_BAD_REQUEST, fields=serializer.errors)
    req = PlanRequest(**serializer.validated_data)

    try:
        result = build_plan(req, get_routing_provider(), OpenMeteoClient(), timezone.now())
    except (PlanError, LocationNotFoundError, NoRouteError) as exc:
        return error(str(exc), status.HTTP_400_BAD_REQUEST)
    except (RoutingError, WeatherError) as exc:
        return error(str(exc), status.HTTP_502_BAD_GATEWAY)

    plan_id = uuid.uuid4().hex
    cache.set(
        plan_cache_key(plan_id),
        {
            "departure": req.departure.isoformat(),
            "load_lb": req.load_lb,
            "paths": [route["path"] for route in result["routes"]],
        },
        PLAN_TTL_S,
    )
    return Response({"plan_id": plan_id, **result})


@api_view(["GET"])
def heatmap(request, plan_id: str):
    cached = cache.get(heatmap_cache_key(plan_id))
    if cached is not None:
        return Response(cached)
    stored = cache.get(plan_cache_key(plan_id))
    if stored is None:
        return error("This plan has expired. Plan the trip again.", status.HTTP_404_NOT_FOUND)

    paths = [[(lat, lon) for lon, lat in path] for path in stored["paths"]]
    try:
        result = build_heatmap(
            paths,
            datetime.fromisoformat(stored["departure"]),
            stored["load_lb"],
            OpenMeteoClient(),
        )
    except WeatherError as exc:
        return error(str(exc), status.HTTP_502_BAD_GATEWAY)

    result = {"plan_id": plan_id, **result}
    cache.set(heatmap_cache_key(plan_id), result, PLAN_TTL_S)
    return Response(result)
