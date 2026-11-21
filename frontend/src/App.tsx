import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ApiError, createPlan, type Plan, type PlanInput } from './lib/api'
import { PlanForm } from './components/PlanForm'
import { RouteCards } from './components/RouteCards'
import { RouteMap } from './components/RouteMap'
import { RISK_LABEL, RISK_LEVELS, riskCss } from './lib/risk'

export default function App() {
  const [selectedId, setSelectedId] = useState('')
  const mutation = useMutation<Plan, ApiError, PlanInput>({
    mutationFn: createPlan,
    onSuccess: (plan) => setSelectedId(plan.recommended_route_id),
  })
  const plan = mutation.data

  return (
    <div className="layout">
      <aside className="sidebar">
        <header>
          <h1>Weather-Aware Truck Routing</h1>
          <p className="subtitle">Compare routes by forecast weather at your arrival time.</p>
        </header>
        <PlanForm
          onSubmit={(input) => mutation.mutate(input)}
          loading={mutation.isPending}
          fieldErrors={mutation.error?.fields}
        />
        {mutation.isError && !mutation.error.fields && (
          <div className="banner banner-danger" role="alert">
            {mutation.error.message}
          </div>
        )}
        {plan && !mutation.isPending && (
          <RouteCards plan={plan} selectedId={selectedId} onSelect={setSelectedId} />
        )}
      </aside>
      <main className="map-area">
        <RouteMap plan={plan} selectedId={selectedId} onSelect={setSelectedId} />
        {mutation.isPending && (
          <div className="map-loading" role="status">
            <span className="spinner" /> Fetching routes and forecasts…
          </div>
        )}
        <div className="legend" aria-label="Risk levels">
          {RISK_LEVELS.map((level) => (
            <span key={level}>
              <span className="swatch" style={{ background: riskCss(level) }} />
              {RISK_LABEL[level]}
            </span>
          ))}
        </div>
      </main>
    </div>
  )
}
