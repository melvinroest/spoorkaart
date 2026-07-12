export interface Station {
  id: string
  name: string
  nameAsPrinted?: string
  country: 'NL' | 'DE' | 'BE' | 'FR' | 'GB'
  major?: boolean
  suspect?: boolean
  coords?: Record<string, [number, number]>
  geo?: [number, number]
  code?: string
  type?: string
}

export interface StationsFile {
  schemaVersion: 1
  source: string
  stations: Station[]
}

export interface Route {
  stops: string[]
  via?: string[]
  note?: string
}

export interface SeriesException {
  type: string
  station?: string
  note: string
}

export interface Series {
  id: string
  kind: 'binnenland' | 'internationaal' | 'buitenland'
  product?: string
  frequency: { class: string; note: string }
  routes: Route[]
  exceptions?: SeriesException[]
  colorHint?: string
  confidence: 'high' | 'medium' | 'low'
  issues?: string[]
}

export interface SeriesFile {
  schemaVersion: 1
  page: number
  timeWindow: string
  series: Series[]
}

export const PAGE_LABELS: Record<number, string> = {
  1: 'ma-do tot 20u',
  2: 'vrijdag tot 20u',
  3: 'weekend tot 20u',
  4: 'ma-zo na 20u',
}
