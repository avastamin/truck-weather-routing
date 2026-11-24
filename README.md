# Weather-Aware Truck Routing

Helps a truck driver pick the safest route between two US locations, based on forecast
weather along each route, the truck's load weight and travel time.

The user enters an origin, a destination, a departure time, the load weight (lb) and a sampling
interval (10, 25 or 50 miles). The app gets 3 truck routes, samples the forecast at each
checkpoint for the time the truck is expected to reach it, classifies the weather risk and
recommends a route. The map shows the routes, the checkpoints and a weather heatmap along the
trip corridor with a 0–48 hour slider.

- **Live app:** https://truck-weather-routing-umber.vercel.app
- **API:** https://truck-weather-routing-api-clu3.onrender.com/api/health
- **Walkthrough video:** https://www.loom.com/share/02094f227b1b476d91930e490c429fc7

## Stack

| Part      | Choice                                                                      |
| --------- | --------------------------------------------------------------------------- |
| Backend   | Django 5 + Django REST Framework, Django cache (Redis optional)             |
| Routing   | HERE Routing v8 (truck mode, gross weight, alternatives), behind an adapter |
| Geocoding | HERE Geocoding & Search v7                                                  |
| Weather   | Open-Meteo forecast API (paid key optional)                                 |
| Frontend  | React + TypeScript + Vite, MapLibre GL, deck.gl, TanStack Query             |

## Project layout

```
backend/
  config/                 Django settings and URLs
  api/
    domain/               pure logic, no Django imports
      types.py            Route and GeoPoint data shapes
      geo.py              distance, line simplification, via-point offsets
      risk.py             thresholds and load rules -> risk level per checkpoint
      sampling.py         checkpoints every N miles, miles covered, ETA at each
      hours_of_service.py driver breaks and rests built into the ETAs
      forecast.py         unit conversion, value at an exact time between forecast hours
      recommend.py        miles per risk level, ranking, recommendation reason
    services/
      routing.py          routing provider adapter (HERE) -> Route, 3-route fallback
      weather.py          batched Open-Meteo requests, unit conversion, caching
      planner.py          builds a plan: routes -> checkpoints -> weather -> risk -> ranking
      heatmap.py          weather grid around the routes for 48 hours after departure
    serializers.py        request validation
    views.py              GET /api/health, POST /api/plan, GET /api/heatmap/<plan_id>
  spikes/                 scripts that check the external APIs
  tests/                  pytest
frontend/
  src/
    lib/                  API client and types, formatting, risk colours
    components/           PlanForm, RouteCards, RouteMap, HourSlider
```

## Setup

Requirements: Python 3.11+, Node 20+.

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # requirements.txt alone for production
cp .env.example .env        # then set DJANGO_SECRET_KEY and HERE_API_KEY
python manage.py runserver  # http://127.0.0.1:8000/api/health
```

Environment variables (see `backend/.env.example`):

| Variable               | Purpose                                                        |
| ---------------------- | -------------------------------------------------------------- |
| `DJANGO_DEBUG`         | `true` for local development                                   |
| `DJANGO_SECRET_KEY`    | required when debug is off                                     |
| `DJANGO_ALLOWED_HOSTS` | comma-separated hosts                                          |
| `CORS_ALLOWED_ORIGINS` | frontend origin(s), e.g. `http://localhost:5173`               |
| `REDIS_URL`            | optional; in-memory cache is used if unset                     |
| `ROUTING_PROVIDER`     | `here` (only provider so far)                                  |
| `HERE_API_KEY`         | HERE Platform API key. Backend only, never sent to the browser |
| `OPEN_METEO_API_KEY`   | optional paid Open-Meteo key; the free API is used if unset    |

### Frontend

```bash
cd frontend
npm install
cp .env.example .env        # VITE_API_BASE_URL, defaults to http://127.0.0.1:8000/api
npm run dev                 # http://localhost:5173
```

### Tests

```bash
cd backend
pytest            # tests
ruff check .      # lint
ruff format .     # format

cd frontend
npm run lint
npm run build     # type-checks with tsc, then bundles
```

### API spikes

Run from `backend/` with the virtualenv active:

```bash
python -m spikes.openmeteo_spike   # no key needed
python -m spikes.here_spike        # needs HERE_API_KEY; default trip Dallas, TX -> Denver, CO
```

The HERE spike reports how many routes come back, whether per-segment durations are present,
and whether the load weight changes the routes. Raw responses are saved to
`backend/spikes/output/` (gitignored).

## Deployment

The API runs on Render and the frontend on Vercel, both from this repository.

**API (Render).** `render.yaml` describes the service: in Render choose _New > Blueprint_ and
pick this repository. Then set these environment variables on the service:

