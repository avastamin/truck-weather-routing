"""Quick check of the Open-Meteo response shape, units and batching. No API key needed.

Run from backend/:

    python -m spikes.openmeteo_spike

Checks the facts that sampling, weather and heatmap code depend on:
- several locations come back as a JSON list in input order (one location as an object)
- metric request -> rain/showers in mm, snowfall in cm
- hourly series starts at 00:00 UTC today; forecast_days capped at 16
- how long a large batched request (heatmap-sized) takes
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime

import requests

URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"

# Rough points along Dallas -> Amarillo -> Denver.
CORRIDOR = [(32.78, -96.80), (33.91, -98.49), (35.22, -101.83), (36.40, -103.20), (39.74, -104.99)]


def fetch(points, forecast_days=9):
    params = {
        "latitude": ",".join(f"{lat:.2f}" for lat, _ in points),
        "longitude": ",".join(f"{lon:.2f}" for _, lon in points),
        "hourly": HOURLY,
        "wind_speed_unit": "mph",
        "timezone": "UTC",
        "timeformat": "unixtime",
        "forecast_days": forecast_days,
    }
    t0 = time.perf_counter()
    resp = requests.get(URL, params=params, timeout=60)
    return resp, time.perf_counter() - t0


def main() -> int:
    resp, elapsed = fetch(CORRIDOR)
    resp.raise_for_status()
    data = resp.json()
    data = data if isinstance(data, list) else [data]
    print(
        f"{len(CORRIDOR)} points -> {type(resp.json()).__name__} of {len(data)} in {elapsed:.2f}s"
    )
    print("hourly_units:", data[0]["hourly_units"])
    t = data[0]["hourly"]["time"]
    print(
        f"hours: {len(t)}  first: {datetime.fromtimestamp(t[0], UTC).isoformat()}  "
        f"last: {datetime.fromtimestamp(t[-1], UTC).isoformat()}"
    )
    for (lat, lon), loc in zip(CORRIDOR, data, strict=True):
        h = loc["hourly"]
        peak = {k: max((v or 0) for v in h[k]) for k in HOURLY.split(",")}
        print(
            f"  ({lat:6.2f},{lon:8.2f}) -> grid "
            f"({loc['latitude']:.3f},{loc['longitude']:.3f})  peaks {peak}"
        )

    # forecast_days limit
    resp, _ = fetch(CORRIDOR[:1], forecast_days=17)
    print(f"\nforecast_days=17 -> HTTP {resp.status_code}: {resp.text[:120]}")

    # Heatmap-sized batch: 20 x 20 grid at 0.25 deg spacing over the corridor.
    grid = [(32.5 + 0.375 * i, -105.0 + 0.45 * j) for i in range(20) for j in range(20)]
    resp, elapsed = fetch(grid, forecast_days=3)
    print(
        f"\n{len(grid)}-point grid, 3 days -> HTTP {resp.status_code} in {elapsed:.2f}s, "
        f"{len(resp.content) / 1e6:.2f} MB"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
