export type RiskLevel = 'low' | 'moderate' | 'high' | 'severe' | 'no_travel'

export interface Place {
  lat: number
  lon: number
  label: string
}

export interface Checkpoint {
  mile: number
  lat: number
  lon: number
  eta: string
  covers_miles: number
  wind_mph: number
  gust_mph: number | null
  rain_in_hr: number
  snow_in_hr: number
  level: RiskLevel
  triggered_by: string[]
  reasons: string[]
}

export interface PlannedRoute {
  id: string
  rank: number
  distance_miles: number
  duration_seconds: number
  arrival: string
  miles_by_level: Record<RiskLevel, number>
  avg_risk: number
  has_no_travel: boolean
  path: [number, number][] // [lon, lat]
  checkpoints: Checkpoint[]
}

export interface Plan {
  plan_id: string
  origin: Place
  destination: Place
  departure: string
  load_lb: number
  interval_miles: number
  recommended_route_id: string
  reason: string
  no_travel_warning: boolean
  routes: PlannedRoute[]
}

export interface PlanInput {
  origin: string
  destination: string
  departure: string // ISO 8601 with offset
  load_lb: number
  interval_miles: 10 | 25 | 50
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api'

export class ApiError extends Error {
  fields?: Record<string, string[]>

  constructor(message: string, fields?: Record<string, string[]>) {
    super(message)
    this.fields = fields
  }
}

export async function createPlan(input: PlanInput): Promise<Plan> {
  let resp: Response
  try {
    resp = await fetch(`${API_BASE}/plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })
  } catch {
    throw new ApiError('Could not reach the server. Check your connection and try again.')
  }
  const body = await resp.json().catch(() => null)
  if (!resp.ok) {
    throw new ApiError(body?.error ?? `Request failed (HTTP ${resp.status}).`, body?.fields)
  }
  return body as Plan
}
