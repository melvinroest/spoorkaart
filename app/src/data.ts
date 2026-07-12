import type { StationsFile, SeriesFile } from './types'

export interface SeriesResult {
  file: SeriesFile
  source: 'kaart' | 'gtfs'
}

export async function loadStations(): Promise<StationsFile> {
  const res = await fetch('/data/stations.json')
  if (!res.ok) throw new Error(`stations.json: HTTP ${res.status}`)
  return res.json()
}

async function fetchJson(path: string): Promise<SeriesFile | null> {
  const res = await fetch(path)
  // Vite dev serves index.html for missing files, so check the content type too.
  if (!res.ok || !res.headers.get('content-type')?.includes('json')) return null
  return res.json()
}

export async function loadSeries(page: number): Promise<SeriesResult | null> {
  const map = await fetchJson(`/data/page${page}.series.json`)
  if (map) return { file: map, source: 'kaart' }
  const gtfs = await fetchJson(`/data/gtfs/page${page}.series.json`)
  if (gtfs) return { file: gtfs, source: 'gtfs' }
  return null
}

// Serie id -> product (Intercity, Sprinter, ...) unioned over the four GTFS
// windows. The map-extraction files carry no product field, so this is the
// product source when the kaart file is the active series source.
export async function loadProductMap(): Promise<Record<string, string>> {
  const out: Record<string, string> = {}
  const files = await Promise.all(
    [1, 2, 3, 4].map((p) => fetchJson(`/data/gtfs/page${p}.series.json`)),
  )
  for (const f of files) {
    if (!f) continue
    for (const s of f.series) {
      if (s.product && !(s.id in out)) out[s.id] = s.product
    }
  }
  return out
}

export async function loadSerieColors(): Promise<Record<string, string>> {
  const res = await fetch('/data/serie-colors.json')
  if (!res.ok || !res.headers.get('content-type')?.includes('json')) return {}
  return res.json()
}

export interface HighlightPath {
  d: string
  w: number
  dash: string
}

export async function loadHighlights(
  page: number,
): Promise<Record<string, HighlightPath[]>> {
  const res = await fetch(`/data/highlights/page${page}.json`)
  if (!res.ok || !res.headers.get('content-type')?.includes('json')) return {}
  return res.json()
}

export async function loadMapSvg(page: number): Promise<string> {
  const res = await fetch(`/map/page${page}.svg`)
  if (!res.ok) throw new Error(`page${page}.svg: HTTP ${res.status}`)
  return res.text()
}
