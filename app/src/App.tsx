import { useEffect, useState } from 'react'
import SchematicView from './SchematicView'
import GeoView from './GeoView'
import { loadStations } from './data'
import { PAGE_LABELS, type Station } from './types'

type View = 'schematic' | 'geo'

export default function App() {
  const [stations, setStations] = useState<Station[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>('schematic')
  const [page, setPage] = useState(1)
  // The geo view mounts on first visit and then stays mounted (hidden via
  // CSS) so its state survives tab switches.
  const [geoMounted, setGeoMounted] = useState(false)

  useEffect(() => {
    loadStations()
      .then((f) => setStations(f.stations))
      .catch((e) => setError(String(e)))
  }, [])

  if (error) return <p className="error">FAIL: {error}</p>
  if (!stations) return <p className="muted">Laden...</p>

  return (
    <div className="app">
      <header>
        <h1>Spoorkaart 2026</h1>
        <nav className="tabs">
          {[1, 2, 3, 4].map((p) => (
            <button
              key={p}
              className={view === 'schematic' && page === p ? 'active' : ''}
              onClick={() => {
                setView('schematic')
                setPage(p)
              }}
            >
              {PAGE_LABELS[p]}
            </button>
          ))}
          <button
            className={view === 'geo' ? 'active' : ''}
            onClick={() => {
              setView('geo')
              setGeoMounted(true)
            }}
          >
            geo
          </button>
        </nav>
      </header>
      {view === 'schematic' && <SchematicView page={page} stations={stations} />}
      {geoMounted && (
        <div className={view === 'geo' ? '' : 'view-hidden'}>
          <GeoView stations={stations} active={view === 'geo'} />
        </div>
      )}
    </div>
  )
}
