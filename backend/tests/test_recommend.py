"""Route aggregation, ranking tie-breakers, No Travel ordering and the reason text."""

import pytest

from api.domain.recommend import RouteRisk, aggregate, recommend
from api.domain.risk import RiskLevel

L, M, H, S, NT = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)
HOUR = 3600


def risk(route_id, *, low=0.0, mod=0.0, high=0.0, severe=0.0, nt=0.0, hours=10.0):
    """A RouteRisk with the given miles per level and a 'filler' of low miles to 100 mi."""
    segments = [(M, mod), (H, high), (S, severe), (NT, nt)]
    filler = max(0.0, 100.0 - mod - high - severe - nt) if low == 0 else low
    return aggregate(route_id, [(L, filler), *segments], hours * HOUR)


class TestAggregate:
    def test_miles_per_level_and_total(self):
        r = aggregate("A", [(L, 10), (H, 5), (L, 15), (S, 20)], 7200)
        assert r.miles_by_level[L] == 25
        assert r.miles_by_level[H] == 5
        assert r.miles_by_level[S] == 20
        assert r.miles_by_level[M] == 0
        assert r.miles_by_level[NT] == 0
        assert r.total_miles == 50

    def test_average_risk_is_mile_weighted(self):
        # 30 mi Low (0) + 10 mi High (2) -> 20 / 40 = 0.5
        r = aggregate("A", [(L, 30), (H, 10)], 3600)
        assert r.avg_risk == pytest.approx(0.5)

    def test_no_travel_scores_4(self):
        r = aggregate("A", [(NT, 10)], 3600)
        assert r.avg_risk == 4
        assert r.has_no_travel

    def test_zero_miles_rejected(self):
        with pytest.raises(ValueError):
            aggregate("A", [], 3600)


class TestTieBreakers:
    def test_fewest_severe_miles_wins_even_if_worse_on_everything_else(self):
        a = risk("A", severe=10, hours=8)
        b = risk("B", severe=5, high=60, mod=20, hours=14)
        assert recommend([a, b]).route_id == "B"

    def test_fewest_high_miles_breaks_severe_tie(self):
        a = risk("A", severe=5, high=20, hours=8)
        b = risk("B", severe=5, high=10, mod=50, hours=14)
        assert recommend([a, b]).route_id == "B"

    def test_lowest_average_risk_breaks_severe_and_high_tie(self):
        a = risk("A", severe=5, high=10, mod=40, hours=8)
        b = risk("B", severe=5, high=10, mod=10, hours=14)
        assert recommend([a, b]).route_id == "B"

    def test_shortest_time_breaks_full_risk_tie(self):
        a = risk("A", high=10, hours=12)
        b = risk("B", high=10, hours=11)
        assert recommend([a, b]).route_id == "B"

    def test_complete_tie_keeps_provider_order(self):
        a = risk("A", high=10)
        b = risk("B", high=10)
        assert recommend([a, b]).route_id == "A"
        assert recommend([b, a]).route_id == "B"

    def test_full_ranking_order(self):
        routes = [
            risk("A", severe=10),
            risk("B", severe=0, high=30),
            risk("C", severe=0, high=5),
        ]
        assert recommend(routes).ranking == ["C", "B", "A"]


class TestRounding:
    def test_severe_miles_within_rounding_count_as_tie(self):
        # 10.04 and 10.0 both round to 10.0 -> falls through to high miles.
        a = risk("A", severe=10.04, high=1)
        b = risk("B", severe=10.0, high=5)
        assert recommend([a, b]).route_id == "A"

    def test_average_risk_within_rounding_counts_as_tie(self):
        # avg 0.3351 vs 0.3369 both round to 0.34 -> falls through to travel time.
        a = aggregate("A", [(L, 249), (M, 125.5)], 12 * HOUR)
        b = aggregate("B", [(L, 248), (M, 126)], 11 * HOUR)
        assert round(a.avg_risk, 2) == round(b.avg_risk, 2)
        assert a.avg_risk != b.avg_risk
        assert recommend([a, b]).route_id == "B"


class TestNoTravel:
    def test_any_no_travel_ranks_below_routes_without(self):
        a = risk("A", nt=1)
        b = risk("B", severe=90)
        assert recommend([a, b]).route_id == "B"

    def test_tiny_no_travel_still_ranks_below(self):
        # 0.04 mi rounds to 0.0 but is still No Travel exposure.
        a = risk("A", nt=0.04)
        b = risk("B", severe=50)
        assert recommend([a, b]).route_id == "B"

    def test_among_no_travel_routes_fewer_nt_miles_first(self):
        a = risk("A", nt=20)
        b = risk("B", nt=5, severe=50)
        assert recommend([a, b]).route_id == "B"

    def test_warning_only_when_every_route_has_no_travel(self):
        clean = recommend([risk("A"), risk("B", nt=3)])
        assert not clean.no_travel_warning
        dirty = recommend([risk("A", nt=4), risk("B", nt=3)])
        assert dirty.route_id == "B"
        assert dirty.no_travel_warning


class TestReason:
    def test_severe_reason(self):
        rec = recommend([risk("A", severe=0), risk("B", severe=34)])
        assert rec.reason == "0 severe miles vs 34 on Route B"

    def test_high_reason(self):
        rec = recommend([risk("A", severe=5, high=10), risk("B", severe=5, high=25.5)])
        assert rec.reason == "Same severe miles; 10 high miles vs 25.5 on Route B"

    def test_average_reason(self):
        rec = recommend([risk("A", mod=10), risk("B", mod=40)])
        assert rec.reason == "Same severe and high miles; average risk 0.10 vs 0.40 on Route B"

    def test_time_reason(self):
        rec = recommend([risk("A", hours=10), risk("B", hours=11.25)])
        assert rec.reason == "Same weather risk; 1 h 15 min faster than Route B"

    def test_no_travel_reason(self):
        rec = recommend([risk("A", severe=40), risk("B", nt=12)])
        assert rec.reason == "0 No Travel miles vs 12 on Route B"

    def test_tiny_no_travel_is_not_shown_as_zero(self):
        rec = recommend([risk("A", severe=40), risk("B", nt=0.04)])
        assert rec.reason == "0 No Travel miles vs <0.1 on Route B"

    def test_reason_compares_against_runner_up(self):
        rec = recommend([risk("A", severe=50), risk("B", severe=0), risk("C", severe=20)])
        assert rec.route_id == "B"
        assert rec.reason == "0 severe miles vs 20 on Route C"

    def test_full_tie_reason(self):
        rec = recommend([risk("A"), risk("B")])
        assert rec.reason == "Same risk and travel time as Route B; first route returned"

    def test_single_route(self):
        rec = recommend([risk("A")])
        assert rec.route_id == "A"
        assert rec.reason == "Only route available"


def test_empty_input_rejected():
    with pytest.raises(ValueError):
        recommend([])


def test_route_risk_is_a_value_object():
    r = risk("A")
    assert isinstance(r, RouteRisk)
    with pytest.raises(AttributeError):
        r.route_id = "Z"
