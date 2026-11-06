import type {
  IPriceLine,
  IPrimitivePaneRenderer,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from 'lightweight-charts'
import { CandleMarkers, type Marker } from './CandleProbabilityLayer'
import { chooseVideoSetup, VIDEO_STRATEGIES } from './videoStrategyGuide.js'
import type { VideoBar, VideoEvent, VideoGuideResult, VideoStrategyId } from './videoStrategyTypes'
export interface VideoDisplay {
  first: number
  last: number
  showPending: boolean
  showAll: boolean
}
export function videoGuideMarkers(
  result: VideoGuideResult,
  bars: readonly VideoBar[],
  view: VideoDisplay
): Marker[] {
  if (!result.available) return []
  const anchors = new Map(bars.map((b) => [b.time, b]))
  const recent = bars[Math.max(0, bars.length - 10)]?.time ?? view.first
  const first = view.showAll ? view.first : Math.max(view.first, recent)
  return result.events
    .flatMap((e) => {
      const time = e.entryBar ?? e.confirmedBar ?? e.barTime
      const bar = anchors.get(time)
      if (
        !bar ||
        time < first ||
        time > view.last ||
        (!view.showPending && e.status === 'watching')
      )
        return []
      if (!e.confirmedAt && !view.showPending) return []
      const bull = e.side > 0,
        name = VIDEO_STRATEGIES[e.kind].name
      return [
        {
          time,
          price: bull ? bar.low : bar.high,
          text: `${name} · ${e.entryAt ? 'condition observed' : 'observation'}`,
          above: !bull,
          color: bull ? '#34d399' : '#f87171',
          textColor: bull ? '#34d399' : '#f87171',
          background: '#111827',
          pointer: true,
          tooltip: `${name}: ${e.reason}`,
        },
      ]
    })
    .slice(-40)
}
class SelectedVideoZone implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private event: VideoEvent | null = null
  private last = 0
  attached(a: SeriesAttachedParameter<Time>) {
    this.attachment = a
  }
  detached() {
    this.attachment = null
  }
  set(event: VideoEvent | null, last: number) {
    this.event = event
    this.last = last
    this.attachment?.requestUpdate()
  }
  paneViews() {
    return [
      {
        zOrder: () => 'bottom' as const,
        renderer: () => ({
          draw: (target: Parameters<IPrimitivePaneRenderer['draw']>[0]) => {
            const a = this.attachment,
              e = this.event
            if (!a || !e || e.high <= e.low) return
            target.useMediaCoordinateSpace(({ context: c, mediaSize: s }) => {
              const x = a.chart
                  .timeScale()
                  .timeToCoordinate((e.confirmedBar ?? e.barTime) as UTCTimestamp),
                right = a.chart.timeScale().timeToCoordinate(this.last as UTCTimestamp),
                y1 = a.series.priceToCoordinate(e.high),
                y2 = a.series.priceToCoordinate(e.low)
              if (x == null || right == null || y1 == null || y2 == null) return
              c.save()
              c.beginPath()
              c.rect(0, 0, s.width, s.height)
              c.clip()
              c.fillStyle = e.side > 0 ? 'rgba(52,211,153,0.12)' : 'rgba(248,113,113,0.12)'
              c.strokeStyle = e.side > 0 ? '#34d399' : '#f87171'
              c.setLineDash([4, 3])
              const left = Math.max(0, x),
                width = Math.min(s.width, right) - left
              if (width > 0) {
                c.fillRect(left, Math.min(y1, y2), width, Math.abs(y2 - y1))
                c.strokeRect(left, Math.min(y1, y2), width, Math.abs(y2 - y1))
              }
              c.restore()
            })
          },
        }),
      },
    ]
  }
}
export class VideoStrategyLayer {
  private readonly price: ISeriesApi<'Candlestick'>
  private readonly markers = new CandleMarkers(12)
  private readonly zone = new SelectedVideoZone()
  private lines: IPriceLine[] = []
  private key = ''
  constructor(price: ISeriesApi<'Candlestick'>) {
    this.price = price
    price.attachPrimitive(this.markers)
    price.attachPrimitive(this.zone)
  }
  update(
    result: VideoGuideResult,
    selectedId: VideoStrategyId | '',
    bars: VideoBar[],
    view: VideoDisplay
  ) {
    const picked = chooseVideoSetup(result, selectedId).event
    this.markers.set(
      videoGuideMarkers(
        { ...result, events: result.events.filter((e) => e.strategy === picked?.strategy) },
        bars,
        view
      ),
      bars.map((b) => ({ ...b, volume: b.volume ?? 0 }))
    )
    const e =
      result.available &&
      picked &&
      ['waiting', 'entry', 'unpriced', ...(view.showPending ? ['watching'] : [])].includes(
        picked.status
      )
        ? picked
        : null
    this.zone.set(e, view.last)
    const levels = e?.priced
      ? ([
          ['Guide watch', e.watch, '#94a3b8'],
          ['Guide close ref', e.entry, '#3b82f6'],
          ['Guide SL', e.stop, '#ef4444'],
          ['Guide target', e.target, '#22c55e'],
        ] as const)
      : []
    const key = JSON.stringify(levels)
    if (key === this.key) return
    for (const line of this.lines) this.price.removePriceLine(line)
    this.lines = []
    this.key = key
    for (const [title, price, color] of levels)
      if (price != null)
        this.lines.push(
          this.price.createPriceLine({
            title,
            price,
            color,
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
          })
        )
  }
  destroy() {
    for (const line of this.lines) this.price.removePriceLine(line)
    this.lines = []
    this.price.detachPrimitive?.(this.markers)
    this.price.detachPrimitive?.(this.zone)
  }
}
