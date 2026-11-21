import { useEffect, useState } from 'react'

const SLOW_AFTER_MS = 8000

/** Shown while a plan is being built. Long waits are usually the server waking up. */
export function LoadingNotice() {
  const [slow, setSlow] = useState(false)

  useEffect(() => {
    const timer = window.setTimeout(() => setSlow(true), SLOW_AFTER_MS)
    return () => window.clearTimeout(timer)
  }, [])

  return (
    <div className="map-loading" role="status">
      <span className="spinner" />
      {slow
        ? 'Still working: the server may be waking up, which can take up to a minute.'
        : 'Fetching routes and forecasts…'}
    </div>
  )
}