- `HERE_API_KEY`
- `CORS_ALLOWED_ORIGINS`: the frontend's URL, e.g. `https://your-app.vercel.app`
- `OPEN_METEO_API_KEY`: recommended. Render's free instances share their outgoing IP address
  with other apps, and Open-Meteo's free limits are per IP, so without a key the hosted app can
  find the daily limit already used up.

`DJANGO_SECRET_KEY` is generated by Render. The service runs gunicorn as a single process with
threads, because plans live in an in-memory cache that the heatmap request reads back. To run
more processes, add Redis and set `REDIS_URL`.

**Frontend (Vercel).** Import the repository, set the root directory to `frontend` (Vite is
detected automatically) and set `VITE_API_BASE_URL` to the API's URL plus `/api`, e.g.
`https://truck-weather-routing-api-clu3.onrender.com/api`.

The hosted API uses Render's Starter instance (0.5 CPU), which stays running. On the free
instance type it also works, but it stops after 15 idle minutes, the next request takes up to
a minute while it starts, and long-trip heatmaps take several times longer. The frontend pings
the API when the page opens to start it early, and says so if planning takes longer than usual.

## API

### `POST /api/plan`

```json
{
  "origin": "Dallas, TX",
  "destination": "Denver, CO",
  "departure": "2026-11-22T08:00:00-06:00",
  "load_lb": 40000,
  "interval_miles": 25
}
```

`departure` must include a timezone offset. `interval_miles` is 10, 25 or 50 (default 25).

The response has the resolved origin and destination, `recommended_route_id`, a `reason`, a
`no_travel_warning` flag, a `plan_id` (used by the heatmap) and up to 3 `routes`. Each route
has its distance, door-to-door and driving time, arrival time, rank, its driver breaks and
rests (`rest_stops`, each with mile, position, arrive and leave times), miles per risk level,
average risk, a simplified
`path` (`[lon, lat]` pairs) and its `checkpoints`. Each checkpoint has its mile, position, ETA,
wind, gusts, rain, snow, risk level and the rule that set it.

### `GET /api/heatmap/<plan_id>`

The forecast on a grid of 0.25° cells covering about 25 km either side of every route, for
hour 0 (the departure time) to hour 48. Plans are kept for 2 hours; after that this returns 404.

```json
{
  "start": "2026-11-22T14:00:00+00:00",
  "hours": 48,
  "cell_size_deg": 0.25,
  "cells": [[-96.75, 32.75], ...],
  "risk": [[0, 0, 1, ...], ...],
  "wind_mph": [[12, 13, 25, ...], ...],
  "gust_mph": [...], "rain_in_hr": [...], "snow_in_hr": [...]
}
```

Each array has one row per cell and one column per hour. `risk` is 0 (Low) to 4 (No Travel)
using the plan's load, or -1 where the forecast has a gap. Very long trips get a coarser grid so
one request stays under 600 locations.

Errors come back as `{"error": "..."}`, plus `"fields"` for invalid input:

| Status | When                                                                           |
| ------ | ------------------------------------------------------------------------------ |
| 400    | invalid input, departure outside the allowed window, place not found, no route |
| 404    | heatmap requested for an unknown or expired plan                               |
| 502    | the routing or weather service failed                                          |

## Risk rules (from the brief)

| Condition    | Low   | Moderate  | High      | Severe    | No Travel |
| ------------ | ----- | --------- | --------- | --------- | --------- |
| Wind (mph)   | <25   | 25–34     | 35–44     | 45–54     | ≥55       |
| Rain (in/hr) | <0.10 | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | >1.00     |
| Snow (in/hr) | <0.5  | 0.5–1.0   | 1.0–2.0   | 2.0–3.0   | >3.0      |

Load rules:

- Wind ≥55 mph → No Travel for any load
- Wind 45–54 mph and load >30,000 lb → No Travel
- Wind 35–44 mph and load >40,000 lb → Severe

Recommendation order: fewest Severe miles, then fewest High miles, then lowest average risk,
then shortest travel time.

## Assumptions and interpretation decisions

Where the brief is ambiguous, the app does the following:

1. **Sampling interval** is chosen by the user: 10, 25 or 50 miles (default 25).
2. **Boundaries**: lower bound inclusive, upper bound exclusive, so 0.25 in/hr rain is High.
   The No Travel column for rain and snow says ">", so exactly 1.00 in/hr rain and exactly
   3.0 in/hr snow are Severe. Wind says "≥55", so 55 mph is No Travel.
3. **Wind** is classified on sustained wind (`wind_speed_10m`). Gusts are shown in the
   checkpoint popup but don't affect the risk level.
