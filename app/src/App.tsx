import { useEffect, useRef, useState } from 'react'
import SchematicView from './SchematicView'
import GeoView from './GeoView'
import { hasMapArtwork, loadStations } from './data'
import { screenshot, type ShotResult } from './screenshot'
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
  // Public deploys ship without the NS map artwork; the schematic tabs hide
  // and the geo view becomes the whole app.
  const [artwork, setArtwork] = useState<boolean | null>(null)
  const [shot, setShot] = useState<ShotResult | 'busy' | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  const takeShot = async () => {
    if (!rootRef.current || shot === 'busy') return
    setShot('busy')
    const result = await screenshot(rootRef.current).catch(
      (): ShotResult => 'failed',
    )
    setShot(result)
    setTimeout(() => setShot(null), 2500)
  }

  useEffect(() => {
    loadStations()
      .then((f) => setStations(f.stations))
      .catch((e) => setError(String(e)))
    hasMapArtwork().then((ok) => {
      setArtwork(ok)
      if (!ok) {
        setView('geo')
        setGeoMounted(true)
      }
    })
  }, [])

  if (error) return <p className="error">FAIL: {error}</p>
  if (!stations) return <p className="muted">Laden...</p>

  return (
    <div className="app" ref={rootRef}>
      <header>
        <h1>Spoorkaart 2026</h1>
        <nav className="tabs">
          {artwork !== false &&
            [1, 2, 3, 4].map((p) => (
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
        <button className="shot-btn" onClick={takeShot} disabled={shot === 'busy'}>
          {shot === 'busy'
            ? 'bezig...'
            : shot === 'clipboard'
              ? 'gekopieerd'
              : shot === 'download'
                ? 'gedownload'
                : shot === 'failed'
                  ? 'mislukt'
                  : 'screenshot'}
        </button>
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
