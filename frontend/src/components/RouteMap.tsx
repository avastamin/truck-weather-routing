import { useEffect, useMemo, useRef, useState } from 'react'
import { Map, NavigationControl, Popup, useControl, type MapRef } from 'react-map-gl/maplibre'
import { MapboxOverlay, type MapboxOverlayProps } from '@deck.gl/mapbox'
import { PathLayer, ScatterplotLayer } from '@deck.gl/layers'
import { setWorkerUrl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { Checkpoint, Plan, PlannedRoute } from '../lib/api'
import { formatTime } from '../lib/format'
import { RISK_LABEL, RISK_RGB, riskCss } from '../lib/risk'

// MapLibre looks for its worker next to its own file, which isn't where Vite puts it.
// vite.config.ts copies the worker into public/.
setWorkerUrl('/maplibre-gl-worker.mjs')

// OpenFreeMap: free vector tiles, no API key.
const MAP_STYLE = 'https://tiles.openfreemap.org/styles/positron'
const INITIAL_VIEW = { longitude: -98.5, latitude: 39.5, zoom: 3.6 }

const SELECTED_RGB: [number, number, number] = [29, 78, 216]
const MUTED_RGB: [number, number, number] = [148, 163, 184]

interface Props {
  plan: Plan | undefined
  selectedId: string
  onSelect: (id: string) => void
}

interface CheckpointDatum extends Checkpoint {
  routeId: string
}

function DeckOverlay(props: MapboxOverlayProps) {
  const overlay = useControl<MapboxOverlay>(() => new MapboxOverlay(props))
  overlay.setProps(props)
  return null
}

export function RouteMap({ plan, selectedId, onSelect }: Props) {
  const mapRef = useRef<MapRef>(null)
  // Remember which plan the popup belongs to, so it disappears when a new plan arrives.
  const [popupState, setPopupState] = useState<{ planId: string; cp: CheckpointDatum } | null>(null)
  const popup = plan && popupState?.planId === plan.plan_id ? popupState.cp : null

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

  const layers = [
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
      onClick: ({ object }) => object && plan && setPopupState({ planId: plan.plan_id, cp: object }),
      updateTriggers: { getFillColor: selectedId, getRadius: selectedId },
    }),
  ]

  return (
    <Map ref={mapRef} initialViewState={INITIAL_VIEW} mapStyle={MAP_STYLE}>
      <NavigationControl position="top-right" />
      <DeckOverlay layers={layers} />
      {popup && (
        <Popup
          longitude={popup.lon}
          latitude={popup.lat}
          onClose={() => setPopupState(null)}
          closeOnClick={false}
          maxWidth="280px"
        >
          <CheckpointDetails cp={popup} />
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
