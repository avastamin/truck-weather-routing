"""Driver breaks and rests, so ETAs reflect when a truck can actually be somewhere.

Simplified US hours-of-service rules for property-carrying drivers: a 30-minute break after
8 hours of driving and a 10-hour rest after 11 hours of driving, repeating for multi-day trips.
The driver is assumed to start the trip fresh. The 14-hour on-duty window is respected by this
pattern (8 h + 0.5 h + 3 h); the 60/70-hour weekly limits are not modelled.
"""

from __future__ import annotations

from dataclasses import replace

from api.domain.types import RestStop, Route

HOUR = 3600
BREAK_AFTER_DRIVING = 8 * HOUR
BREAK_SECONDS = 30 * 60
REST_AFTER_DRIVING = 11 * HOUR
REST_SECONDS = 10 * HOUR

STOP_SECONDS = {"break": BREAK_SECONDS, "rest": REST_SECONDS}


def stop_times(driving_seconds: float) -> list[tuple[float, str]]:
    """(driving seconds at which the stop starts, kind) for a trip of this much driving.

    No stop is needed if the trip ends exactly when the driving time runs out.
    """
    stops: list[tuple[float, str]] = []
    shift_start = 0.0
    while True:
        brk = shift_start + BREAK_AFTER_DRIVING
        if brk >= driving_seconds:
            return stops
        stops.append((brk, "break"))
        rest = shift_start + REST_AFTER_DRIVING
        if rest >= driving_seconds:
            return stops
        stops.append((rest, "rest"))
        shift_start = rest


def add_rest_stops(route: Route) -> Route:
    """The route with its breaks and rests built into the ETAs.

    Each stop becomes two vertices at the same place: one when the truck arrives and one when it
    leaves. ETAs before a stop are unchanged and ETAs after it move later by the stop's length.
    Expects a route with driving time only (no stops added yet).
    """
    stops = stop_times(route.duration_seconds)
    if not stops:
        return route

    coords = [route.coords[0]]
    miles = [route.cum_miles[0]]
    seconds = [route.cum_seconds[0]]
    rest_stops: list[RestStop] = []
    offset = 0.0
    k = 0
    for i in range(len(route.coords) - 1):
        s0, s1 = route.cum_seconds[i], route.cum_seconds[i + 1]
        while k < len(stops) and stops[k][0] <= s1:
            at, kind = stops[k]
            frac = (at - s0) / (s1 - s0) if s1 > s0 else 0.0
            (lat0, lon0), (lat1, lon1) = route.coords[i], route.coords[i + 1]
            point = (lat0 + (lat1 - lat0) * frac, lon0 + (lon1 - lon0) * frac)
            mile = route.cum_miles[i] + (route.cum_miles[i + 1] - route.cum_miles[i]) * frac
            duration = STOP_SECONDS[kind]
            rest_stops.append(RestStop(kind, mile, point[0], point[1], at + offset, duration))
            coords += [point, point]
            miles += [mile, mile]
            seconds += [at + offset, at + offset + duration]
            offset += duration
            k += 1
        coords.append(route.coords[i + 1])
        miles.append(route.cum_miles[i + 1])
        seconds.append(s1 + offset)

    return replace(
        route, coords=coords, cum_miles=miles, cum_seconds=seconds, rest_stops=tuple(rest_stops)
    )
