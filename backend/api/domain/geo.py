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


def densify(path: list[tuple[float, float]], spacing_miles: float) -> list[tuple[float, float]]:
    """Points along a (lat, lon) path no more than `spacing_miles` apart, endpoints included."""
    if not path:
        return []
    out = [path[0]]
    for a, b in zip(path, path[1:], strict=False):
        steps = max(1, math.ceil(haversine_miles(a, b) / spacing_miles))
        for k in range(1, steps + 1):
            f = k / steps
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    return out


MILES_PER_DEG_LAT = 69.05


def corridor_grid(
    paths: list[list[tuple[float, float]]], step_deg: float, buffer_miles: float
) -> list[tuple[float, float]]:
    """Centres of grid cells (on multiples of `step_deg`) that touch a buffer around any path.

    A cell counts if its centre is within the buffer plus half the cell's diagonal, so the
    squares drawn on the map fully cover the buffer instead of leaving gaps along its edge.
    """
    cells: set[tuple[int, int]] = set()
    for path in paths:
        for lat, lon in densify(path, buffer_miles / 2):
            cos_lat = max(math.cos(math.radians(lat)), 0.01)
            half_diag = math.hypot(step_deg / 2, step_deg / 2 * cos_lat) * MILES_PER_DEG_LAT
            reach = buffer_miles + half_diag
            lat_span = reach / MILES_PER_DEG_LAT
            lon_span = lat_span / cos_lat
            for i in range(
                math.floor((lat - lat_span) / step_deg), math.ceil((lat + lat_span) / step_deg) + 1
            ):
                for j in range(
                    math.floor((lon - lon_span) / step_deg),
                    math.ceil((lon + lon_span) / step_deg) + 1,
                ):
                    if (i, j) not in cells and haversine_miles(
                        (lat, lon), (i * step_deg, j * step_deg)
                    ) <= reach:
                        cells.add((i, j))
    return [(round(i * step_deg, 4), round(j * step_deg, 4)) for i, j in sorted(cells)]


def shared_fraction(
    path: list[tuple[float, float]],
    others: list[list[tuple[float, float]]],
    near_miles: float = 0.3,
) -> float:
    """Share of `path`, by distance, that runs within `near_miles` of any of the `others`.

    Points along the other paths are bucketed into a grid about `near_miles` wide, so each
    point on `path` only has to be compared with the few points in neighbouring buckets.
    """
    cell = near_miles / MILES_PER_DEG_LAT

    def bucket(p: tuple[float, float]) -> tuple[int, int]:
        lat, lon = p
        return math.floor(lat / cell), math.floor(lon * math.cos(math.radians(lat)) / cell)

    buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for other in others:
        for p in densify(other, near_miles / 2):
            buckets.setdefault(bucket(p), []).append(p)

    samples = densify(path, near_miles / 2)
    if not samples:
        return 0.0
    shared = 0
    for p in samples:
        bi, bj = bucket(p)
        neighbours = (
            q for di in (-1, 0, 1) for dj in (-1, 0, 1) for q in buckets.get((bi + di, bj + dj), ())
        )
        if any(haversine_miles(p, q) <= near_miles for q in neighbours):
            shared += 1
    return shared / len(samples)
