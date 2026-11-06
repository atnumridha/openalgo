import type {
  ISeriesApi,
  ISeriesPrimitive,
  IPrimitivePaneRenderer,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from 'lightweight-charts'
import type { Bar } from './model'
import {
  indicatorAction,
  type IndicatorChartContext,
  type IndicatorSource,
} from './indicatorChartContext'
type DisplayEvent = IndicatorEvent & { label?: string; displaySide?: 'CALL' | 'PUT' | 'WAIT' }
import { INDICATORS, type IndicatorEvent, type NineResult } from './nineIndicators'

class IndependentMarkers implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private events: DisplayEvent[] = []
  attached(a: SeriesAttachedParameter<Time>) {
    this.attachment = a
  }
  detached() {
    this.attachment = null
  }
  set(events: DisplayEvent[]) {
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
              const placed: Array<{left:number;top:number;width:number}> = []
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
                if (x == null || y == null || x < 0 || x > size.width || y < 0 || y > size.height) continue
                const call = (event.displaySide ?? event.side) === 'CALL'
                const direction = call ? 1 : -1
                const text = `${INDICATORS.find((item) => item.key === event.key)?.short} ${event.label ?? `BUY ${event.side}`}`
                const width = c.measureText(text).width + 10
                const left = Math.max(2, Math.min(x - width / 2, size.width - width - 2))
                const clamp = (v:number) => Math.max(9, Math.min(size.height - 9, v))
                const preferred = y + direction * 18
                let top = clamp(preferred)
                // Nearby bars can collide just as same-bar signals do. Pack label
                // rectangles, while a leader preserves the exact candle anchor.
                for (let step=0;step<Math.ceil(size.height/18)*2;step++) {
                  const offset = step===0 ? 0 : Math.ceil(step/2)*18*(step%2 ? direction : -direction)
                  const candidate=clamp(preferred+offset)
                  const collision=placed.some(r=>left<r.left+r.width+2&&left+width+2>r.left&&candidate-7<r.top+10&&candidate+10>r.top-7)
                  if(!collision){top=candidate;break}
                }
                placed.push({left,top,width})
                c.strokeStyle=call?'#16a34a':'#ef4444'
                c.lineWidth=1
                c.beginPath()
                c.moveTo(x,y)
                c.lineTo(left+width/2,top-direction*7)
                c.stroke()
                c.fillStyle = call ? '#075a43' : '#8c2430'
                c.fillRect(left, top - 7, width, 15)
                c.fillStyle = '#ffffff'
                c.fillText(text, left + width/2, top)
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
    bars: Bar[],
    display?: { chart: IndicatorChartContext; source: IndicatorSource }
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
        .filter((e) => display?.chart.kind !== 'option' || anchors.has(e.time))
        .sort((a, b) => a.time - b.time)
        .map((event) => {
          const anchor = anchors.get(event.time)
          const action = display
            ? indicatorAction(event.side, display.chart, display.source, event.key)
            : undefined
          const side = action?.side ?? event.side
          return {
            ...event,
            label: action?.label,
            displaySide: side,
            price: anchor ? (side === 'CALL' ? anchor.low : anchor.high) : event.price,
          }
        })
    )
  }
}
