import { useEffect, useState } from 'react'
import { formatTime } from '../lib/format'

interface Props {
  start: string
  hours: number
  hour: number
  onChange: (hour: number) => void
  status: 'loading' | 'error' | 'ready'
  error?: string
}

const PLAY_STEP_MS = 600

export function HourSlider({ start, hours, hour, onChange, status, error }: Props) {
  const [playing, setPlaying] = useState(false)

  useEffect(() => {
    if (!playing) return
    const timer = window.setInterval(() => {
      onChange(hour >= hours ? 0 : hour + 1)
    }, PLAY_STEP_MS)
    return () => window.clearInterval(timer)
  }, [playing, hour, hours, onChange])

  const time = new Date(new Date(start).getTime() + hour * 3600 * 1000).toISOString()
  const label = `${formatTime(time)} (${hour === 0 ? 'departure' : `+${hour}h`})`

  return (
    <div className="hour-slider">
      <div className="hour-slider-title">Weather along the corridor</div>
      {status === 'loading' && <div className="hour-slider-status">Loading forecast grid…</div>}
      {status === 'error' && <div className="hour-slider-status error">{error}</div>}
      {status === 'ready' && (
        <div className="hour-slider-controls">
          <button
            type="button"
            onClick={() => setPlaying((p) => !p)}
            aria-label={playing ? 'Pause' : 'Play'}
          >
            {playing ? '❚❚' : '▶'}
          </button>
          <input
            type="range"
            min={0}
            max={hours}
            step={1}
            value={hour}
            onChange={(e) => onChange(Number(e.target.value))}
            aria-label="Forecast hour"
            aria-valuetext={label}
          />
          <span className="hour-slider-label">{label}</span>
        </div>
      )}
    </div>
  )
}
