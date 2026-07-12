export function haversineKm(a: [number, number], b: [number, number]): number {
  const rad = Math.PI / 180
  const dLat = (b[0] - a[0]) * rad
  const dLon = (b[1] - a[1]) * rad
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(dLon / 2) ** 2
  return 2 * 6371 * Math.asin(Math.sqrt(h))
}

function checkLatLon(lat: number, lon: number): [number, number] | null {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null
  return [lat, lon]
}

// Accepts "52.09052, 5.12108", Dutch decimal commas, and Google Maps URLs.
// URL forms, in order of authority: the place pin (!3d<lat>!4d<lon>), the
// viewport center (/@lat,lon,zoom), and q= / ll= style query params.
// Short links (maps.app.goo.gl) hide the coordinate behind a redirect and
// cannot be resolved client-side; those stay invalid.
export function parseLatLon(text: string): [number, number] | null {
  const t = text.trim()
  let m = t.match(/!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/)
  if (m) return checkLatLon(parseFloat(m[1]), parseFloat(m[2]))
  m = t.match(/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/)
  if (m) return checkLatLon(parseFloat(m[1]), parseFloat(m[2]))
  m = t.match(/[?&](?:q|ll|query|center|destination)=(?:loc:)?(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)/)
  if (m) return checkLatLon(parseFloat(m[1]), parseFloat(m[2]))
  m = t.match(/^(-?\d+(?:[.,]\d+)?)[\s,;]+(-?\d+(?:[.,]\d+)?)$/)
  if (m)
    return checkLatLon(
      parseFloat(m[1].replace(',', '.')),
      parseFloat(m[2].replace(',', '.')),
    )
  return null
}
