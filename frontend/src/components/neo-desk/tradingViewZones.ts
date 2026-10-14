import type {
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from 'lightweight-charts'
import type { GapZone } from './tradingViewStudies'

export class TradingViewZones implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private zones: GapZone[] = []
  private renderer: IPrimitivePaneRenderer = {
    draw: (target) => {
      const a = this.attachment
      if (!a) return
      // biome-ignore lint/correctness/useHookAtTopLevel: FancyCanvas coordinate-space API is not a React hook
      target.useMediaCoordinateSpace(({ context, mediaSize }) => {
        for (const zone of this.zones) {
          const start = a.chart.timeScale().timeToCoordinate(zone.time as UTCTimestamp),
            end = a.chart.timeScale().timeToCoordinate(zone.end as UTCTimestamp),
            top = a.series.priceToCoordinate(zone.high),
            bottom = a.series.priceToCoordinate(zone.low)
          if (top == null || bottom == null || end == null) continue
          const x = Math.max(0, start ?? 0),
            width = Math.min(mediaSize.width, end) - x
          if (width <= 0) continue
          context.fillStyle = zone.bullish ? 'rgba(38,166,154,0.08)' : 'rgba(239,83,80,0.08)'
          context.strokeStyle = zone.bullish ? 'rgba(38,166,154,0.38)' : 'rgba(239,83,80,0.38)'
          context.lineWidth = 1
          context.fillRect(x, top, width, bottom - top)
          context.strokeRect(x, top, width, bottom - top)
        }
      })
    },
  }
  private view: IPrimitivePaneView = { zOrder: () => 'bottom', renderer: () => this.renderer }
  attached(parameter: SeriesAttachedParameter<Time>) {
    this.attachment = parameter
  }
  detached() {
    this.attachment = null
  }
  paneViews() {
    return [this.view]
  }
  setZones(zones: GapZone[]) {
    this.zones = zones
    this.attachment?.requestUpdate()
  }
}
