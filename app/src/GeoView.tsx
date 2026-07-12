import { useEffect, useMemo, useRef, useState } from 'react'
import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { Series, Station } from './types'
import { PAGE_LABELS } from './types'
import {
  loadProductMap,
  loadSerieColors,
  loadSeries,
  type SeriesResult,
} from './data'
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
  const [colors, setColors] = useState<Record<string, string>>({})
  const [products, setProducts] = useState<Record<string, string>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const [hoveredStation, setHoveredStation] = useState<string | null>(null)
  const [pinned, setPinned] = useState<string[]>([])
  const [target, setTarget] = useState<[number, number] | null>(null)
  const [radiusKm, setRadiusKm] = useState(14)
  const [colorBase, setColorBase] = useState(false)
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
    setHovered(null)
    loadSeries(win).then((f) => {
      if (alive) setSeries(f)
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
    const routePts = (r: { stops: string[] }): [number, number][] => {
      const pts: [number, number][] = []
      for (const id of r.stops) {
        const g = byId.get(id)?.geo
        if (g) pts.push(g)
      }
      return pts
    }
    // Pass 1: white casing under everything (transit map style).
    for (const s of renderSeries) {
      const state = serieState(s)
      for (const r of s.routes) {
        const pts = routePts(r)
        if (pts.length < 2) continue
        group.addLayer(
          L.polyline(pts, {
            renderer,
            color: '#ffffff',
            weight: (state === 'hot' ? 5 : 3) + 3,
            opacity: state === 'cold' ? 0.08 : 0.9,
            interactive: false,
          }),
        )
      }
    }
    // Pass 2: the colored lines.
    for (const s of renderSeries) {
      const color = colors[s.id] ?? fallbackColor(s.id)
      const state = serieState(s)
      for (const r of s.routes) {
        const pts = routePts(r)
        if (pts.length < 2) continue
        const line = L.polyline(pts, {
          renderer,
          color,
          weight: state === 'hot' ? 5 : 3,
          opacity: state === 'cold' ? 0.15 : 0.9,
          bubblingMouseEvents: false,
        })
        line.bindTooltip(s.id, { sticky: true })
        line.on('mouseover', () => setHovered(s.id))
        line.on('mouseout', () => setHovered(null))
        line.on('click', () => togglePin(s.id))
        group.addLayer(line)
      }
    }
  }, [renderSeries, colors, hovered, pinned, byId, selected, hoveredStation])

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
    }
  }, [selected, hovered, hoveredStation, hoveredStops, pinnedStops, inside, direct, colors, byId])

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
                    const unreach = Boolean(direct) && !isReach && id !== selected
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
                          {isReach && <span className="tag-direct">direct</span>}
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
