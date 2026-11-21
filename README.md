# Weather-Aware Truck Routing

Helps a truck driver pick the safest route between two US locations, based on forecast
weather along each route, the truck's load weight and travel time.

The user enters an origin, a destination, a departure time, the load weight (lb) and a sampling
interval (10, 25 or 50 miles). The app gets 3 truck routes, samples the forecast at each
checkpoint for the time the truck is expected to reach it, classifies the weather risk and
recommends a route. The map shows the routes, the checkpoints and a weather heatmap along the
trip corridor with a 0–48 hour slider.

> **Status: early scaffold.** The backend and frontend projects are set up, the routing adapter
> (HERE) is written, and spikes against HERE and Open-Meteo are in place. Next: the risk,
> sampling and recommendation logic, then the API endpoints, the map UI and the heatmap.

## Stack

| Part      | Choice                                                            |
| --------- | ----------------------------------------------------------------- |
| Backend   | Django 5 + Django REST Framework, Django cache (Redis optional)   |
| Routing   | HERE Routing v8 (truck mode, gross weight, alternatives), behind an adapter |
| Geocoding | HERE Geocoding & Search v7                                        |
| Weather   | Open-Meteo forecast API (no key)                                  |
| Frontend  | React + TypeScript + Vite, MapLibre GL, deck.gl, TanStack Query  |

## Project layout

```
backend/
  config/                 Django settings and URLs
  api/
    domain/               pure logic, no Django imports
      types.py            Route and GeoPoint data shapes
      geo.py              distance helpers
    services/
      routing.py          routing provider adapter (HERE) -> Route
    views.py              API endpoints (currently GET /api/health)
  spikes/                 scripts that check the external APIs
  tests/                  pytest
frontend/                 Vite + React + TypeScript app
```

## Setup

Requirements: Python 3.11+, Node 20+.

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set DJANGO_SECRET_KEY and HERE_API_KEY
python manage.py runserver  # http://localhost:8000/api/health
```

Environment variables (see `backend/.env.example`):

| Variable               | Purpose                                                  |
| ---------------------- | -------------------------------------------------------- |
| `DJANGO_DEBUG`         | `true` for local development                             |
| `DJANGO_SECRET_KEY`    | required when debug is off                               |
| `DJANGO_ALLOWED_HOSTS` | comma-separated hosts                                    |
| `CORS_ALLOWED_ORIGINS` | frontend origin(s), e.g. `http://localhost:5173`         |
| `REDIS_URL`            | optional; in-memory cache is used if unset               |
| `ROUTING_PROVIDER`     | `here` (only provider so far)                            |
| `HERE_API_KEY`         | HERE Platform API key. Backend only, never sent to the browser |

### Frontend

```bash
cd frontend
npm install
cp .env.example .env        # VITE_API_BASE_URL, defaults to http://localhost:8000/api
npm run dev                 # http://localhost:5173
```

### Tests

```bash
cd backend && pytest
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
5. **Miles per checkpoint**: each checkpoint covers half the gap to each neighbour; the first
   and last checkpoints also cover the stretch to the route's start and end.
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
15. **Heatmap load**: the heatmap's combined risk uses the plan's load weight. The heatmap
    response also includes raw wind, gust, rain and snow values per hour for the popup.
