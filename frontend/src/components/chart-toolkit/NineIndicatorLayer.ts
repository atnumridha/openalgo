import type {
  ISeriesApi,
  ISeriesPrimitive,
  IPrimitivePaneRenderer,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from 'lightweight-charts'
import type { Bar } from './model'
import { INDICATORS, type IndicatorEvent, type NineResult } from './nineIndicators'

class IndependentMarkers implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private events: IndicatorEvent[] = []
  attached(a: SeriesAttachedParameter<Time>) {
    this.attachment = a
  }
  detached() {
    this.attachment = null
  }
  set(events: IndicatorEvent[]) {
    this.events = events
    this.attachment?.requestUpdate()
  }
  paneViews() {
    return [
      {
        zOrder: () => 'top' as const,
        renderer: () => ({
          draw: (target: Parameters<IPrimitivePaneRenderer['draw']>[0]) => {
            const a = this.attachment
            if (!a || !this.events.length) return
            // biome-ignore lint/correctness/useHookAtTopLevel: FancyCanvas coordinate API
            target.useMediaCoordinateSpace(({ context: c, mediaSize: size }) => {
              const lanes = new Map<string, number>()
              c.save()
              c.beginPath()
              c.rect(0, 0, size.width, size.height)
              c.clip()
              c.font = '600 10px Inter, system-ui, sans-serif'
              c.textAlign = 'center'
              c.textBaseline = 'middle'
              for (const event of this.events) {
                const x = a.chart.timeScale().timeToCoordinate(event.time as UTCTimestamp),
                  y = a.series.priceToCoordinate(event.price)
                if (x == null || y == null || x < -65 || x > size.width + 65) continue
                const key = `${event.time}:${event.side}`,
                  lane = lanes.get(key) ?? 0
                lanes.set(key, lane + 1)
                const call = event.side === 'CALL',
                  top = y + (call ? 1 : -1) * (18 + lane * 18)
                const text = `${INDICATORS.find((item) => item.key === event.key)?.short} BUY ${event.side}`
                const width = c.measureText(text).width + 10
                c.fillStyle = call ? '#075a43' : '#8c2430'
                c.fillRect(x - width / 2, top - 7, width, 15)
                c.fillStyle = '#ffffff'
                c.fillText(text, x, top)
              }
              c.restore()
            })
          },
        }),
      },
    ]
  }
}
export class NineIndicatorLayer {
  private markers = new IndependentMarkers()
  private attached = false
  private price: ISeriesApi<'Candlestick'>
  constructor(price: ISeriesApi<'Candlestick'>) {
    this.price = price
  }
  update(
    result: NineResult | null,
    enabled: string[],
    first: number,
    last: number,
    proxy: NineResult | null,
    bars: Bar[]
  ) {
    if (result && !this.attached) {
      this.price.attachPrimitive(this.markers)
      this.attached = true
    }
    const nativeMfi = result?.states.find((s) => s.key === 'mfi')?.value
    const useProxy = nativeMfi == null && proxy != null
    const events = result
      ? [
          ...result.events.filter((e) => !useProxy || e.key !== 'mfi'),
          ...(useProxy ? proxy.events.filter((e) => e.key === 'mfi') : []),
        ]
      : []
    const anchors = new Map(bars.map((b) => [b.time, b]))
    this.markers.set(
      events
        .filter((e) => enabled.includes(`nine-${e.key}`) && e.time >= first && e.time <= last)
        .sort((a, b) => a.time - b.time)
        .map((event) => {
          const anchor = anchors.get(event.time)
          return anchor
            ? { ...event, price: event.side === 'CALL' ? anchor.low : anchor.high }
            : event
        })
    )
  }
}