4. **Checkpoint risk** is the worst of wind (after load rules), rain and snow.
5. **Checkpoints** are placed at mile 0, N, 2N, … and at the destination, so the weather at
   departure and arrival is always checked. Each checkpoint covers half the gap to each
   neighbour, so the miles covered add up to the route length.
6. **No Travel** isn't in the brief's ranking order. Any route with No Travel miles ranks below
   every route without them (then by fewest No Travel miles), and the UI shows a warning.
7. **Average risk** is mile-weighted, with Low = 0, Moderate = 1, High = 2, Severe = 3,
   No Travel = 4.
8. **Weather at the ETA** is linearly interpolated between the two surrounding forecast hours.
9. The recommendation comes with a plain-language reason, e.g. "0 severe miles vs 34 on Route B".
10. **Routing** uses HERE Routing v8 in truck mode with the load as gross weight. The provider
    sits behind an adapter so another (e.g. Mapbox) can be swapped in.
11. **Rain** is Open-Meteo `rain + showers` (`rain` alone leaves out convective showers).
    Open-Meteo's snowfall unit depends on the request (cm by default), so the app requests
    metric units and converts to in/hr using the units listed in each response, failing loudly
    on an unexpected unit. Hourly values are totals for the preceding hour, so they are used
    directly as per-hour rates.
12. **Heatmap time axis**: hour 0 is the departure time. The slider is labelled with clock time
    and offset, e.g. "Sat 14:00 (+6h)".
13. **Departure window**: from now (with 15 minutes' grace for clock drift) up to 7 days ahead.
    Departure plus the longest route's duration must also fall inside the forecast window,
    otherwise the API returns a clear error.
14. **Rounding before ranking**: risk miles are rounded to 0.1 mi and average risk to 0.01
    before comparing, so near-equal values count as ties and the later tie-breakers apply.
    If routes are still tied after travel time, the routing provider's order decides.
15. **Load weight** must be between 1 and 200,000 lb. That's well above the 80,000 lb federal
    limit, to allow permitted heavy loads.
16. **Place names**: if HERE's best match for a place is weak (match score below 0.7), the app
    asks for a more specific name instead of silently routing from a different town. The
    matched names are shown above the route cards, so an ambiguous name like "Springfield"
    is visible.
17. **Driver breaks and rests** are built into every ETA, using simplified US hours-of-service
    rules: a 30-minute break after 8 hours of driving and a 10-hour rest after 11 hours,
    repeating on multi-day trips. The driver is assumed to start fresh; weekly (60/70-hour)
    limits aren't modelled. Rest time counts toward travel time when ranking routes, so a
    route that needs one more rest can lose to a slightly longer drive. The stops are worked
    out by the app rather than by HERE, because HERE returns only one route when a driver
    schedule is set and the brief asks for three.
18. **Times** are shown in the browser's timezone with the zone name (e.g. "Sat 14:00 CST"), and
    the departure field is read in that same timezone.
19. **Fewer than 3 routes**: if HERE returns fewer than 3, the app tries via points to either
    side of the trip. A result only counts as a new route if less than 70% of it runs on roads
    the existing routes already use; otherwise it's the same road with a detour. Trips with only
    one sensible road (e.g. Key West → Marathon) show a single route and say so.
20. **Heatmap load**: the heatmap's combined risk uses the plan's load weight. The heatmap
    response also includes raw wind, gust, rain and snow values per hour for the popup.

## Known limitations

- **Weather API limits without a key.** Open-Meteo's free tier counts every location in a
  request as one call (600 a minute, 5,000 an hour, 10,000 a day, per IP address). One plan plus
  its heatmap uses about 500, so planning two different trips within the same minute can hit the
  limit, and so can a cross-country trip at 10-mile checkpoints. The app then shows Open-Meteo's
  "try again in a minute" message. Re-planning the same trip (e.g. with a different load) is
  served from the cache. The hosted app uses a paid key (`OPEN_METEO_API_KEY`), which has no
  per-minute, hourly or daily limits.
- **Plans are kept for 2 hours**, in memory. After that, or after the API restarts (for
  example on a deploy), the heatmap for an old plan returns 404 and the trip has to be
  planned again.
- **Hours of service are simplified**: the driver is assumed to start fresh, and weekly
  (60/70-hour) limits and real parking locations for rests aren't modelled.
- **Forecast resolution.** Checkpoint weather comes from a 0.1° grid (about 7 miles) and the
  heatmap from 0.25° cells, so very local conditions such as a single mountain pass can be
  smoothed out.
- **Long trips get a coarser heatmap**: the grid is capped at 600 cells, so cross-country
  corridors use 0.5° cells.
