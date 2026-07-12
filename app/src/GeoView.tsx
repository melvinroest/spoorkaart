import { useEffect, useMemo, useRef, useState } from 'react'
import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet-polylineoffset'
import type { Series, Station } from './types'
import { PAGE_LABELS } from './types'
import {
  loadGtfsSeries,
  loadMinutes,
  loadProductMap,
  loadSerieColors,
  loadSeries,
  loadShapes,
  type SeriesResult,
} from './data'
import type { SeriesFile, ShapesFile } from './types'
import { buildTimeIndex, type TimeIndex } from './minutes'
import { fallbackColor } from './color'
import { haversineKm, parseLatLon } from './geo'

interface Props {
  stations: Station[]
  active?: boolean
}

const DOT_BASE = {
  color: '#ffffff',
  weight: 1,
  fillColor: '#3d4f5f',
  fillOpacity: 0.85,
}

// Last-mile speeds for the isochrone, km/h.
const SPEEDS = { lopen: 5, fiets: 16, auto: 40 } as const
type Speed = keyof typeof SPEEDS

// Real routes are longer than the straight line. Measured against Google
// around the Kite Pharma pin: 16.1 km road vs 10.2 km hemelsbreed (1.58)
// and 2.5 km walking vs 1.5 km (1.67); Dutch cycle-network average is ~1.4.
const DETOUR_FACTOR = 1.4

const ISO_BANDS: { limit: number; color: string; label: string }[] = [
  { limit: 30, color: '#00a650', label: 'onder 30 min' },
  { limit: 45, color: '#ffc917', label: '30 tot 45 min' },
  { limit: 60, color: '#f36f21', label: '45 tot 60 min' },
  { limit: Infinity, color: '#e8112d', label: 'boven 60 min' },
]

function isoColor(t: number): string {
  for (const b of ISO_BANDS) if (t < b.limit) return b.color
  return ISO_BANDS[ISO_BANDS.length - 1].color
}

// Stable per-serie sideways offset in pixels so series sharing the same
// track render as parallel strands instead of hiding each other. Five slots
// keep the worst off-track error bounded to 8 px.
function offsetFor(id: string): number {
  let h = 0
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 997
  return ((h % 5) - 2) * 4
}

// A pixel offset larger than a curve's on-screen size draws little loops at
// tight bends, so the offset fades out when zooming to country level where
// strand separation is invisible anyway.
function offsetZoomFactor(zoom: number): number {
  if (zoom >= 11) return 1
  if (zoom >= 10) return 0.5
  return 0
}

type OffsetPolyline = L.Polyline & {
  _baseOffset?: number
  setOffset?: (offset: number) => void
}

// RdT station type -> chip label. Sneltrein stays its own category on purpose:
// a knooppuntSneltreinstation (Ommen, Valkenburg) is neither IC nor sprinter.
function typeChip(t?: string): 'IC' | 'SNEL' | 'SPR' | null {
  if (!t) return null
  const s = t.toLowerCase()
  if (s.includes('intercity') || s.includes('mega')) return 'IC'
  if (s.includes('sneltrein')) return 'SNEL'
  return 'SPR'
}

function productToChip(p: string): 'IC' | 'SNEL' | 'SPR' | null {
  const s = p.toLowerCase()
  if (s.includes('sprinter') || s.includes('stoptrein') || s.includes('stopbus'))
    return 'SPR'
  if (s.includes('sneltrein')) return 'SNEL'
  if (
    s.includes('intercity') ||
    s.includes('eurostar') ||
    s.includes('ice') ||
    s.includes('nightjet') ||
    s.includes('euro')
  )
    return 'IC'
  return null
}

// Serie -> chip. Own product field first (GTFS source), then the GTFS
// product lookup (kaart source), split combined labels like 700/800, then
// the foreign id prefix (RB/RS locals, RE fast regionals), then kind.
function serieChip(
  s: Series,
  products: Record<string, string>,
): 'IC' | 'SNEL' | 'SPR' | null {
  const own = s.product ?? products[s.id]
  if (own) {
    const c = productToChip(own)
    if (c) return c
  }
  for (const part of s.id.split('/')) {
    const p = products[part]
    if (p) {
      const c = productToChip(p)
      if (c) return c
    }
  }
  if (/^R[BS]/i.test(s.id)) return 'SPR'
  if (/^RE/i.test(s.id)) return 'SNEL'
  if (s.kind === 'internationaal') return 'IC'
  return null
}

