"""Forecast helpers: unit conversion and reading a value at an exact time.

Open-Meteo hourly precipitation values are totals for the preceding hour, so after conversion
they can be used directly as in/hr rates.
"""

from __future__ import annotations

from bisect import bisect_left

# Divisors to convert an Open-Meteo precipitation unit to inches.
_PER_INCH = {"mm": 25.4, "cm": 2.54, "inch": 1.0}


class ForecastRangeError(ValueError):
    """The requested time is outside the forecast, or the forecast has a gap there."""


def to_inches(value: float, unit: str) -> float:
    try:
        return value / _PER_INCH[unit]
    except KeyError:
        raise ValueError(f"Unexpected precipitation unit from forecast: {unit!r}") from None


def interpolate_at(times: list[float], values: list[float | None], t: float) -> float:
    """Value at time t (unix seconds), linearly interpolated between the surrounding hours."""
    if not times or t < times[0] or t > times[-1]:
        raise ForecastRangeError("Time is outside the forecast window")
    j = bisect_left(times, t)
    if times[j] == t:
        neighbours = [values[j]]
    else:
        neighbours = [values[j - 1], values[j]]
    if any(v is None for v in neighbours):
        raise ForecastRangeError("Forecast has no data for this hour")
    if len(neighbours) == 1:
        return float(neighbours[0])
    frac = (t - times[j - 1]) / (times[j] - times[j - 1])
    return neighbours[0] + (neighbours[1] - neighbours[0]) * frac
