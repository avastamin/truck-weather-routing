import { useCallback, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ApiError, createPlan, fetchHeatmap, type Heatmap, type Plan, type PlanInput } from './lib/api'
import { HourSlider } from './components/HourSlider'
import { LoadingNotice } from './components/LoadingNotice'
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

  const heatmapQuery = useQuery<Heatmap, ApiError>({
    queryKey: ['heatmap', plan?.plan_id],
    queryFn: () => fetchHeatmap(plan!.plan_id),
    enabled: Boolean(plan) && !mutation.isPending,
    staleTime: Infinity,
    retry: 1,
  })

  // The hour belongs to a plan, so a new plan starts back at departure.
  const [hourState, setHourState] = useState({ planId: '', hour: 0 })
  const hour = plan && hourState.planId === plan.plan_id ? hourState.hour : 0
  const setHour = useCallback(
    (h: number) => plan && setHourState({ planId: plan.plan_id, hour: h }),
    [plan],
  )

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
        <RouteMap
          plan={mutation.isPending ? undefined : plan}
          heatmap={heatmapQuery.data}
          hour={hour}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        {plan && !mutation.isPending && (
          <HourSlider
            start={plan.departure}
            hours={heatmapQuery.data?.hours ?? 48}
            hour={hour}
            onChange={setHour}
            status={heatmapQuery.isError ? 'error' : heatmapQuery.data ? 'ready' : 'loading'}
            error={heatmapQuery.error?.message}
          />
        )}
        {mutation.isPending && <LoadingNotice />}
        <div className="legend" aria-label="Risk levels">
          {RISK_LEVELS.map((level) => (
            <span key={level}>
              <span className="swatch" style={{ background: riskCss(level) }} />
              {RISK_LABEL[level]}
            </span>
          ))}
          <span>
            <span className="swatch stop-swatch" />
            Break / rest
          </span>
        </div>
      </main>
    </div>
  )
}
