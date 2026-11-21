import { useState, type FormEvent } from 'react'
import type { PlanInput } from '../lib/api'
import { localZoneName, toLocalInputValue } from '../lib/format'

interface Props {
  onSubmit: (input: PlanInput) => void
  loading: boolean
  fieldErrors?: Record<string, string[]>
}

const MAX_DAYS_AHEAD = 7
const ZONE = localZoneName()

function nextFullHour(): Date {
  const d = new Date()
  d.setHours(d.getHours() + 1, 0, 0, 0)
  return d
}

export function PlanForm({ onSubmit, loading, fieldErrors }: Props) {
  const [origin, setOrigin] = useState('Dallas, TX')
  const [destination, setDestination] = useState('Denver, CO')
  const [departure, setDeparture] = useState(() => toLocalInputValue(nextFullHour()))
  const [load, setLoad] = useState('40000')
  const [interval, setInterval] = useState<PlanInput['interval_miles']>(25)

  // Input limits are a convenience; the server enforces the real departure window.
  const [limits] = useState(() => {
    const now = new Date()
    const max = new Date(now.getTime() + MAX_DAYS_AHEAD * 24 * 3600 * 1000)
    return { min: toLocalInputValue(now), max: toLocalInputValue(max) }
  })

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    onSubmit({
      origin: origin.trim(),
      destination: destination.trim(),
      // datetime-local is in the browser's timezone; toISOString makes the offset explicit.
      departure: new Date(departure).toISOString(),
      load_lb: Number(load),
      interval_miles: interval,
    })
  }

  const fieldError = (name: string) =>
    fieldErrors?.[name] ? <span className="field-error">{fieldErrors[name].join(' ')}</span> : null

  return (
    <form className="plan-form" onSubmit={handleSubmit}>
      <label>
        Origin
        <input value={origin} onChange={(e) => setOrigin(e.target.value)} required
          placeholder="City, state or address" />
        {fieldError('origin')}
      </label>
      <label>
        Destination
        <input value={destination} onChange={(e) => setDestination(e.target.value)} required
          placeholder="City, state or address" />
        {fieldError('destination')}
      </label>
      <label>
        Departure ({ZONE})
        <input type="datetime-local" value={departure} onChange={(e) => setDeparture(e.target.value)}
          min={limits.min} max={limits.max} required />
        {fieldError('departure')}
      </label>
      <div className="form-row">
        <label>
          Load (lb)
          <input type="number" inputMode="numeric" min={1} max={200000} step={1} value={load}
            onChange={(e) => setLoad(e.target.value)} required />
          {fieldError('load_lb')}
        </label>
        <label>
          Check every
          <select value={interval}
            onChange={(e) => setInterval(Number(e.target.value) as PlanInput['interval_miles'])}>
            <option value={10}>10 miles</option>
            <option value={25}>25 miles</option>
            <option value={50}>50 miles</option>
          </select>
          {fieldError('interval_miles')}
        </label>
      </div>
      <button type="submit" disabled={loading}>
        {loading ? 'Planning…' : 'Plan routes'}
      </button>
    </form>
  )
}
