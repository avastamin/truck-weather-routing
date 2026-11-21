"""Geometry helpers."""

from __future__ import annotations

import math

EARTH_RADIUS_MILES = 3958.7613
METERS_PER_MILE = 1609.344


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in miles between two (lat, lon) points."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def _to_xy(point: tuple[float, float], ref_lat: float) -> tuple[float, float]:
    """Project (lat, lon) onto a flat plane in degrees, scaling longitude by latitude."""
    lat, lon = point
    return lon * math.cos(math.radians(ref_lat)), lat


def offset_midpoint(
    a: tuple[float, float], b: tuple[float, float], fraction: float
) -> tuple[float, float]:
    """Midpoint of a-b moved sideways by `fraction` of the a-b distance.

    Positive fractions move to the left of the a->b direction, negative to the right. Used to
    pick a via point that pushes the router onto a different corridor.
    """
    ref = (a[0] + b[0]) / 2
    ax, ay = _to_xy(a, ref)
    bx, by = _to_xy(b, ref)
    dx, dy = bx - ax, by - ay
    mx, my = (ax + bx) / 2, (ay + by) / 2
    # (-dy, dx) is (dx, dy) turned 90 degrees to the left; it has the same length as a-b.
    x, y = mx - dy * fraction, my + dx * fraction
    return y, x / math.cos(math.radians(ref))


def simplify(points: list[tuple[float, float]], tolerance_deg: float) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker line simplification. Keeps both endpoints.

    Long routes come back from the router with thousands of vertices; the map only needs the
    shape, so this keeps the response small without visibly changing the line.
    """
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        (y1, x1), (y2, x2) = points[start], points[end]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        worst, worst_i = 0.0, -1
        for i in range(start + 1, end):
            y, x = points[i]
            if length == 0:
                dist = math.hypot(x - x1, y - y1)
            else:
                dist = abs(dy * (x - x1) - dx * (y - y1)) / length
            if dist > worst:
                worst, worst_i = dist, i
        if worst > tolerance_deg:
            keep[worst_i] = True
            stack.append((start, worst_i))
            stack.append((worst_i, end))
    return [p for p, k in zip(points, keep, strict=True) if k]
