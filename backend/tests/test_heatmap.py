"""Heatmap grid and the 48-hour arrays built from it."""

from datetime import UTC, datetime, timedelta

from api.services import heatmap
from api.services.heatmap import HOURS, NO_DATA, build_heatmap, heatmap_cells
from api.services.weather import HourlySeries, grid_key, hour_ceil, hour_floor

DEPART = datetime(2026, 11, 22, 8, 30, tzinfo=UTC)
PATH = [(35.0, -101.0), (35.0, -100.0)]


class RampWeather:
    """Wind rises 1 mph per hour from 0 at the first forecast hour; no rain or snow."""

    def __init__(self, gap_at_hour=None):
        self.calls = []
        self.gap_at_hour = gap_at_hour

    def hourly(self, points, start, end):
        self.calls.append((len(points), start, end))
        start_h, end_h = hour_floor(start), hour_ceil(end)
        n = int((end_h - start_h).total_seconds() // 3600) + 1
        times = [int(start_h.timestamp()) + 3600 * i for i in range(n)]
        wind = [float(i) for i in range(n)]
        if self.gap_at_hour is not None:
            wind[self.gap_at_hour] = None
        return {
            grid_key(lat, lon): HourlySeries(times, wind, wind, [0.0] * n, [0.0] * n)
            for lat, lon in points
        }


def test_long_corridors_get_a_coarser_grid(monkeypatch):
    monkeypatch.setattr(heatmap, "MAX_CELLS", 10)
    cells, step = heatmap_cells([PATH])
    assert len(cells) <= 10
    assert step > heatmap.GRID_STEP_DEG


def test_arrays_have_one_row_per_cell_and_49_hours():
    result = build_heatmap([PATH], DEPART, 30_000, RampWeather())
    n = len(result["cells"])
    assert n > 0
    for key in ("risk", "wind_mph", "gust_mph", "rain_in_hr", "snow_in_hr"):
        assert len(result[key]) == n
        assert all(len(row) == HOURS + 1 for row in result[key])
    assert result["start"] == DEPART.isoformat()


def test_hours_count_from_departure_not_from_the_whole_hour():
    # Departure is 08:30. Hour 3 is 11:30, halfway between the 11:00 (3 mph) and 12:00 (4 mph)
    # forecast values, so 3.5 mph, shown rounded to whole mph.
    weather = RampWeather()
    result = build_heatmap([PATH], DEPART, 30_000, weather)
    assert result["wind_mph"][0][3] == round(3.5)
    _, start, end = weather.calls[0]
    assert start == DEPART and end == DEPART + timedelta(hours=48)


def test_risk_uses_the_plan_load():
    # At hour 40 wind is ~40.5 mph: High for a light load, Severe above 40,000 lb.
    light = build_heatmap([PATH], DEPART, 30_000, RampWeather())
    heavy = build_heatmap([PATH], DEPART, 45_000, RampWeather())
    assert light["risk"][0][40] == 2
    assert heavy["risk"][0][40] == 3


def test_cells_are_lon_lat():
    result = build_heatmap([PATH], DEPART, 30_000, RampWeather())
    lon, lat = result["cells"][0]
    assert -102 < lon < -99 and 34 < lat < 36


def test_forecast_gaps_become_no_data():
    result = build_heatmap([PATH], DEPART, 30_000, RampWeather(gap_at_hour=10))
    # Hours 9 and 10 after departure both interpolate against the missing 18:00 value.
    assert result["risk"][0][9] == NO_DATA
    assert result["wind_mph"][0][9] is None
    assert result["risk"][0][20] != NO_DATA
