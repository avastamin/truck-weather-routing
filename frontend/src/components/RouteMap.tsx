import { useEffect, useMemo, useRef, useState } from 'react'
import { Map, NavigationControl, Popup, useControl, type MapRef } from 'react-map-gl/maplibre'
import type { PickingInfo } from '@deck.gl/core'
import { MapboxOverlay, type MapboxOverlayProps } from '@deck.gl/mapbox'
import { PathLayer, ScatterplotLayer, SolidPolygonLayer } from '@deck.gl/layers'
import { setWorkerUrl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { Checkpoint, Heatmap, Plan, PlannedRoute, RestStop } from '../lib/api'
import { describeStops, formatDuration, formatMiles, formatTime } from '../lib/format'
import { RISK_LABEL, RISK_LEVELS, RISK_RGB, riskCss } from '../lib/risk'

// MapLibre looks for its worker next to its own file, which isn't where Vite puts it.
// vite.config.ts copies the worker into public/.
setWorkerUrl('/maplibre-gl-worker.mjs')

// OpenFreeMap: free vector tiles, no API key.
const MAP_STYLE = 'https://tiles.openfreemap.org/styles/positron'
const INITIAL_VIEW = { longitude: -98.5, latitude: 39.5, zoom: 3.6 }

const SELECTED_RGB: [number, number, number] = [29, 78, 216]
const MUTED_RGB: [number, number, number] = [148, 163, 184]
// Low cells are faint so the corridor reads as "fine" and anything worse stands out.
const LOW_ALPHA = 40
const RISK_ALPHA = 150
const NO_DATA = -1

interface Props {
  plan: Plan | undefined
  heatmap: Heatmap | undefined
  hour: number
  selectedId: string
  onSelect: (id: string) => void
}

interface CheckpointDatum extends Checkpoint {
  routeId: string
}

interface RestStopDatum extends RestStop {
  routeId: string
}

interface Cell {
  index: number
  polygon: [number, number][]
}

type PopupTarget =
  | { kind: 'checkpoint'; planId: string; cp: CheckpointDatum }
  | { kind: 'cell'; planId: string; index: number; lon: number; lat: number }

function cellColor(risk: number): [number, number, number, number] {
  if (risk === NO_DATA) return [0, 0, 0, 0]
  const level = RISK_LEVELS[risk]
  return [...RISK_RGB[level], level === 'low' ? LOW_ALPHA : RISK_ALPHA]
}

const TOOLTIP_STYLE = {
  background: '#0f172a',
  color: '#fff',
  fontSize: '12px',
  lineHeight: '1.5',
  padding: '6px 10px',
  borderRadius: '6px',
  whiteSpace: 'pre',
}

function restStopTooltip(stop: RestStopDatum) {
  const what = stop.kind === 'rest' ? '10 h rest' : '30 min break'
  const lines = [
    `Route ${stop.routeId} · ${what} at mile ${Math.round(stop.mile)}`,
    `Stop ${formatTime(stop.arrive)}`,
    `Leave ${formatTime(stop.leave)}`,
  ]
  return { text: lines.join('\n'), style: TOOLTIP_STYLE }
}

/** Hovering a route line or rest stop shows its summary, so the map reads without the sidebar. */
function mapTooltip(plan: Plan | undefined, { layer, object }: PickingInfo) {
  if (!plan || !object) return null
  if (layer?.id === 'rest-stops') return restStopTooltip(object as RestStopDatum)
  if (layer?.id !== 'routes') return null
  const route = object as PlannedRoute
  const miles = route.miles_by_level
  const title =
    `Route ${route.id}` + (route.id === plan.recommended_route_id ? ' · Recommended' : '')
  const lines = [
    title,
    `${formatDuration(route.duration_seconds)} · ${formatMiles(route.distance_miles)}`,
    `Arrive ${formatTime(route.arrival)}`,
    ...(route.rest_stops.length > 0
      ? [`${formatDuration(route.driving_seconds)} driving + ${describeStops(route.rest_stops)}`]
      : []),
    `Severe ${Math.round(miles.severe)} mi · High ${Math.round(miles.high)} mi` +
      (miles.no_travel > 0 ? ` · No Travel ${Math.round(miles.no_travel)} mi` : ''),
    `Average risk ${route.avg_risk.toFixed(2)} / 4`,
  ]
  return { text: lines.join('\n'), style: TOOLTIP_STYLE }
}

function DeckOverlay(props: MapboxOverlayProps) {
  const overlay = useControl<MapboxOverlay>(() => new MapboxOverlay(props))
  overlay.setProps(props)
  return null
}

export function RouteMap({ plan, heatmap, hour, selectedId, onSelect }: Props) {
  const mapRef = useRef<MapRef>(null)
  // Remember which plan the popup belongs to, so it disappears when a new plan arrives.
  const [popupState, setPopupState] = useState<PopupTarget | null>(null)
  const popup = plan && popupState?.planId === plan.plan_id ? popupState : null
  const grid = heatmap && plan && heatmap.plan_id === plan.plan_id ? heatmap : undefined

  // Zoom to the routes whenever a new plan arrives.
  useEffect(() => {
    if (!plan || !mapRef.current) return
    let [minLon, minLat, maxLon, maxLat] = [180, 90, -180, -90]
    for (const route of plan.routes) {
      for (const [lon, lat] of route.path) {
        minLon = Math.min(minLon, lon)
        minLat = Math.min(minLat, lat)
        maxLon = Math.max(maxLon, lon)
        maxLat = Math.max(maxLat, lat)
      }
    }
    mapRef.current.fitBounds([[minLon, minLat], [maxLon, maxLat]], { padding: 60, duration: 800 })
  }, [plan])

  // Draw the selected route last so it sits on top of the others.
  const orderedRoutes = useMemo(() => {
    if (!plan) return []
    return [...plan.routes].sort((a, b) => Number(a.id === selectedId) - Number(b.id === selectedId))
  }, [plan, selectedId])

  const checkpoints = useMemo<CheckpointDatum[]>(
    () =>
      orderedRoutes.flatMap((route) =>
        route.checkpoints.map((cp) => ({ ...cp, routeId: route.id })),
      ),
    [orderedRoutes],
  )

  // Cell squares only change with a new heatmap; the slider just picks a column of `risk`.
  const cells = useMemo<Cell[]>(() => {
    if (!grid) return []
    const half = grid.cell_size_deg / 2
    return grid.cells.map(([lon, lat], index) => ({
      index,
      polygon: [
        [lon - half, lat - half],
        [lon + half, lat - half],
        [lon + half, lat + half],
        [lon - half, lat + half],
      ],
    }))
  }, [grid])

  const restStops = useMemo<RestStopDatum[]>(
    () =>
      orderedRoutes.flatMap((route) =>
        route.rest_stops.map((stop) => ({ ...stop, routeId: route.id })),
      ),
    [orderedRoutes],
  )

  const layers = [
    new SolidPolygonLayer<Cell>({
      id: 'weather',
      data: cells,
      getPolygon: (c) => c.polygon,
      getFillColor: (c) => cellColor(grid ? grid.risk[c.index][hour] : NO_DATA),
      pickable: true,
      onClick: ({ object, coordinate }) =>
        object &&
        plan &&
        coordinate &&
        setPopupState({
          kind: 'cell',
          planId: plan.plan_id,
          index: object.index,
          lon: coordinate[0],
          lat: coordinate[1],
        }),
      updateTriggers: { getFillColor: [grid, hour] },
    }),
    new PathLayer<PlannedRoute>({
      id: 'routes',
      data: orderedRoutes,
      getPath: (r) => r.path,
      getColor: (r) => (r.id === selectedId ? SELECTED_RGB : MUTED_RGB),
      getWidth: (r) => (r.id === selectedId ? 6 : 4),
      widthUnits: 'pixels',
      capRounded: true,
      jointRounded: true,
      pickable: true,
      onClick: ({ object }) => object && onSelect(object.id),
      updateTriggers: { getColor: selectedId, getWidth: selectedId },
    }),
    new ScatterplotLayer<CheckpointDatum>({
      id: 'checkpoints',
      data: checkpoints,
      getPosition: (cp) => [cp.lon, cp.lat],
      getFillColor: (cp) => [...RISK_RGB[cp.level], cp.routeId === selectedId ? 255 : 140],
      getRadius: (cp) => (cp.routeId === selectedId ? 6 : 4),
      radiusUnits: 'pixels',
      stroked: true,
      getLineColor: [255, 255, 255],
      lineWidthMinPixels: 1.5,
      pickable: true,
      onClick: ({ object }) =>
        object && plan && setPopupState({ kind: 'checkpoint', planId: plan.plan_id, cp: object }),
      updateTriggers: { getFillColor: selectedId, getRadius: selectedId },
    }),
    // Driver breaks and rests: dark markers, so they stand apart from the risk-coloured checkpoints.
    new ScatterplotLayer<RestStopDatum>({
      id: 'rest-stops',
      data: restStops,
      getPosition: (s) => [s.lon, s.lat],
      getFillColor: (s) => (s.routeId === selectedId ? [15, 23, 42, 255] : [15, 23, 42, 120]),
      getRadius: (s) => (s.kind === 'rest' ? 8 : 6),
      radiusUnits: 'pixels',
      stroked: true,
      getLineColor: [255, 255, 255],
      lineWidthMinPixels: 2,
      pickable: true,
      updateTriggers: { getFillColor: selectedId },
    }),
  ]

  return (
    <Map ref={mapRef} initialViewState={INITIAL_VIEW} mapStyle={MAP_STYLE}>
      <NavigationControl position="top-right" />
      <DeckOverlay layers={layers} getTooltip={(info) => mapTooltip(plan, info)} />
      {popup && (
        <Popup
          longitude={popup.kind === 'checkpoint' ? popup.cp.lon : popup.lon}
          latitude={popup.kind === 'checkpoint' ? popup.cp.lat : popup.lat}
          onClose={() => setPopupState(null)}
          closeOnClick={false}
          maxWidth="280px"
        >
          {popup.kind === 'checkpoint' ? (
            <CheckpointDetails cp={popup.cp} />
          ) : (
            grid && <CellDetails grid={grid} index={popup.index} hour={hour} />
          )}
        </Popup>
      )}
    </Map>
  )
}

function CheckpointDetails({ cp }: { cp: CheckpointDatum }) {
  return (
    <div className="checkpoint-popup">
      <div className="checkpoint-title">
        Route {cp.routeId} · mile {Math.round(cp.mile)}
      </div>
      <div className="checkpoint-level" style={{ color: riskCss(cp.level) }}>
        {RISK_LABEL[cp.level]}
      </div>
      <dl>
        <dt>ETA</dt>
        <dd>{formatTime(cp.eta)}</dd>
        <dt>Wind</dt>
        <dd>
          {cp.wind_mph.toFixed(0)} mph
          {cp.gust_mph !== null && ` (gusts ${cp.gust_mph.toFixed(0)})`}
        </dd>
        <dt>Rain</dt>
        <dd>{cp.rain_in_hr.toFixed(2)} in/hr</dd>
        <dt>Snow</dt>
        <dd>{cp.snow_in_hr.toFixed(2)} in/hr</dd>
      </dl>
      {cp.reasons.length > 0 && (
        <ul className="checkpoint-reasons">
          {cp.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Forecast for one grid cell at the slider's hour; updates as the slider moves. */
function CellDetails({ grid, index, hour }: { grid: Heatmap; index: number; hour: number }) {
  const risk = grid.risk[index][hour]
  const time = new Date(new Date(grid.start).getTime() + hour * 3600 * 1000).toISOString()
  const fmt = (v: number | null, digits: number, unit: string) =>
    v === null ? 'no data' : `${v.toFixed(digits)} ${unit}`
  const gust = grid.gust_mph[index][hour]
  return (
    <div className="checkpoint-popup">
      <div className="checkpoint-title">Forecast at {formatTime(time)}</div>
      {risk === NO_DATA ? (
        <div className="checkpoint-level">No data</div>
      ) : (
        <div className="checkpoint-level" style={{ color: riskCss(RISK_LEVELS[risk]) }}>
          {RISK_LABEL[RISK_LEVELS[risk]]}
        </div>
      )}
      <dl>
        <dt>Wind</dt>
        <dd>
          {fmt(grid.wind_mph[index][hour], 0, 'mph')}
          {gust !== null && ` (gusts ${gust.toFixed(0)})`}
        </dd>
        <dt>Rain</dt>
        <dd>{fmt(grid.rain_in_hr[index][hour], 2, 'in/hr')}</dd>
        <dt>Snow</dt>
        <dd>{fmt(grid.snow_in_hr[index][hour], 2, 'in/hr')}</dd>
      </dl>
    </div>
  )
}