export default function GeoView({ stations, active = true }: Props) {
  const mapDivRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const dotsRef = useRef(new Map<string, L.CircleMarker>())
  const linesRef = useRef<L.LayerGroup | null>(null)
  const lineRendererRef = useRef<L.Renderer | null>(null)
  const circleRef = useRef<L.Circle | null>(null)
  const targetDotRef = useRef<L.CircleMarker | null>(null)

  const [win, setWin] = useState(1)
  const [series, setSeries] = useState<SeriesResult | null>(null)
  const [timeIndex, setTimeIndex] = useState<TimeIndex | null>(null)
  const [gtfsSeries, setGtfsSeries] = useState<SeriesFile | null>(null)
  const [shapes, setShapes] = useState<ShapesFile | null>(null)
  const [colors, setColors] = useState<Record<string, string>>({})
  const [products, setProducts] = useState<Record<string, string>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const [hoveredStation, setHoveredStation] = useState<string | null>(null)
  const [pinned, setPinned] = useState<string[]>([])
  const [target, setTarget] = useState<[number, number] | null>(null)
  const [radiusKm, setRadiusKm] = useState(14)
  const [colorBase, setColorBase] = useState(false)
  const [isoMode, setIsoMode] = useState(false)
  const [speed, setSpeed] = useState<Speed>('fiets')
  const [coordText, setCoordText] = useState('')
  const [coordError, setCoordError] = useState(false)

  const byId = useMemo(() => new Map(stations.map((s) => [s.id, s])), [stations])
  const geoStations = useMemo(() => stations.filter((s) => s.geo), [stations])

  // Map island: Leaflet owns everything inside mapDivRef.
  useEffect(() => {
    const div = mapDivRef.current
    if (!div || mapRef.current) return
    const map = L.map(div, { zoomSnap: 0.5 })
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-bijdragers',
    }).addTo(map)
    // Series lines and the radius circle render in a pane under the dots.
    map.createPane('lines').style.zIndex = '399'
    lineRendererRef.current = L.canvas({ pane: 'lines', tolerance: 6 })
    linesRef.current = L.layerGroup().addTo(map)
    const dotRenderer = L.canvas({ tolerance: 3 })
    for (const s of geoStations) {
      const m = L.circleMarker(s.geo as [number, number], {
        renderer: dotRenderer,
        radius: s.major ? 6 : 4.5,
        bubblingMouseEvents: false,
        ...DOT_BASE,
      })
      m.bindTooltip(s.name, { direction: 'top', offset: [0, -6] })
      m.on('click', () => {
        setPinned([])
        setSelected((cur) => (cur === s.id ? null : s.id))
      })
      m.on('mouseover', () => setHoveredStation(s.id))
      m.on('mouseout', () => setHoveredStation(null))
      m.addTo(map)
      dotsRef.current.set(s.id, m)
    }
    // A click on empty map (no dot, no line) clears the station selection.
    map.on('click', () => setSelected(null))
    // Rescale the per-serie line offsets when the zoom level changes.
    map.on('zoomend', () => {
      const f = offsetZoomFactor(map.getZoom())
      linesRef.current?.eachLayer((l) => {
        const line = l as OffsetPolyline
        if (line._baseOffset !== undefined && line.setOffset)
          line.setOffset(line._baseOffset * f)
      })
    })
    const nl = geoStations
      .filter((s) => s.country === 'NL')
      .map((s) => s.geo as [number, number])
    map.fitBounds(L.latLngBounds(nl).pad(0.03))
    mapRef.current = map
    // Debug hook for browser-driven checks (latLngToContainerPoint etc).
    ;(window as unknown as { spoorkaartMap?: L.Map }).spoorkaartMap = map
    return () => {
      map.remove()
      mapRef.current = null
      linesRef.current = null
      lineRendererRef.current = null
      circleRef.current = null
      targetDotRef.current = null
      dotsRef.current.clear()
    }
  }, [geoStations])

  useEffect(() => {
    loadSerieColors().then(setColors)
    loadProductMap().then(setProducts)
  }, [])

  // Hidden containers freeze Leaflet's size; recompute when shown again.
  useEffect(() => {
    if (active) mapRef.current?.invalidateSize()
  }, [active])

  useEffect(() => {
    let alive = true
    setSeries(null)
    setTimeIndex(null)
    setGtfsSeries(null)
    setShapes(null)
    setHovered(null)
    loadSeries(win).then((f) => {
      if (alive) setSeries(f)
    })
    Promise.all([loadGtfsSeries(win), loadMinutes(win)]).then(([s, m]) => {
      if (!alive) return
      setGtfsSeries(s)
      setTimeIndex(s && m ? buildTimeIndex(s, m) : null)
    })
    loadShapes(win).then((sh) => {
      if (alive) setShapes(sh)
    })
    return () => {
      alive = false
    }
  }, [win])

  const direct = useMemo(() => {
    if (!selected || !series) return null
    const hits = series.file.series.filter((s) =>
      s.routes.some((r) => r.stops.includes(selected)),
    )
    const reachable = new Set<string>()
    for (const s of hits) {
      for (const r of s.routes) {
        if (r.stops.includes(selected)) r.stops.forEach((st) => reachable.add(st))
      }
    }
    reachable.delete(selected)
    return { series: hits, reachable }
  }, [selected, series])

  const pinnedSeries = useMemo<Series[]>(() => {
    if (!series) return []
    return pinned
      .map((id) => series.file.series.find((s) => s.id === id))
      .filter((s): s is Series => Boolean(s))
  }, [pinned, series])

  const renderSeries = useMemo<Series[]>(() => {
    const seen = new Set<string>()
    const all = [...(direct?.series ?? []), ...pinnedSeries]
    return all.filter((s) => {
      if (seen.has(s.id)) return false
      seen.add(s.id)
      return true
    })
  }, [direct, pinnedSeries])

  const hoveredStops = useMemo(() => {
    if (!hovered || !series) return new Set<string>()
    const s = series.file.series.find((x) => x.id === hovered)
    if (!s) return new Set<string>()
    return new Set(s.routes.flatMap((r) => r.stops))
  }, [hovered, series])

  const pinnedStops = useMemo(() => {
    const m = new Map<string, string>()
    for (const s of pinnedSeries) {
      const c = colors[s.id] ?? fallbackColor(s.id)
      for (const r of s.routes) r.stops.forEach((st) => m.set(st, c))
    }
    return m
  }, [pinnedSeries, colors])

  const inside = useMemo(() => {
    const m = new Map<string, number>()
    if (!target) return m
    for (const s of geoStations) {
      const d = haversineKm(target, s.geo as [number, number])
      if (d <= radiusKm) m.set(s.id, d)
    }
    return m
  }, [target, radiusKm, geoStations])

  // Door-to-door minutes per station: best candidate arrival station plus
  // last-mile from there to the pin at the chosen speed. The breakdown is
  // kept so the tooltip can show which assumptions produced the number.
  const isoTimes = useMemo(() => {
    if (!isoMode || !target || !timeIndex || inside.size === 0) return null
    const lastMile = new Map<string, number>()
    for (const [d, km] of inside)
      lastMile.set(d, ((km * DETOUR_FACTOR) / SPEEDS[speed]) * 60)
    const out = new Map<
      string,
      {
        total: number
        train: number
        lm: number
        lmKm: number
        via: string
        transfer: boolean
      }
    >()
    for (const s of geoStations) {
      let best: {
        total: number
        train: number
        lm: number
        lmKm: number
        via: string
        transfer: boolean
      } | null = null
      for (const [d, lm] of lastMile) {
        const pair = timeIndex.fastest1(s.id, d)
        const direct = pair.direct ?? Infinity
        const viaTransfer = (pair.transfer ?? Infinity) < direct
        const train = viaTransfer ? (pair.transfer as number) : direct
        if (train === Infinity) continue
        const total = train + lm
        if (best === null || total < best.total)
          best = {
            total,
            train,
            lm,
            lmKm: (inside.get(d) as number) * DETOUR_FACTOR,
            via: d,
            transfer: viaTransfer,
          }
      }
      if (best !== null) out.set(s.id, best)
    }
    return out
  }, [isoMode, target, timeIndex, inside, speed, geoStations])

  // Redraw series polylines when selection, pins or hover change.
  // Pair tracing: with a station selected and another station hovered, only
  // the series whose route contains both stay hot.
  useEffect(() => {
    const group = linesRef.current
    const renderer = lineRendererRef.current
    if (!group || !renderer) return
    group.clearLayers()
    const pairWith =
      selected && hoveredStation && hoveredStation !== selected
        ? hoveredStation
        : null
    const serieState = (s: Series): '' | 'hot' | 'cold' => {
      if (hovered !== null) return hovered === s.id ? 'hot' : 'cold'
      if (pairWith)
        return s.routes.some(
          (r) => r.stops.includes(selected!) && r.stops.includes(pairWith),
        )
          ? 'hot'
          : 'cold'
      if (pinned.length) return pinned.includes(s.id) ? 'hot' : 'cold'
      return ''
    }
    const chordPts = (r: { stops: string[] }): [number, number][] => {
      const pts: [number, number][] = []
      for (const id of r.stops) {
        const g = byId.get(id)?.geo
        if (g) pts.push(g)
      }
      return pts
    }
    // Real track geometry when a gtfs shape matches this route (by serie id
    // plus best stop overlap; the displayed series may be kaart-sourced with
    // its own route indexing), otherwise straight chords between stops.
    const shapePts = (
      s: Series,
      r: { stops: string[] },
    ): [number, number][] | null => {
      const sh = shapes?.series[s.id]
      const gs = gtfsSeries?.series.find((x) => x.id === s.id)
      if (!sh || !gs) return null
      const want = new Set(r.stops)
      let bestIdx = -1
      let bestScore = 0
      gs.routes.forEach((gr, j) => {
        let n = 0
        for (const st of gr.stops) if (want.has(st)) n++
        const score = n / want.size
        if (score > bestScore) {
          bestScore = score
          bestIdx = j
        }
      })
      if (bestIdx < 0 || bestScore < 0.5) return null
      return sh.routes[bestIdx] ?? null
    }
    const geoms: { s: Series; state: '' | 'hot' | 'cold'; pts: [number, number][] }[] = []
    for (const s of renderSeries) {
      const state = serieState(s)
      for (const r of s.routes) {
        const pts = shapePts(s, r) ?? chordPts(r)
        if (pts.length < 2) continue
        geoms.push({ s, state, pts })
      }
    }
    const zoomF = offsetZoomFactor(mapRef.current?.getZoom() ?? 8)
    // Pass 1: white casing under everything (transit map style).
    for (const g of geoms) {
      const base = offsetFor(g.s.id)
      const casing = L.polyline(g.pts, {
        renderer,
        color: '#ffffff',
        weight: (g.state === 'hot' ? 5 : 3) + 3,
        opacity: g.state === 'cold' ? 0.08 : 0.9,
        interactive: false,
        offset: base * zoomF,
      } as L.PolylineOptions) as OffsetPolyline
      casing._baseOffset = base
      group.addLayer(casing)
    }
    // Pass 2: the colored lines.
    for (const g of geoms) {
      const color = colors[g.s.id] ?? fallbackColor(g.s.id)
      const base = offsetFor(g.s.id)
      const line = L.polyline(g.pts, {
        renderer,
        color,
        weight: g.state === 'hot' ? 5 : 3,
        opacity: g.state === 'cold' ? 0.15 : 0.9,
        bubblingMouseEvents: false,
        offset: base * zoomF,
      } as L.PolylineOptions) as OffsetPolyline
      line._baseOffset = base
      line.bindTooltip(g.s.id, { sticky: true })
      line.on('mouseover', () => setHovered(g.s.id))
      line.on('mouseout', () => setHovered(null))
      line.on('click', () => togglePin(g.s.id))
      group.addLayer(line)
    }
  }, [renderSeries, colors, hovered, pinned, byId, selected, hoveredStation, shapes, gtfsSeries])

  // Restyle dots from the current interaction state. With a selection
  // active, directly reachable stations get a yellow ring and in-circle
  // candidates without a direct connection dim.
  useEffect(() => {
    const reachable = direct?.reachable ?? null
    for (const [id, m] of dotsRef.current) {
      const st = byId.get(id)
      if (!st) continue
      const base = st.major ? 6 : 4.5
      if (id === selected) {
        m.setStyle({ fillColor: '#ffc917', color: '#14181d', weight: 1.5, fillOpacity: 1 })
        m.setRadius(base + 2)
      } else if (id === hoveredStation) {
        m.setStyle({ fillColor: '#ffffff', color: '#0063d3', weight: 3, fillOpacity: 1 })
        m.setRadius(base + 3)
      } else if (hoveredStops.has(id)) {
        const c = hovered ? (colors[hovered] ?? fallbackColor(hovered)) : '#ffffff'
        m.setStyle({ fillColor: c, color: '#ffffff', weight: 1.5, fillOpacity: 1 })
        m.setRadius(base + 1)
      } else if (pinnedStops.has(id)) {
        m.setStyle({
          fillColor: pinnedStops.get(id) as string,
          color: '#ffffff',
          weight: 1.5,
          fillOpacity: 1,
        })
        m.setRadius(base + 1)
      } else if (isoTimes) {
        const t = isoTimes.get(id)
        if (t === undefined) {
          m.setStyle({ ...DOT_BASE, fillOpacity: 0.4 })
          m.setRadius(base)
        } else {
          m.setStyle({
            fillColor: isoColor(t.total),
            color: '#ffffff',
            weight: 1,
            fillOpacity: 1,
          })
          m.setRadius(base + 1)
        }
      } else {
        const inCircle = inside.has(id)
        const chip = inCircle ? typeChip(st.type) : null
        let fill = DOT_BASE.fillColor
        let fillOpacity: number = DOT_BASE.fillOpacity
        let ring = DOT_BASE.color
        let weight: number = DOT_BASE.weight
        let radius = base
        if (chip) {
          fill = chip === 'SPR' ? '#00a650' : chip === 'SNEL' ? '#7a5cd6' : '#0063d3'
          fillOpacity = 1
          weight = 1.5
          radius = base + 1
        }
        if (reachable) {
          if (reachable.has(id)) {
            ring = '#ffc917'
            weight = 2.5
            fillOpacity = 1
            radius = Math.max(radius, base + 1)
          } else if (inCircle) {
            fillOpacity = 0.35
            weight = 1
          }
        }
        m.setStyle({ fillColor: fill, color: ring, weight, fillOpacity })
        m.setRadius(radius)
      }
      // Tooltip carries the door-to-door breakdown while the isochrone is
      // on, so every assumption behind the number is readable on the dot.
      const t = isoTimes?.get(id)
      if (t === undefined || !isoTimes) {
        m.setTooltipContent(st.name)
      } else if (t.train === 0) {
        m.setTooltipContent(
          `${st.name} · ${Math.round(t.total)} min: ${speed} rechtstreeks naar het ` +
            `geprikte punt (±${t.lmKm.toFixed(1)} km geschat)`,
        )
      } else {
        m.setTooltipContent(
          `${st.name} · ${Math.round(t.total)} min: trein ${Math.round(t.train)} min ` +
            `(${t.transfer ? '1 overstap' : 'direct'}) naar ${name(t.via)}, ` +
            `vandaar ${speed} ${Math.round(t.lm)} min naar het geprikte punt ` +
            `(±${t.lmKm.toFixed(1)} km geschat)`,
        )
      }
    }
  }, [selected, hovered, hoveredStation, hoveredStops, pinnedStops, inside, direct, isoTimes, speed, colors, byId])

  // Hovering a station row in the panel shows its name tooltip on the map.
  useEffect(() => {
    if (!hoveredStation) return
    const m = dotsRef.current.get(hoveredStation)
    m?.openTooltip()
    return () => {
      m?.closeTooltip()
    }
  }, [hoveredStation])

  // Radius circle plus target dot.
  useEffect(() => {
    const map = mapRef.current
    const renderer = lineRendererRef.current
    if (!map || !renderer) return
    circleRef.current?.remove()
    circleRef.current = null
    targetDotRef.current?.remove()
    targetDotRef.current = null
    if (!target) return
    circleRef.current = L.circle(target, {
      renderer,
      radius: radiusKm * 1000,
      interactive: false,
      color: '#0063d3',
      weight: 1.5,
      dashArray: '6 4',
      fillColor: '#0063d3',
      fillOpacity: 0.05,
    }).addTo(map)
    targetDotRef.current = L.circleMarker(target, {
      radius: 6,
      interactive: false,
      color: '#ffffff',
      weight: 2,
      fillColor: '#d6006f',
      fillOpacity: 1,
    }).addTo(map)
  }, [target, radiusKm])

  const togglePin = (serie: string) =>
    setPinned((cur) =>
      cur.includes(serie) ? cur.filter((x) => x !== serie) : [...cur, serie],
    )

  const name = (id: string) => byId.get(id)?.name ?? id

  const applyCoord = () => {
    const p = parseLatLon(coordText)
    if (!p) {
      setCoordError(true)
      return
    }
    setCoordError(false)
    setTarget(p)
    mapRef.current?.fitBounds(L.latLng(p).toBounds(radiusKm * 2000).pad(0.2))
  }

  const serieRow = (s: Series, anchor: string | null) => {
    const route =
      (anchor && s.routes.find((r) => r.stops.includes(anchor))) || s.routes[0]
    const from = route.stops[0]
    const to = route.stops[route.stops.length - 1]
    const isPinned = pinned.includes(s.id)
    const chip = serieChip(s, products)
    return (
      <li
        key={s.id}
        className={hovered === s.id ? 'hot' : ''}
        onMouseEnter={() => setHovered(s.id)}
        onMouseLeave={() => setHovered(null)}
        onClick={() => togglePin(s.id)}
        title={isPinned ? 'klik om los te maken' : 'klik om vast te zetten'}
      >
        <span
          className="swatch"
          style={{ background: colors[s.id] ?? fallbackColor(s.id) }}
        />
        <strong>{s.id}</strong>{' '}
        {chip && <span className={`chip chip-${chip.toLowerCase()}`}>{chip}</span>}
        {isPinned && <span className="pin-mark">vast</span>}{' '}
        {name(from)} &ndash; {name(to)}
        {s.frequency.note && <div className="muted">{s.frequency.note}</div>}
      </li>
    )
  }

  return (
    <div className="geo">
      <div className="geo-toolbar">
        <nav className="tabs">
          {[1, 2, 3, 4].map((p) => (
            <button
              key={p}
              className={win === p ? 'active' : ''}
              onClick={() => setWin(p)}
            >
              {PAGE_LABELS[p]}
            </button>
          ))}
        </nav>
        <form
          className="coord-form"
          onSubmit={(e) => {
            e.preventDefault()
            applyCoord()
          }}
        >
          <input
            className={coordError ? 'bad' : ''}
            value={coordText}
            onChange={(e) => setCoordText(e.target.value)}
            placeholder="lat, lon of Google Maps-link"
            size={26}
          />
          <button type="submit">prik punt</button>
          {target && (
            <button
              type="button"
              onClick={() => {
                setTarget(null)
                setCoordText('')
                setCoordError(false)
                setIsoMode(false)
              }}
            >
              wis
            </button>
          )}
        </form>
        <label className="radius">
          straal {radiusKm} km
          <input
            type="range"
            min={5}
            max={30}
            step={1}
            value={radiusKm}
            onChange={(e) => setRadiusKm(Number(e.target.value))}
          />
        </label>
        <label className="radius">
          <input
            type="checkbox"
            checked={colorBase}
            onChange={(e) => setColorBase(e.target.checked)}
          />{' '}
          kaartkleur
        </label>
        <label
          className="radius"
          title={target ? '' : 'prik eerst een punt'}
        >
          <input
            type="checkbox"
            checked={isoMode}
            disabled={!target}
            onChange={(e) => setIsoMode(e.target.checked)}
          />{' '}
          isochroon
        </label>
        {isoMode && target && (
          <nav className="tabs">
            {(Object.keys(SPEEDS) as Speed[]).map((sp) => (
              <button
                key={sp}
                className={speed === sp ? 'active' : ''}
                onClick={() => setSpeed(sp)}
              >
                {sp} {SPEEDS[sp]} km/u
              </button>
            ))}
          </nav>
        )}
      </div>
      <div className="geo-body">
        <div
          className={`geo-map${colorBase ? '' : ' base-muted'}`}
          ref={mapDivRef}
        />
        <aside className="panel">
          {!selected && !target && (
            <p>
              Klik een station voor zijn directe series, of prik een GPS-punt en
              zie welke stations binnen de straal liggen.
            </p>
          )}
          {isoTimes && (
            <div className="iso-legend">
              <h3>Deur-tot-deur vanaf elk station</h3>
              {ISO_BANDS.map((b) => (
                <div key={b.label}>
                  <span className="swatch" style={{ background: b.color }} />
                  {b.label}
                </div>
              ))}
              <p className="muted">
                aannames: treintijd (direct of 1 overstap, mediaan plus halve
                frequentie bij overstap) plus {speed} {SPEEDS[speed]} km/u
                vanaf het beste aankomststation binnen de cirkel, over
                hemelsbreed maal {DETOUR_FACTOR} als benadering van de echte
                route. Hover een dot voor de opbouw van het getal.
              </p>
            </div>
          )}
          {target && (
            <>
              <h3>Binnen {radiusKm} km van het punt</h3>
              {inside.size === 0 && (
                <p className="muted">Geen stations binnen de cirkel.</p>
              )}
              <ul className="inside-list">
                {[...inside.entries()]
                  .sort((a, b) => a[1] - b[1])
                  .map(([id, d]) => {
                    const chip = typeChip(byId.get(id)?.type)
                    const isReach = direct?.reachable.has(id) ?? false
                    const pair =
                      selected && id !== selected
                        ? timeIndex?.fastest1(selected, id)
                        : null
                    const mins = isReach ? (pair?.direct ?? null) : null
                    const transfer =
                      pair?.transfer != null &&
                      (!isReach || pair.transfer < (pair.direct ?? Infinity))
                        ? pair.transfer
                        : null
                    const unreach =
                      Boolean(direct) &&
                      !isReach &&
                      transfer == null &&
                      id !== selected
                    return (
                      <li
                        key={id}
                        className={
                          (id === selected ? 'sel' : '') +
                          (id === hoveredStation ? ' hot' : '') +
                          (unreach ? ' unreach' : '')
                        }
                        onClick={() => {
                          setPinned([])
                          setSelected((cur) => (cur === id ? null : id))
                        }}
                        onMouseEnter={() => setHoveredStation(id)}
                        onMouseLeave={() => setHoveredStation(null)}
                      >
                        <span>
                          {chip && <span className={`chip chip-${chip.toLowerCase()}`}>{chip}</span>}
                          {name(id)}
                          {isReach && (
                            <span className="tag-direct">
                              {mins != null ? `direct ${Math.round(mins)} min` : 'direct'}
                            </span>
                          )}
                          {transfer != null && (
                            <span className="tag-transfer">
                              overstap {Math.round(transfer)} min
                            </span>
                          )}
                        </span>
                        <span className="muted">{d.toFixed(1)} km</span>
                      </li>
                    )
                  })}
              </ul>
            </>
          )}
          {selected && (
            <>
              <h2>
                {name(selected)}
                {(() => {
                  const chip = typeChip(byId.get(selected)?.type)
                  return chip ? (
                    <span className={`chip chip-${chip.toLowerCase()}`}>{chip}</span>
                  ) : null
                })()}
                <button
                  className="clear-sel"
                  title="selectie wissen"
                  onClick={() => setSelected(null)}
                >
                  wis
                </button>
              </h2>
              {!series && <p className="muted">Seriedata laden...</p>}
              {series && direct && (
                <>
                  <p className="muted">
                    bron:{' '}
                    {series.source === 'kaart' ? 'kaartextractie' : 'GTFS (afgeleid)'}{' '}
                    &middot; {direct.series.length} directe series &middot;{' '}
                    {direct.reachable.size} stations zonder overstap
                  </p>
                  <ul>{direct.series.map((s) => serieRow(s, selected))}</ul>
                </>
              )}
            </>
          )}
          {pinned.length > 0 && (
            <>
              <h3>Vastgezet</h3>
              <ul>{pinnedSeries.map((s) => serieRow(s, null))}</ul>
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
