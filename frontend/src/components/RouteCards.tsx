import type { Plan, PlannedRoute } from '../lib/api'
import { describeStops, formatDuration, formatMiles, formatTime } from '../lib/format'
import { RISK_LABEL, RISK_LEVELS, riskCss } from '../lib/risk'

interface Props {
  plan: Plan
  selectedId: string
  onSelect: (id: string) => void
}

export function RouteCards({ plan, selectedId, onSelect }: Props) {
  const routes = [...plan.routes].sort((a, b) => a.rank - b.rank)
  return (
    <div className="route-cards">
      {/* Show what the geocoder matched, so an ambiguous name like "Springfield" is visible. */}
      <p className="trip-summary">
        {plan.origin.label} → {plan.destination.label}
      </p>
      {routes.length < 3 && (
        <p className="route-note">
          Only {routes.length === 1 ? 'one route' : `${routes.length} distinct routes`} found for
          this trip.
        </p>
      )}
      {plan.no_travel_warning && (
        <div className="banner banner-danger" role="alert">
          Every route has stretches rated No Travel at the expected arrival time. Consider a
          different departure time.
        </div>
      )}
      {routes.map((route) => (
        <RouteCard
          key={route.id}
          route={route}
          recommended={route.id === plan.recommended_route_id}
          reason={plan.reason}
          selected={route.id === selectedId}
          onSelect={() => onSelect(route.id)}
        />
      ))}
    </div>
  )
}

interface CardProps {
  route: PlannedRoute
  recommended: boolean
  reason: string
  selected: boolean
  onSelect: () => void
}

function RouteCard({ route, recommended, reason, selected, onSelect }: CardProps) {
  const total = route.distance_miles || 1
  return (
    <button
      type="button"
      className={`route-card${selected ? ' selected' : ''}`}
      onClick={onSelect}
      aria-pressed={selected}
    >
      <div className="route-card-header">
        <span className="route-name">Route {route.id}</span>
        {recommended && <span className="badge badge-recommended">Recommended</span>}
        {route.has_no_travel && <span className="badge badge-danger">No Travel</span>}
      </div>
      {recommended && <p className="route-reason">{reason}</p>}
      <div className="route-stats">
        <span>{formatDuration(route.duration_seconds)}</span>
        <span>{formatMiles(route.distance_miles)}</span>
        <span>Arrive {formatTime(route.arrival)}</span>
      </div>
      {route.rest_stops.length > 0 && (
        <div className="route-stops">
          {formatDuration(route.driving_seconds)} driving + {describeStops(route.rest_stops)}
        </div>
      )}
      <div className="risk-bar" aria-hidden="true">
        {RISK_LEVELS.map((level) =>
          route.miles_by_level[level] > 0 ? (
            <span
              key={level}
              style={{
                width: `${(route.miles_by_level[level] / total) * 100}%`,
                background: riskCss(level),
              }}
            />
          ) : null,
        )}
      </div>
      <ul className="risk-miles">
        {RISK_LEVELS.map((level) => (
          <li key={level} className={route.miles_by_level[level] > 0 ? '' : 'zero'}>
            <span className="swatch" style={{ background: riskCss(level) }} />
            {RISK_LABEL[level]} <strong>{Math.round(route.miles_by_level[level])}</strong> mi
          </li>
        ))}
      </ul>
      <div className="route-avg">Average risk {route.avg_risk.toFixed(2)} / 4</div>
    </button>
  )
}
