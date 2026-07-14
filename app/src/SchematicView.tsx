import { useEffect, useMemo, useRef, useState } from 'react'
import type { Station, Series } from './types'
import { PAGE_LABELS } from './types'
import {
  loadMapSvg,
  loadSeries,
  loadSerieColors,
  loadHighlights,
  type SeriesResult,
  type HighlightPath,
} from './data'
import { fallbackColor } from './color'

const VIEWBOX = '0 0 895.181 1262'

interface Props {
  page: number
  onPage: (page: number) => void
  stations: Station[]
}

interface DirectInfo {
  series: Series[]
  reachable: Set<string>
}

interface Tip {
  text: string
  x: number
  y: number
}

function productClass(s: Series): 'ic' | 'spr' | null {
  const p = s.product?.toLowerCase()
  if (!p) return null
  if (p.includes('sprinter') || p.includes('stoptrein') || p.includes('stopbus'))
    return 'spr'
  return 'ic'
}

function parseDash(dash: string): string | undefined {
  const m = dash.match(/\[([^\]]*)\]/)
  const inner = m?.[1].trim()
  return inner ? inner.split(/\s+/).join(' ') : undefined
}

export default function SchematicView({ page, onPage, stations }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<HTMLDivElement>(null)
  const [series, setSeries] = useState<SeriesResult | null>(null)
  const [colors, setColors] = useState<Record<string, string>>({})
  const [highlights, setHighlights] = useState<Record<string, HighlightPath[]>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const [pinned, setPinned] = useState<string[]>([])
  const [tip, setTip] = useState<Tip | null>(null)
  const [showLines, setShowLines] = useState(true)
  const [showStations, setShowStations] = useState(true)
  const [showIc, setShowIc] = useState(true)
  const [showSpr, setShowSpr] = useState(true)

  useEffect(() => {
    loadSerieColors().then(setColors)
  }, [])

  useEffect(() => {
    setSelected(null)
    setHovered(null)
    setTip(null)
    setSeries(null)
    setHighlights({})
    let alive = true
    loadMapSvg(page).then((svg) => {
      if (!alive || !mapRef.current) return
      mapRef.current.innerHTML = svg
      const el = mapRef.current.querySelector('svg')
      if (el) {
        el.removeAttribute('width')
        el.removeAttribute('height')
      }
    })
    loadSeries(page).then((f) => {
      if (alive) setSeries(f)
    })
    loadHighlights(page).then((h) => {
      if (alive) setHighlights(h)
    })
    return () => {
      alive = false
    }
  }, [page])

  const byId = useMemo(() => new Map(stations.map((s) => [s.id, s])), [stations])

  const placed = useMemo(
    () => stations.filter((s) => s.coords?.[String(page)]),
    [stations, page],
  )

  const direct = useMemo<DirectInfo | null>(() => {
    if (!selected || !series) return null
    const hits = series.file.series.filter((s) => {
      if (!s.routes.some((r) => r.stops.includes(selected))) return false
      const cls = productClass(s)
      if (cls === 'ic') return showIc
      if (cls === 'spr') return showSpr
      return true
    })
    const reachable = new Set<string>()
    for (const s of hits) {
      for (const r of s.routes) {
        if (r.stops.includes(selected)) r.stops.forEach((st) => reachable.add(st))
      }
    }
    reachable.delete(selected)
    return { series: hits, reachable }
  }, [selected, series, showIc, showSpr])

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

  const highlightPaths = useMemo(() => {
    return renderSeries.flatMap((s) =>
      (highlights[s.id] ?? []).map((p, i) => ({
        key: `${s.id}-${i}`,
        serie: s.id,
        color: colors[s.id] ?? fallbackColor(s.id),
        d: p.d,
        w: p.w,
        dash: parseDash(p.dash),
      })),
    )
  }, [renderSeries, highlights, colors])

  const togglePin = (serie: string) =>
    setPinned((cur) =>
      cur.includes(serie) ? cur.filter((x) => x !== serie) : [...cur, serie],
    )

  const showTip = (text: string, e: React.MouseEvent) => {
    const r = wrapRef.current?.getBoundingClientRect()
    if (!r) return
    setTip({ text, x: e.clientX - r.left, y: e.clientY - r.top })
  }

  const name = (id: string) => byId.get(id)?.name ?? id

  const serieRow = (s: Series, anchor: string | null) => {
    const route =
      (anchor && s.routes.find((r) => r.stops.includes(anchor))) || s.routes[0]
    const from = route.stops[0]
    const to = route.stops[route.stops.length - 1]
    const isPinned = pinned.includes(s.id)
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
        <strong>{s.id}</strong> {isPinned && <span className="pin-mark">vast</span>}{' '}
        {Object.keys(highlights).length > 0 && !highlights[s.id]?.length && (
          <span className="tag-nokaart">
            {series?.source === 'gtfs' ? 'niet op de kaart' : 'geen lijn-highlight'}
          </span>
        )}{' '}
        {name(from)} &ndash; {name(to)}
        {s.frequency.note && <div className="muted">{s.frequency.note}</div>}
      </li>
    )
  }

  return (
    <div>
      <nav className="tabs schematic-tabs">
        {[1, 2, 3, 4].map((p) => (
          <button
            key={p}
            className={page === p ? 'active' : ''}
            onClick={() => onPage(p)}
          >
            {PAGE_LABELS[p]}
          </button>
        ))}
      </nav>
      <div className="schematic">
      <div
        ref={wrapRef}
        className={`map-wrap${selected || pinned.length ? ' map-dim' : ''}`}
      >
        <div className="map-art" ref={mapRef} />
        <svg className="map-overlay" viewBox={VIEWBOX}>
          {showLines && (
            <g className="hl">
              {highlightPaths.map((p) => (
                <path
                  key={p.key}
                  className={
                    hovered !== null
                      ? hovered === p.serie
                        ? 'hot'
                        : 'cold'
                      : pinned.length
                        ? pinned.includes(p.serie)
                          ? 'hot'
                          : 'cold'
                        : ''
                  }
                  d={p.d}
                  stroke={p.color}
                  strokeWidth={p.w + (hovered === p.serie ? 2.5 : 0.5)}
                  strokeDasharray={p.dash}
                  onMouseEnter={() => setHovered(p.serie)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => togglePin(p.serie)}
                >
                  <title>
                    {p.serie}
                    {pinned.includes(p.serie) ? ' (vast, klik om los te maken)' : ''}
                  </title>
                </path>
              ))}
            </g>
          )}
          {placed.map((s) => {
            const [x, y] = s.coords![String(page)]
            const isHoverStop = hoveredStops.has(s.id)
            const pinColor = pinnedStops.get(s.id)
            const dotColor = isHoverStop
              ? (hovered && (colors[hovered] ?? fallbackColor(hovered))) || undefined
              : pinColor
            const cls =
              s.id === selected
                ? 'st sel'
                : dotColor
                  ? 'st hstop'
                  : showStations && direct?.reachable.has(s.id)
                    ? 'st reach'
                    : showStations
                      ? 'st debug'
                      : 'st'
            return (
              <circle
                key={s.id}
                className={cls}
                cx={x}
                cy={y}
                r={(s.major ? 6 : 4) + (isHoverStop || pinColor ? 1 : 0)}
                style={dotColor ? { fill: dotColor } : undefined}
                onClick={() => {
                  setPinned([])
                  setSelected(s.id === selected ? null : s.id)
                }}
                onMouseEnter={(e) => showTip(s.name, e)}
                onMouseLeave={() => setTip(null)}
              />
            )
          })}
        </svg>
        {tip && (
          <div className="tip" style={{ left: tip.x + 14, top: tip.y - 12 }}>
            {tip.text}
          </div>
        )}
        <div className="view-toggles">
          <label>
            <input
              type="checkbox"
              checked={showIc}
              onChange={(e) => setShowIc(e.target.checked)}
            />{' '}
            intercity
          </label>
          <label>
            <input
              type="checkbox"
              checked={showSpr}
              onChange={(e) => setShowSpr(e.target.checked)}
            />{' '}
            sprinter
          </label>
          <span className="toggle-sep" />
          <label>
            <input
              type="checkbox"
              checked={showLines}
              onChange={(e) => setShowLines(e.target.checked)}
            />{' '}
            lijnen
          </label>
          <label>
            <input
              type="checkbox"
              checked={showStations}
              onChange={(e) => setShowStations(e.target.checked)}
            />{' '}
            stations
          </label>
        </div>
      </div>
      <aside className="panel">
        {!selected && !pinned.length && (
          <p>
            Klik een station. Klik daarna een oplichtende lijn om die vast te
            zetten. De grijze stippen markeren de klikbare stations; zet ze
            uit met "stations" rechtsboven op de kaart.
          </p>
        )}
        {selected && (
          <>
            <h2>{name(selected)}</h2>
            {!series && (
              <p className="muted">
                Nog geen seriedata voor deze pagina (extractie-agents draaien nog).
              </p>
            )}
            {series && direct && (
              <>
                <p className="muted">
                  bron: {series.source === 'kaart' ? 'kaartextractie' : 'GTFS (afgeleid)'}{' '}
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
