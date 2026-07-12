import type { MinutesFile, SeriesFile } from './types'

// Transfer penalty model: platform walk plus the expected wait for leg two,
// which is half the headway of the serie boarded there. When a serie has no
// measurable headway (fewer than two departures on the reference day) we
// assume hourly-or-worse service.
const TRANSFER_WALK_MIN = 4
const FALLBACK_HEADWAY_MIN = 60

export interface PairTimes {
  direct: number | null
  // Best door-to-door time with exactly one transfer: leg one, walk plus
  // half the headway of leg two's serie, leg two. Null when nothing connects.
  transfer: number | null
}

export interface TimeIndex {
  // Fastest direct time in minutes between two stations, null when no route
  // of the window carries both (or the minutes chain is broken there).
  direct: (a: string, b: string) => number | null
  fastest1: (a: string, b: string) => PairTimes
  headway: (serie: string) => number | null
}

interface RouteEntry {
  serie: string
  pos: Map<string, number>
  arr: (number | null)[]
  dep: (number | null)[]
}

export function buildTimeIndex(
  series: SeriesFile,
  minutes: MinutesFile,
): TimeIndex {
  const entries: RouteEntry[] = []
  const byStation = new Map<string, number[]>()
  for (const s of series.series) {
    const m = minutes.series[s.id]
    if (!m || m.routes.length !== s.routes.length) continue
    s.routes.forEach((r, i) => {
      const mr = m.routes[i]
      if (!mr || mr.arr.length !== r.stops.length) return
      const idx = entries.length
      entries.push({
        serie: s.id,
        pos: new Map(r.stops.map((st, j) => [st, j])),
        arr: mr.arr,
        dep: mr.dep,
      })
      for (const st of r.stops) {
        const list = byStation.get(st)
        if (list) list.push(idx)
        else byStation.set(st, [idx])
      }
    })
  }

  const entryTime = (e: RouteEntry, a: string, b: string): number | null => {
    const pa = e.pos.get(a)
    const pb = e.pos.get(b)
    if (pa === undefined || pb === undefined) return null
    const lo = Math.min(pa, pb)
    const hi = Math.max(pa, pb)
    const t0 = e.dep[lo]
    const t1 = e.arr[hi]
    if (t0 === null || t1 === null) return null
    const t = t1 - t0
    return t >= 0 ? t : null
  }

  const direct = (a: string, b: string): number | null => {
    if (a === b) return 0
    const la = byStation.get(a)
    const lb = byStation.get(b)
    if (!la || !lb) return null
    const scan = la.length <= lb.length ? la : lb
    let best: number | null = null
    for (const i of scan) {
      const t = entryTime(entries[i], a, b)
      if (t !== null && (best === null || t < best)) best = t
    }
    return best
  }

  const headway = (serie: string): number | null =>
    minutes.series[serie]?.headwayMinutes ?? null

  const penalty = (serie: string): number =>
    TRANSFER_WALK_MIN + (headway(serie) ?? FALLBACK_HEADWAY_MIN) / 2

  // All stations directly reachable from a, with the fastest leg-one time.
  const reachCache = new Map<string, Map<string, number>>()
  const reach = (a: string): Map<string, number> => {
    const hit = reachCache.get(a)
    if (hit) return hit
    const out = new Map<string, number>()
    for (const i of byStation.get(a) ?? []) {
      const e = entries[i]
      for (const st of e.pos.keys()) {
        if (st === a) continue
        const t = entryTime(e, a, st)
        if (t === null) continue
        const cur = out.get(st)
        if (cur === undefined || t < cur) out.set(st, t)
      }
    }
    if (reachCache.size > 16) reachCache.clear()
    reachCache.set(a, out)
    return out
  }

  const fastest1 = (a: string, b: string): PairTimes => {
    const d = direct(a, b)
    let best: number | null = null
    if (a !== b) {
      const lb = byStation.get(b)
      if (lb) {
        const leg1 = reach(a)
        for (const i of lb) {
          const e = entries[i]
          const pen = penalty(e.serie)
          for (const x of e.pos.keys()) {
            if (x === b || x === a) continue
            const t1 = leg1.get(x)
            if (t1 === undefined) continue
            const t2 = entryTime(e, x, b)
            if (t2 === null) continue
            const total = t1 + pen + t2
            if (best === null || total < best) best = total
          }
        }
      }
    }
    return { direct: d, transfer: best }
  }

  return { direct, fastest1, headway }
}
