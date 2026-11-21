"""Risk classification: every threshold boundary, load rules, and the combined checkpoint level."""

import math

import pytest

from api.domain.risk import (
    RiskLevel,
    assess,
    classify_rain,
    classify_snow,
    classify_wind,
)

L, M, H, S, NT = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)
LIGHT = 10_000  # lb, below every load rule


@pytest.mark.parametrize(
    "mph, expected",
    [
        (0, L),
        (24.9, L),
        (25, M),
        (34.9, M),
        (35, H),
        (44.9, H),
        (45, S),
        (54.9, S),
        (55, NT),
        (80, NT),
    ],
)
def test_wind_thresholds_light_load(mph, expected):
    assert classify_wind(mph, LIGHT) == expected


@pytest.mark.parametrize(
    "in_hr, expected",
    [
        (0, L),
        (0.099, L),
        (0.10, M),
        (0.249, M),
        (0.25, H),
        (0.499, H),
        (0.50, S),
        (1.00, S),  # "0.50–1.00" is Severe; No Travel is strictly "> 1.00"
        (1.001, NT),
        (2.5, NT),
    ],
)
def test_rain_thresholds(in_hr, expected):
    assert classify_rain(in_hr) == expected


@pytest.mark.parametrize(
    "in_hr, expected",
    [
        (0, L),
        (0.49, L),
        (0.5, M),
        (0.99, M),
        (1.0, H),
        (1.99, H),
        (2.0, S),
        (3.0, S),  # No Travel is strictly "> 3.0"
        (3.01, NT),
        (6, NT),
    ],
)
def test_snow_thresholds(in_hr, expected):
    assert classify_snow(in_hr) == expected


class TestLoadRules:
    def test_wind_55_is_no_travel_for_any_load(self):
        for load in (0, 5_000, 30_000, 80_000):
            assert classify_wind(55, load) == NT

    def test_wind_54_heavy_is_no_travel_but_light_is_severe(self):
        assert classify_wind(54, 30_001) == NT
        assert classify_wind(54, 30_000) == S

    def test_wind_45_threshold_for_30k_rule(self):
        assert classify_wind(45, 30_001) == NT
        assert classify_wind(44.9, 30_001) == H  # 35-44 band: 30,001 lb is under the 40k rule

    def test_wind_35_to_44_with_load_over_40k_is_severe(self):
        assert classify_wind(44, 40_001) == S
        assert classify_wind(44, 40_000) == H
        assert classify_wind(35, 40_001) == S

    def test_wind_below_35_is_not_affected_by_load(self):
        assert classify_wind(34.9, 80_000) == M
        assert classify_wind(24.9, 80_000) == L

    def test_45_to_54_band_with_40k_plus_load_is_no_travel(self):
        # The >30,000 lb rule applies; the 40k rule only concerns the 35-44 band.
        assert classify_wind(50, 45_000) == NT


class TestAssess:
    def test_all_calm_is_low_with_no_triggers(self):
        result = assess(wind_mph=5, rain_in_hr=0, snow_in_hr=0, load_lb=LIGHT)
        assert result.level == L
        assert result.triggered_by == ()

    def test_worst_factor_wins(self):
        result = assess(wind_mph=30, rain_in_hr=0.3, snow_in_hr=0, load_lb=LIGHT)
        assert result.level == H
        assert result.triggered_by == ("rain",)

    def test_ties_list_every_triggering_factor(self):
        result = assess(wind_mph=47, rain_in_hr=0.6, snow_in_hr=2.5, load_lb=LIGHT)
        assert result.level == S
        assert result.triggered_by == ("wind", "rain", "snow")

    def test_load_rule_raises_wind_above_precip(self):
        result = assess(wind_mph=40, rain_in_hr=0.3, snow_in_hr=0, load_lb=45_000)
        assert result.level == S
        assert result.triggered_by == ("wind",)
        assert "load" in result.reasons[0].lower()

    def test_reasons_are_human_readable(self):
        result = assess(wind_mph=50, rain_in_hr=0, snow_in_hr=0, load_lb=35_000)
        assert result.level == NT
        assert result.reasons == ("Wind 50 mph with load over 30,000 lb: No Travel",)

    def test_float_noise_at_boundary_does_not_drop_a_level(self):
        # 2.54 mm converted to inches can land a hair under 0.10.
        assert classify_rain(2.54 / 25.4 - 1e-12) == M

    @pytest.mark.parametrize("bad", [-0.1, math.nan, math.inf])
    def test_invalid_inputs_raise(self, bad):
        with pytest.raises(ValueError):
            assess(wind_mph=bad, rain_in_hr=0, snow_in_hr=0, load_lb=LIGHT)
        with pytest.raises(ValueError):
            assess(wind_mph=0, rain_in_hr=bad, snow_in_hr=0, load_lb=LIGHT)
        with pytest.raises(ValueError):
            assess(wind_mph=0, rain_in_hr=0, snow_in_hr=0, load_lb=bad)


def test_level_score_and_label():
    assert [lvl.score for lvl in RiskLevel] == [0, 1, 2, 3, 4]
    assert NT.label == "No Travel"
    assert M.label == "Moderate"
