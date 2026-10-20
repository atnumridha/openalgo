import type {
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from 'lightweight-charts'
import type { GapZone } from './tradingViewStudies'
import { layoutChartLabels } from '../kotak-assistant/chartLabels'

export class TradingViewZones implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private zones: GapZone[] = []
  private dark: boolean
  constructor(dark = false) {
    this.dark = dark
  }
  private paint(target: Parameters<IPrimitivePaneRenderer['draw']>[0], labels: boolean) {
    const a = this.attachment
    if (!a) return
    // biome-ignore lint/correctness/useHookAtTopLevel: FancyCanvas coordinate-space API is not a React hook
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      const visible = this.zones.flatMap((zone) => {
        const start = a.chart.timeScale().timeToCoordinate(zone.time as UTCTimestamp)
        const end = a.chart.timeScale().timeToCoordinate(zone.end as UTCTimestamp)
        const top = a.series.priceToCoordinate(zone.high),
          bottom = a.series.priceToCoordinate(zone.low)
        if (top == null || bottom == null || end == null) return []
        const x = Math.max(0, start ?? 0),
          right = Math.min(mediaSize.width, end)
        const y = Math.max(0, top),
          height = Math.min(mediaSize.height, bottom) - y
        return right > x && height > 0 ? [{ zone, x, right, y, height }] : []
      })
      context.save()
      context.beginPath()
      context.rect(0, 0, mediaSize.width, mediaSize.height)
      context.clip()
      if (!labels) {
        for (const { zone, x, right, y, height } of visible) {
          context.fillStyle = zone.bullish ? 'rgba(16,185,129,0.06)' : 'rgba(244,63,94,0.06)'
          context.strokeStyle = zone.bullish ? 'rgba(16,185,129,0.65)' : 'rgba(244,63,94,0.65)'
          context.lineWidth = 1
          context.fillRect(x, y, right - x, height)
          context.strokeRect(x, y, right - x, height)
        }
      } else {
        const positions = layoutChartLabels(
          visible.map(({ zone, y, height }, i) => ({
            title: String(i),
            price: zone.low,
            color: '',
            y: y + height / 2,
          })),
          mediaSize.height
        )
        context.font = '600 11px Inter, system-ui, sans-serif'
        context.textBaseline = 'middle'
        for (const label of positions) {
          const { zone, right } = visible[Number(label.title)]
          const text = `${zone.bullish ? '↑' : '↓'} FVG`
          const width = context.measureText(text).width + 8
          const x = Math.max(4, Math.min(right - width - 4, mediaSize.width - width - 4))
          context.strokeStyle = zone.bullish ? '#10b981' : '#f43f5e'
          context.beginPath()
          context.moveTo(right, label.y)
          context.lineTo(x + width, label.top + 11)
          context.stroke()
          context.fillStyle = this.dark ? '#111827' : '#ffffff'
          context.fillRect(x, label.top, width, 22)
          context.fillStyle = zone.bullish
            ? this.dark
              ? '#6ee7b7'
              : '#047857'
            : this.dark
              ? '#fda4af'
              : '#be123c'
          context.fillText(text, x + 4, label.top + 11)
        }
      }
      context.restore()
    })
  }
  private renderer: IPrimitivePaneRenderer = {
    draw: (target) => this.paint(target, false),
  }
  private view: IPrimitivePaneView = { zOrder: () => 'bottom', renderer: () => this.renderer }
  private labelView: IPrimitivePaneView = {
    zOrder: () => 'top',
    renderer: () => ({ draw: (target) => this.paint(target, true) }),
  }
  attached(parameter: SeriesAttachedParameter<Time>) {
    this.attachment = parameter
  }
  detached() {
    this.attachment = null
  }
  paneViews() {
    return [this.view, this.labelView]
  }
  setZones(zones: GapZone[]) {
    this.zones = zones
    this.attachment?.requestUpdate()
  }
}
