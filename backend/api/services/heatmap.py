"""Weather grid around a plan's routes for the next 48 hours after departure.

The response is a set of parallel arrays (one row per cell, one column per hour) so the
frontend can switch hours by reading a different column, without new requests.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from api.domain.forecast import ForecastRangeError, interpolate_at
from api.domain.geo import corridor_grid
from api.domain.risk import assess
from api.services.weather import HourlySeries, OpenMeteoClient, grid_key

HOURS = 48
GRID_STEP_DEG = 0.25
BUFFER_MILES = 15.5  # ~25 km either side of each route
# Each cell is one location in the weather request. Long trips get a coarser grid rather than
# thousands of locations.
MAX_CELLS = 600
NO_DATA = -1


def heatmap_cells(
    paths: list[list[tuple[float, float]]],
) -> tuple[list[tuple[float, float]], float]:
    """Grid cells for the corridor, and the cell size used."""
    step = GRID_STEP_DEG
    cells = corridor_grid(paths, step, BUFFER_MILES)
    while len(cells) > MAX_CELLS:
        step *= 2
        cells = corridor_grid(paths, step, BUFFER_MILES)
    return cells, step


def _value(series: HourlySeries, values: list[float | None], t: float) -> float | None:
    try:
        return interpolate_at(series.times, values, t)
    except ForecastRangeError:
        return None


def _rounded(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def build_heatmap(
    paths: list[list[tuple[float, float]]],
    departure: datetime,
    load_lb: float,
    weather: OpenMeteoClient,
) -> dict[str, Any]:
    cells, step = heatmap_cells(paths)
    end = departure + timedelta(hours=HOURS)
    forecasts = weather.hourly(cells, departure, end)
    times = [(departure + timedelta(hours=h)).timestamp() for h in range(HOURS + 1)]

    wind_rows, gust_rows, rain_rows, snow_rows, risk_rows = [], [], [], [], []
    for lat, lon in cells:
        series = forecasts[grid_key(lat, lon)]
        wind, gust, rain, snow, risk = [], [], [], [], []
        for t in times:
            w = _value(series, series.wind_mph, t)
            r = _value(series, series.rain_in, t)
            s = _value(series, series.snow_in, t)
            wind.append(_rounded(w, 0))
            gust.append(_rounded(_value(series, series.gust_mph, t), 0))
            rain.append(_rounded(r, 2))
            snow.append(_rounded(s, 2))
            if w is None or r is None or s is None:
                risk.append(NO_DATA)
            else:
                level = assess(wind_mph=w, rain_in_hr=r, snow_in_hr=s, load_lb=load_lb).level
                risk.append(int(level))
        wind_rows.append(wind)
        gust_rows.append(gust)
        rain_rows.append(rain)
        snow_rows.append(snow)
        risk_rows.append(risk)

    return {
        "start": departure.isoformat(),
        "hours": HOURS,
        "cell_size_deg": step,
        # [lon, lat] cell centres, as map libraries expect
        "cells": [[lon, lat] for lat, lon in cells],
        # risk: 0 Low .. 4 No Travel, -1 where the forecast has no data
        "risk": risk_rows,
        "wind_mph": wind_rows,
        "gust_mph": gust_rows,
        "rain_in_hr": rain_rows,
        "snow_in_hr": snow_rows,
    }
