"""Unit conversion (incl. snowfall cm -> in) and interpolation between forecast hours."""

import pytest

from api.domain.forecast import ForecastRangeError, interpolate_at, to_inches

H = 3600
T0 = 1_795_219_200  # 2026-11-21T00:00Z


class TestToInches:
    def test_snowfall_cm_to_inches(self):
        assert to_inches(2.54, "cm") == pytest.approx(1.0)
        assert to_inches(7.62, "cm") == pytest.approx(3.0)

    def test_rain_mm_to_inches(self):
        assert to_inches(25.4, "mm") == pytest.approx(1.0)
        assert to_inches(6.35, "mm") == pytest.approx(0.25)

    def test_inches_pass_through(self):
        assert to_inches(0.5, "inch") == 0.5

    def test_unknown_unit_fails_loudly(self):
        with pytest.raises(ValueError, match="unit"):
            to_inches(1.0, "kg/m²")


class TestInterpolateAt:
    TIMES = [T0, T0 + H, T0 + 2 * H]
    VALUES = [10.0, 20.0, 0.0]

    def test_exact_hour_returns_value(self):
        assert interpolate_at(self.TIMES, self.VALUES, T0 + H) == 20.0

    def test_linear_between_hours(self):
        assert interpolate_at(self.TIMES, self.VALUES, T0 + H / 4) == pytest.approx(12.5)
        assert interpolate_at(self.TIMES, self.VALUES, T0 + 1.5 * H) == pytest.approx(10.0)

    def test_first_and_last_hour_inclusive(self):
        assert interpolate_at(self.TIMES, self.VALUES, T0) == 10.0
        assert interpolate_at(self.TIMES, self.VALUES, T0 + 2 * H) == 0.0

    def test_outside_forecast_window_raises(self):
        with pytest.raises(ForecastRangeError):
            interpolate_at(self.TIMES, self.VALUES, T0 - 1)
        with pytest.raises(ForecastRangeError):
            interpolate_at(self.TIMES, self.VALUES, T0 + 2 * H + 1)

    def test_missing_value_raises(self):
        with pytest.raises(ForecastRangeError):
            interpolate_at(self.TIMES, [10.0, None, 0.0], T0 + 0.5 * H)
