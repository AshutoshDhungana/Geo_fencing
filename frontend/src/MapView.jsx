import L from 'leaflet'
import { useEffect, useRef } from 'react'
import { Circle, CircleMarker, MapContainer, Polygon, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet'
import { statusOf } from './api.js'

const COLORS = { in: '#2e7d32', out: '#c62828', stale: '#8a8a84', none: '#8a8a84' }
const FENCE_STYLE = { color: '#2e7d32', weight: 2, fillOpacity: 0.08, dashArray: '6 6' }
const EDIT_STYLE = { color: '#1565c0', weight: 3, fillOpacity: 0.15, dashArray: null }
const PAD = { maxZoom: 18, padding: [60, 60] }

// Fit the view once per mode when data first arrives; afterwards the user owns the camera.
function AutoFit({ animals, fences, fitKey }) {
  const map = useMap()
  const done = useRef(null)
  useEffect(() => {
    const pts = [
      ...fences.flatMap(f => f.polygon ?? [[f.lat, f.lon]]),
      ...animals.filter(a => a.reading).map(a => [a.reading.lat, a.reading.lon]),
    ]
    if (done.current === fitKey || !pts.length) return
    map.fitBounds(pts, PAD)
    done.current = fitKey
  }, [animals, fences, fitKey, map])
  return null
}

const toPts = layer => layer.getLatLngs()[0].map(p => [+p.lat.toFixed(7), +p.lng.toFixed(7)])

// Leaflet-Geoman drawing/editing. edit = { points } to reshape an existing boundary, {} to draw a new one.
// Every change is reported through onDraft; saving is up to the sidebar.
function FenceEditor({ edit, onDraft }) {
  const map = useMap()
  useEffect(() => {
    if (!edit) return
    let layer
    const watch = l => {
      layer = l
      l.setStyle(EDIT_STYLE)
      l.pm.enable({ allowSelfIntersection: false })
      l.on('pm:edit', () => onDraft(toPts(l)))
      onDraft(toPts(l))
    }
    if (edit.points) {
      watch(L.polygon(edit.points).addTo(map))
      map.fitBounds(layer.getBounds(), PAD)
    } else {
      map.pm.enableDraw('Polygon', { allowSelfIntersection: false, pathOptions: EDIT_STYLE, templineStyle: EDIT_STYLE })
      map.once('pm:create', e => watch(e.layer))
    }
    return () => { map.pm.disableDraw(); map.off('pm:create'); layer?.remove() }
  }, [edit, map, onDraft])
  return null
}

function FlyTo({ focus }) {
  const map = useMap()
  useEffect(() => { if (focus) map.flyTo([focus.lat, focus.lon], 18, { duration: 0.6 }) }, [focus, map])
  return null
}

export default function MapView({ animals, fences, track, focus, selected, onSelect, fitKey, now, edit, onDraft }) {
  return (
    <MapContainer center={[27.671239, 85.440312]} zoom={17} className="map">
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      />
      {fences.filter(f => f.id !== edit?.id).map(f => f.polygon
        ? <Polygon key={f.id} positions={f.polygon} pathOptions={FENCE_STYLE}><Tooltip>{f.name}</Tooltip></Polygon>
        : <Circle key={f.id} center={[f.lat, f.lon]} radius={f.radius_m} pathOptions={FENCE_STYLE}>
            <Tooltip>{f.name} · {Math.round(f.radius_m)} m radius</Tooltip>
          </Circle>)}
      {track.length > 1 && <Polyline positions={track} pathOptions={{ color: '#1565c0', weight: 3, opacity: 0.7 }} />}
      {animals.filter(a => a.reading).map(a => {
        const c = COLORS[statusOf(a, now)]
        return (
          <CircleMarker key={a.tag} center={[a.reading.lat, a.reading.lon]} radius={a.tag === selected ? 11 : 8}
            pathOptions={{ color: '#fff', weight: 2, fillColor: c, fillOpacity: 1 }}
            eventHandlers={{ click: () => onSelect(a.tag) }}>
            <Tooltip direction="top" offset={[0, -8]}>{a.name} · {a.reading.distance_m} m</Tooltip>
          </CircleMarker>
        )
      })}
      <AutoFit animals={animals} fences={fences} fitKey={fitKey} />
      <FenceEditor edit={edit} onDraft={onDraft} />
      <FlyTo focus={focus} />
    </MapContainer>
  )
}
