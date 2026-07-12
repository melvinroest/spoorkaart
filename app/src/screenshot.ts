import { toBlob } from 'html-to-image'

export type ShotResult = 'clipboard' | 'download' | 'failed'

// Renders the element to a PNG at 2x and puts it on the clipboard; falls back
// to a file download when the clipboard is unavailable (unfocused document,
// missing permission). OSM tiles are re-fetched over CORS by html-to-image,
// so the Leaflet layer captures without tainting.
export async function screenshot(el: HTMLElement): Promise<ShotResult> {
  // scrollWidth/Height include children that overflow the container's own
  // box (the geo panel does, past the app's max-width), which the default
  // clientWidth-sized canvas would clip.
  const width = Math.max(el.scrollWidth, el.offsetWidth)
  const height = Math.max(el.scrollHeight, el.offsetHeight)
  const blob = await toBlob(el, {
    width,
    height,
    pixelRatio: 2,
    backgroundColor: getComputedStyle(document.body).backgroundColor,
    style: { margin: '0' },
    filter: (node) =>
      !(node instanceof HTMLElement && node.classList.contains('shot-btn')),
  })
  if (!blob) return 'failed'
  try {
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
    return 'clipboard'
  } catch {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `spoorkaart-${new Date().toISOString().replace(/[:.]/g, '-')}.png`
    a.click()
    URL.revokeObjectURL(a.href)
    return 'download'
  }
}
