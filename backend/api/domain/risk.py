"""Weather risk classification.

Each band includes its lower bound and excludes its upper bound. The exception is No Travel for
rain and snow, which only starts above 1.00 in/hr and 3.0 in/hr respectively.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum

# Inputs are rounded to this many decimals before comparing, so float noise from unit
# conversion or interpolation (e.g. 0.09999999 in/hr) doesn't drop a value below a boundary.
_PRECISION = 6

# (lower bound of Moderate, High, Severe) for each factor.
WIND_BANDS_MPH = (25.0, 35.0, 45.0)
WIND_NO_TRAVEL_MPH = 55.0  # >= 55
RAIN_BANDS_IN_HR = (0.10, 0.25, 0.50)
RAIN_NO_TRAVEL_IN_HR = 1.00  # > 1.00
SNOW_BANDS_IN_HR = (0.5, 1.0, 2.0)
SNOW_NO_TRAVEL_IN_HR = 3.0  # > 3.0

# Load rules
NO_TRAVEL_WIND_LOAD_LB = 30_000  # wind 45-54 mph and load > 30,000 lb -> No Travel
SEVERE_WIND_LOAD_LB = 40_000  # wind 35-44 mph and load > 40,000 lb -> Severe


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def score(self) -> int:
        """Weight used for the mile-weighted average risk."""
        return int(self)

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").title()


@dataclass(frozen=True)
class Assessment:
    level: RiskLevel
    triggered_by: tuple[
        str, ...
    ]  # factors at the worst level ("wind", "rain", "snow"); empty if Low
    reasons: tuple[str, ...]  # one human-readable sentence per triggering factor


def _clean(value: float, name: str) -> float:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite, non-negative number (got {value})")
    return round(value, _PRECISION)


def _band(value: float, bands: tuple[float, float, float]) -> RiskLevel:
    moderate, high, severe = bands
    if value >= severe:
        return RiskLevel.SEVERE
    if value >= high:
        return RiskLevel.HIGH
    if value >= moderate:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def _wind_with_rule(mph: float, load_lb: float) -> tuple[RiskLevel, str | None]:
    """Wind level after load rules, plus the load rule that applied (if any)."""
    if mph >= WIND_NO_TRAVEL_MPH:
        return RiskLevel.NO_TRAVEL, None
    base = _band(mph, WIND_BANDS_MPH)
    if base == RiskLevel.SEVERE and load_lb > NO_TRAVEL_WIND_LOAD_LB:
        return RiskLevel.NO_TRAVEL, f"load over {NO_TRAVEL_WIND_LOAD_LB:,} lb"
    if base == RiskLevel.HIGH and load_lb > SEVERE_WIND_LOAD_LB:
        return RiskLevel.SEVERE, f"load over {SEVERE_WIND_LOAD_LB:,} lb"
    return base, None


def classify_wind(mph: float, load_lb: float) -> RiskLevel:
    return _wind_with_rule(_clean(mph, "wind"), _clean(load_lb, "load"))[0]


def classify_rain(in_hr: float) -> RiskLevel:
    value = _clean(in_hr, "rain")
    if value > RAIN_NO_TRAVEL_IN_HR:
        return RiskLevel.NO_TRAVEL
    return _band(value, RAIN_BANDS_IN_HR)


def classify_snow(in_hr: float) -> RiskLevel:
    value = _clean(in_hr, "snow")
    if value > SNOW_NO_TRAVEL_IN_HR:
        return RiskLevel.NO_TRAVEL
    return _band(value, SNOW_BANDS_IN_HR)


def _num(value: float, decimals: int) -> str:
    """Format without trailing zeros: 50.0 -> '50', 0.30 -> '0.3'."""
    return f"{round(value, decimals):g}"


def assess(*, wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_lb: float) -> Assessment:
    """Checkpoint risk is the worst of wind (after load rules), rain and snow."""
    wind = _clean(wind_mph, "wind")
    rain = _clean(rain_in_hr, "rain")
    snow = _clean(snow_in_hr, "snow")
    load = _clean(load_lb, "load")

    wind_level, load_rule = _wind_with_rule(wind, load)
    wind_text = f"Wind {_num(wind, 1)} mph" + (f" with {load_rule}" if load_rule else "")
    factors = [
        ("wind", wind_level, wind_text),
        ("rain", classify_rain(rain), f"Rain {_num(rain, 2)} in/hr"),
        ("snow", classify_snow(snow), f"Snow {_num(snow, 2)} in/hr"),
    ]
    level = max(lvl for _, lvl, _ in factors)
    if level == RiskLevel.LOW:
        return Assessment(level=level, triggered_by=(), reasons=())
    hits = [(name, f"{text}: {lvl.label}") for name, lvl, text in factors if lvl == level]
    return Assessment(
        level=level,
        triggered_by=tuple(name for name, _ in hits),
        reasons=tuple(reason for _, reason in hits),
    )
