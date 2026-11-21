export function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours === 0) return `${minutes} min`
  return minutes === 0 ? `${hours} h` : `${hours} h ${minutes} min`
}

// Times are shown in the browser's timezone, always with the zone name, so "14:05" is never
// mistaken for local time at the origin.
const timeFormat = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
  timeZoneName: 'short',
})

/** "Sat 14:05 CST" in the browser's timezone. */
export function formatTime(iso: string): string {
  return timeFormat.format(new Date(iso))
}

/** Short name of the browser's timezone right now, e.g. "CST" or "GMT+6". */
export function localZoneName(): string {
  const part = timeFormat.formatToParts(new Date()).find((p) => p.type === 'timeZoneName')
  return part?.value ?? 'local time'
}

export function formatMiles(miles: number): string {
  return `${Math.round(miles).toLocaleString()} mi`
}

/** Value for a datetime-local input, in local time. */
export function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

/** "1 break, 1 rest" style summary of a route's stops. */
export function describeStops(stops: { kind: 'break' | 'rest' }[]): string {
  const breaks = stops.filter((s) => s.kind === 'break').length
  const rests = stops.length - breaks
  const parts = []
  if (breaks) parts.push(`${breaks} break${breaks > 1 ? 's' : ''}`)
  if (rests) parts.push(`${rests} rest${rests > 1 ? 's' : ''}`)
  return parts.join(', ')
}
