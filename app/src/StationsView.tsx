import { useEffect, useMemo, useState } from 'react'
import type { MinutesFile, SeriesFile, Station } from './types'
import { loadGtfsSeries, loadMinutes } from './data'

interface Props {
  stations: Station[]
}

// RdT station type -> short chip. Kept local so this view is self-contained.
function typeChip(t?: string): 'IC' | 'SNEL' | 'SPR' | null {
  if (!t) return null
  const s = t.toLowerCase()
  if (s.includes('intercity') || s.includes('mega')) return 'IC'
  if (s.includes('sneltrein')) return 'SNEL'
  return 'SPR'
}

type MetricKey = 'freq' | 'seriesCount' | 'dirDeg' | 'reach' | 'length'
type SortKey = MetricKey | 'name'

interface Row {
  id: string
  name: string
  type?: string
  freq: number
  seriesCount: number
  dirDeg: number
  reach: number
  length: number
}

// Column config drives both the header and the cells, so a metric is defined
// once. `title` explains what the number means (disclosure at the number).
const COLUMNS: { key: MetricKey; label: string; title: string }[] = [
  {
    key: 'freq',
    label: 'treinen/uur',
    title: 'som van de frequenties van alle series die hier stoppen',
  },
  {
    key: 'seriesCount',
    label: 'series',
    title: 'aantal treinseries dat hier stopt',
  },
  {
    key: 'dirDeg',
    label: 'richtingen',
    title: 'aantal directe buurstations (in hoeveel richtingen je kunt vertrekken)',
  },
  {
    key: 'reach',
    label: 'direct bereik',
    title: 'aantal stations bereikbaar zonder overstap',
  },
  {
    key: 'length',
    label: 'lijnlengte (min)',
    title: 'som van de rijtijd van alle lijnen die hier stoppen',
  },
]

const LIMITS: (number | 'all')[] = [25, 50, 100, 'all']

export default function StationsView({ stations }: Props) {
  const [gtfs, setGtfs] = useState<SeriesFile | null>(null)
  const [minutes, setMinutes] = useState<MinutesFile | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('freq')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [limit, setLimit] = useState<number | 'all'>(50)

  const byId = useMemo(() => new Map(stations.map((s) => [s.id, s])), [stations])

  // The metrics use the ma-do daytime network (page 1), the busiest window;
  // the GTFS files are the authoritative stop lists the time engine also uses.
  useEffect(() => {
    loadGtfsSeries(1).then(setGtfs)
    loadMinutes(1).then(setMinutes)
  }, [])

  const rows = useMemo<Row[]>(() => {
    if (!gtfs || !minutes) return []
    const seriesAt = new Map<string, Set<string>>()
    const neigh = new Map<string, Set<string>>()
    const reach = new Map<string, Set<string>>()
    const freq = new Map<string, number>()
    const length = new Map<string, number>()
    const addTo = (m: Map<string, Set<string>>, k: string, v: string) => {
      let s = m.get(k)
      if (!s) {
        s = new Set()
        m.set(k, s)
      }
      s.add(v)
    }
    for (const s of gtfs.series) {
      const mm = minutes.series[s.id]
      const hw = mm?.headwayMinutes ?? null
      const tph = hw ? 60 / hw : 0
      s.routes.forEach((r, ri) => {
        const stops = r.stops
        let dur = 0
        const mr = mm?.routes?.[ri]
        if (mr) for (const a of mr.arr) if (a != null && a > dur) dur = a
        for (let i = 0; i < stops.length; i++) {
          const st = stops[i]
          addTo(seriesAt, st, s.id)
          freq.set(st, (freq.get(st) ?? 0) + tph)
          if (dur) length.set(st, (length.get(st) ?? 0) + dur)
          let rs = reach.get(st)
          if (!rs) {
            rs = new Set()
            reach.set(st, rs)
          }
          for (const o of stops) if (o !== st) rs.add(o)
          if (i > 0) addTo(neigh, st, stops[i - 1])
          if (i < stops.length - 1) addTo(neigh, st, stops[i + 1])
        }
      })
    }
    const out: Row[] = []
    for (const [id, set] of seriesAt) {
      const st = byId.get(id)
      out.push({
        id,
        name: st?.name ?? id,
        type: st?.type,
        seriesCount: set.size,
        dirDeg: neigh.get(id)?.size ?? 0,
        reach: reach.get(id)?.size ?? 0,
        freq: Math.round((freq.get(id) ?? 0) * 10) / 10,
        length: Math.round(length.get(id) ?? 0),
      })
    }
    return out
  }, [gtfs, minutes, byId])

  const sorted = useMemo(() => {
    const arr = [...rows]
    arr.sort((a, b) => {
      const cmp =
        sortKey === 'name'
          ? a.name.localeCompare(b.name)
          : a[sortKey] - b[sortKey]
      return sortDir === 'asc' ? cmp : -cmp
    })
    return arr
  }, [rows, sortKey, sortDir])

  const shown = limit === 'all' ? sorted : sorted.slice(0, limit)

  const onSort = (key: SortKey) => {
    if (key === sortKey) setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    else {
      setSortKey(key)
      setSortDir(key === 'name' ? 'asc' : 'desc')
    }
  }

  const caret = (key: SortKey) =>
    key === sortKey ? (sortDir === 'desc' ? ' ▼' : ' ▲') : ''

  if (!gtfs || !minutes) return <p className="muted">Metrieken berekenen...</p>

  return (
    <div className="rank-view">
      <div className="rank-controls">
        <span>
          {rows.length} stations in de ma-do dienstregeling, gesorteerd op{' '}
          {sortKey === 'name'
            ? 'naam'
            : COLUMNS.find((c) => c.key === sortKey)?.label}
        </span>
        <label>
          toon{' '}
          <select
            value={String(limit)}
            onChange={(e) =>
              setLimit(e.target.value === 'all' ? 'all' : Number(e.target.value))
            }
          >
            {LIMITS.map((l) => (
              <option key={String(l)} value={String(l)}>
                {l === 'all' ? 'alle' : `top ${l}`}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="rank-scroll">
        <table className="rank-table">
          <thead>
            <tr>
              <th className="rank-num">#</th>
              <th
                className={`rank-name sortable${sortKey === 'name' ? ' sorted' : ''}`}
                onClick={() => onSort('name')}
              >
                Station{caret('name')}
              </th>
              <th>type</th>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  title={c.title}
                  className={`num sortable${sortKey === c.key ? ' sorted' : ''}`}
                  onClick={() => onSort(c.key)}
                >
                  {c.label}
                  {caret(c.key)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => {
              const chip = typeChip(r.type)
              return (
                <tr key={r.id}>
                  <td className="rank-num">{i + 1}</td>
                  <td className="rank-name">{r.name}</td>
                  <td>
                    {chip && (
                      <span className={`chip chip-${chip.toLowerCase()}`}>{chip}</span>
                    )}
                  </td>
                  {COLUMNS.map((c) => (
                    <td
                      key={c.key}
                      className={`num${sortKey === c.key ? ' sorted' : ''}`}
                    >
                      {r[c.key]}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
