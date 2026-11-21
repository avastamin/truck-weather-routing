"""Quick check of HERE Routing v8 truck routes on a long US trip.

Run from backend/ once HERE_API_KEY is set in backend/.env:

    python -m spikes.here_spike
    python -m spikes.here_spike "Chicago, IL" "Salt Lake City, UT" --load 45000

Checks: route count (>= 3?), spans present with durations, cumulative arrays monotonic and
matching the section summaries, and load sensitivity (light vs heavy grossWeight).
Raw responses are saved to spikes/output/ (gitignored) for reference.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from api.services.routing import HereRoutingProvider, RoutingError, parse_here_routes

BACKEND = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "output"


def summarize(label: str, raw: dict) -> None:
    routes = parse_here_routes(raw)
    print(f"\n== {label}: {len(routes)} route(s) ==")
    if len(routes) < 3:
        print("  !! fewer than 3 routes -> perpendicular via-point fallback needed")
    for raw_route, route in zip(raw["routes"], routes):
        sections = raw_route["sections"]
        spans = sum(len(s.get("spans") or []) for s in sections)
        spans_ok = all(
            (s.get("spans") or [{}])[0].get("duration") is not None for s in sections
        )
        summary_s = sum(s["summary"]["duration"] for s in sections)
        summary_m = sum(s["summary"]["length"] for s in sections)
        monotonic = all(b >= a for a, b in zip(route.cum_seconds, route.cum_seconds[1:]))
        print(
            f"  Route {route.id}: {route.distance_miles:7.1f} mi  "
            f"{route.duration_seconds / 3600:5.2f} h  "
            f"vertices={len(route.coords)}  sections={len(sections)}  spans={spans} "
            f"(durations {'yes' if spans_ok else 'NO'})  monotonic={monotonic}  "
            f"summary={summary_m / 1609.344:.1f} mi/{summary_s / 3600:.2f} h"
        )
    for notice in raw.get("notices") or []:
        print(f"  notice: {notice}")


def main() -> int:
    load_dotenv(BACKEND / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("origin", nargs="?", default="Dallas, TX")
    parser.add_argument("destination", nargs="?", default="Denver, CO")
    parser.add_argument("--load", type=float, default=45000, help="heavy load in lb")
    args = parser.parse_args()

    key = os.environ.get("HERE_API_KEY", "")
    if not key:
        print("HERE_API_KEY is not set in backend/.env; add it and re-run.")
        return 1

    provider = HereRoutingProvider(key)
    departure = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)
    try:
        origin = provider.geocode(args.origin)
        destination = provider.geocode(args.destination)
        print(f"origin:      {origin}")
        print(f"destination: {destination}")
        print(f"departure:   {departure.isoformat()}")

        OUT.mkdir(exist_ok=True)
        for label, load in (("light 10,000 lb", 10000), (f"heavy {args.load:,.0f} lb", args.load)):
            raw = provider.fetch_routes_raw(origin, destination, departure, load)
            (OUT / f"here_routes_{int(load)}.json").write_text(json.dumps(raw, indent=2))
            summarize(label, raw)
    except RoutingError as exc:
        print(f"RoutingError: {exc}")
        return 1
    print(f"\nRaw responses saved in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
