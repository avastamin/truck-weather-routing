"""Route risk totals, ranking and the recommendation reason.

Ranking order:
  1. Routes with no No Travel miles, then fewest No Travel miles
  2. Fewest Severe miles
  3. Fewest High miles
  4. Lowest average risk
  5. Shortest travel time
  6. Order the routing provider returned them in
Miles are compared rounded to 0.1 mi and average risk to 0.01.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from api.domain.risk import RiskLevel

MILES_DECIMALS = 1
AVG_RISK_DECIMALS = 2


@dataclass(frozen=True)
class RouteRisk:
    route_id: str
    miles_by_level: Mapping[RiskLevel, float]
    duration_seconds: float
    total_miles: float = field(init=False)
    avg_risk: float = field(init=False)

    def __post_init__(self) -> None:
        total = sum(self.miles_by_level.values())
        if total <= 0:
            raise ValueError("route must cover a positive number of miles")
        weighted = sum(level.score * miles for level, miles in self.miles_by_level.items())
        object.__setattr__(self, "total_miles", total)
        object.__setattr__(self, "avg_risk", weighted / total)

    @property
    def has_no_travel(self) -> bool:
        return self.miles_by_level[RiskLevel.NO_TRAVEL] > 0


@dataclass(frozen=True)
class Recommendation:
    route_id: str
    ranking: list[str]  # route ids, best first
    reason: str
    no_travel_warning: bool  # True when even the recommended route has No Travel miles


def aggregate(
    route_id: str, segments: Iterable[tuple[RiskLevel, float]], duration_seconds: float
) -> RouteRisk:
    """Sum (level, miles) pairs, e.g. one per checkpoint, into a RouteRisk."""
    miles = {level: 0.0 for level in RiskLevel}
    for level, covered in segments:
        miles[level] += covered
    return RouteRisk(route_id, MappingProxyType(miles), duration_seconds)


def _miles(r: RouteRisk, level: RiskLevel) -> float:
    return round(r.miles_by_level[level], MILES_DECIMALS)


def _rank_key(r: RouteRisk) -> tuple:
    return (
        r.has_no_travel,
        _miles(r, RiskLevel.NO_TRAVEL),
        _miles(r, RiskLevel.SEVERE),
        _miles(r, RiskLevel.HIGH),
        round(r.avg_risk, AVG_RISK_DECIMALS),
        r.duration_seconds,
    )


def recommend(routes: list[RouteRisk]) -> Recommendation:
    if not routes:
        raise ValueError("need at least one route")
    ranked = sorted(routes, key=_rank_key)  # stable: equal keys keep provider order
    best = ranked[0]
    return Recommendation(
        route_id=best.route_id,
        ranking=[r.route_id for r in ranked],
        reason=_reason(best, ranked[1]) if len(ranked) > 1 else "Only route available",
        no_travel_warning=best.has_no_travel,
    )


def _fmt_miles(value: float) -> str:
    rounded = round(value, MILES_DECIMALS)
    if value > 0 and rounded == 0:
        return "<0.1"
    return f"{rounded:g}"


def _fmt_duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} h {minutes} min"
    return f"{hours} h" if hours else f"{minutes} min"


def _reason(best: RouteRisk, other: RouteRisk) -> str:
    """Explain the first ranking criterion on which the best route beats the runner-up."""
    vs = f"Route {other.route_id}"

    def miles_vs(level: RiskLevel, name: str) -> str:
        best_m = _fmt_miles(best.miles_by_level[level])
        other_m = _fmt_miles(other.miles_by_level[level])
        return f"{best_m} {name} miles vs {other_m} on {vs}"

    nt, sev, high = RiskLevel.NO_TRAVEL, RiskLevel.SEVERE, RiskLevel.HIGH
    if _miles(best, nt) != _miles(other, nt) or best.has_no_travel != other.has_no_travel:
        return miles_vs(nt, "No Travel")
    if _miles(best, sev) != _miles(other, sev):
        return miles_vs(sev, "severe")
    if _miles(best, high) != _miles(other, high):
        return f"Same severe miles; {miles_vs(high, 'high')}"
    best_avg = round(best.avg_risk, AVG_RISK_DECIMALS)
    other_avg = round(other.avg_risk, AVG_RISK_DECIMALS)
    if best_avg != other_avg:
        return f"Same severe and high miles; average risk {best_avg:.2f} vs {other_avg:.2f} on {vs}"
    saved = other.duration_seconds - best.duration_seconds
    if round(saved / 60) >= 1:
        return f"Same weather risk; {_fmt_duration(saved)} faster than {vs}"
    return f"Same risk and travel time as {vs}; first route returned"
