import type { MinutesFile, ShapesFile, StationsFile, SeriesFile } from './types'

// Deploy base ('/' in dev, '/spoorkaart/' on GitHub Pages); always ends in /.
const BASE = import.meta.env.BASE_URL

export interface SeriesResult {
  file: SeriesFile
  source: 'kaart' | 'gtfs'
}

export async function loadStations(): Promise<StationsFile> {
  const res = await fetch(`${BASE}data/stations.json`)
  if (!res.ok) throw new Error(`stations.json: HTTP ${res.status}`)
  return res.json()
}

async function fetchJson<T>(path: string): Promise<T | null> {
  const res = await fetch(path)
  // Vite dev serves index.html for missing files, so check the content type too.
  if (!res.ok || !res.headers.get('content-type')?.includes('json')) return null
  return res.json()
}

export async function loadSeries(page: number): Promise<SeriesResult | null> {
  const map = await fetchJson<SeriesFile>(`${BASE}data/page${page}.series.json`)
  if (map) return { file: map, source: 'kaart' }
  const gtfs = await fetchJson<SeriesFile>(`${BASE}data/gtfs/page${page}.series.json`)
  if (gtfs) return { file: gtfs, source: 'gtfs' }
  return null
}

// The time engine always runs on the GTFS-derived files: minutes arrays are
// index-aligned with THEIR stop arrays, not with the map extraction's.
export async function loadGtfsSeries(page: number): Promise<SeriesFile | null> {
  return fetchJson<SeriesFile>(`${BASE}data/gtfs/page${page}.series.json`)
}

export async function loadMinutes(page: number): Promise<MinutesFile | null> {
  return fetchJson<MinutesFile>(`${BASE}data/gtfs/page${page}.minutes.json`)
}

export async function loadShapes(page: number): Promise<ShapesFile | null> {
  return fetchJson<ShapesFile>(`${BASE}data/gtfs/page${page}.shapes.json`)
}

// Serie id -> product (Intercity, Sprinter, ...) unioned over the four GTFS
// windows. The map-extraction files carry no product field, so this is the
// product source when the kaart file is the active series source.
export async function loadProductMap(): Promise<Record<string, string>> {
  const out: Record<string, string> = {}
  const files = await Promise.all(
    [1, 2, 3, 4].map((p) =>
      fetchJson<SeriesFile>(`${BASE}data/gtfs/page${p}.series.json`),
    ),
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
  const res = await fetch(`${BASE}data/serie-colors.json`)
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
  const res = await fetch(`${BASE}data/highlights/page${page}.json`)
  if (!res.ok || !res.headers.get('content-type')?.includes('json')) return {}
  return res.json()
}

export async function loadMapSvg(page: number): Promise<string> {
  const res = await fetch(`${BASE}map/page${page}.svg`)
  if (!res.ok) throw new Error(`page${page}.svg: HTTP ${res.status}`)
  return res.text()
}

// The schematic view needs the NS map artwork, which is not part of the
// public repo (NS copyright). Probe it so the app can hide those tabs.
export async function hasMapArtwork(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}map/page1.svg`, { method: 'HEAD' })
    return res.ok && !res.headers.get('content-type')?.includes('html')
  } catch {
    return false
  }
}
