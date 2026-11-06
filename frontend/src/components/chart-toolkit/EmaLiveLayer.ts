import type { ISeriesApi, UTCTimestamp, SeriesMarker } from 'lightweight-charts'
import type { Bar } from './model'
import { loadEmaBackfill, type EmaBackfill } from './emaBackfill'
import { emaAlignmentEvents, contiguousEmaBars } from './emaCross'
/** Historical averages run on the server. Only the latest candle is adjusted locally. */
export class EmaLiveLayer {
  private key = ''
  private data: EmaBackfill | null = null
  private controller: AbortController | null = null
  private generation = 0
  private pending = false
  private retryAt = 0
  private painted = ''
  private active = false
  private latest: { time: number; close: number }[] = []
  private baselineThrough = -Infinity
  private first = 0
  private last = 0
  private fast: ISeriesApi<'Line'>
  private slow: ISeriesApi<'Line'>
  private ema21?: ISeriesApi<'Line'>
  private closedThrough = -Infinity
  private revisionToken = ''
  private paintedMarkers = ''
  private markers?: (markers: SeriesMarker<UTCTimestamp>[]) => void
  constructor(fast: ISeriesApi<'Line'>, slow: ISeriesApi<'Line'>, markers?: (markers: SeriesMarker<UTCTimestamp>[]) => void, ema21?: ISeriesApi<'Line'>) {
    this.markers = markers
    this.fast = fast
    this.slow = slow
    this.ema21 = ema21
  }
  update(bars: readonly Bar[], enabled: boolean, first: number, last: number, closedThrough = -Infinity, seconds = 0, historyRevision?: number, markerIntervalSeconds = seconds) {
    this.closedThrough = closedThrough
    if (!enabled) {
      if (this.active) {
        this.destroy()
        for (const series of [this.fast, this.slow, ...(this.ema21 ? [this.ema21] : [])]) {
          series.setData([])
          series.applyOptions({ visible: false })
        }
      }
      this.active = false
      return
    }
    const tail = bars.at(-1), previous = bars.at(-2)
    const token = historyRevision === undefined ? '' : JSON.stringify([historyRevision,bars.length,bars[0]?.time,tail?.time,previous?.time,previous?.open,previous?.high,previous?.low,previous?.close,seconds,markerIntervalSeconds,closedThrough,tail && tail.time <= closedThrough ? [tail.open,tail.high,tail.low,tail.close] : null])
    if (this.active && this.data && token && token === this.revisionToken) {
      this.latest = tail ? [{time:tail.time,close:tail.close}] : []
      this.first=first;this.last=last;this.paint();return
    }
    this.revisionToken = token
    this.active = true
    const source = seconds > 0 ? contiguousEmaBars(bars,seconds) : bars
    this.latest = source.map((b) => ({ time: b.time, open:b.open, high:b.high, low:b.low, close: b.close }))
    this.first = first
    this.last = last
    // closedThrough is the last closed candle's OPEN time. It can include the
    // final candle even before the next forming candle arrives.
    const baseline = Number.isFinite(closedThrough)
      ? this.latest.filter(b => b.time <= closedThrough)
      : this.latest.slice(0, -1)
    this.baselineThrough = baseline.at(-1)?.time ?? -Infinity
    const key = JSON.stringify([seconds, markerIntervalSeconds, baseline])
    if (key !== this.key) {
      this.markers?.([])
      this.key = key
      this.data = null
      this.painted = ''
      this.controller?.abort()
      this.pending = false
      this.retryAt = 0
    }
    if (this.data) {
      this.paint()
      return
    }
    if (this.pending || Date.now() < this.retryAt) return
    this.pending = true
    const generation = ++this.generation,
      controller = new AbortController()
    this.controller = controller
    void loadEmaBackfill(baseline, controller.signal, { intervalSeconds: markerIntervalSeconds, ...(seconds === 0 && markerIntervalSeconds > 0 ? { allowSessionGaps: true } : {}) })
      .then((data) => {
        if (
          generation !== this.generation ||
          controller.signal.aborted ||
          !this.active ||
          this.key !== key
        )
          return
        this.data = data
        this.pending = false
        this.paint()
      })
      .catch(() => {
        if (generation !== this.generation || controller.signal.aborted) return
        this.pending = false
        this.retryAt = Date.now() + 2000
        for (const series of [this.fast, this.slow, ...(this.ema21 ? [this.ema21] : [])]) series.setData([])
      })
  }
  private paint() {
    if (!this.data) return
    const windowKey = `${this.generation}:${this.first}:${this.last}`
    const tail = this.latest.at(-1)
    const latest = tail && tail.time > this.baselineThrough ? tail : undefined
    for (const [period, series, name] of [
      [9, this.fast, 'EMA 9'],
      [15, this.slow, 'EMA 15'],
      [21, this.ema21, 'EMA 21'],
    ] as const) {
      if (!series) continue
      const seed = this.data[String(period) as '9' | '15' | '21']
      if (!seed) {
        series.setData([])
        series.applyOptions({ visible: false })
        continue
      }
      const value =
        latest && Number.isFinite(latest.close) && latest.close > 0
          ? seed.value !== null
            ? seed.value + (2 / (period + 1)) * (latest.close - seed.value)
            : seed.count + 1 === period
              ? (seed.sum + latest.close) / period
              : null
          : null
      const point = latest && value !== null ? { time: latest.time as UTCTimestamp, value } : null
      const visible = point && point.time >= this.first && point.time <= this.last ? point : null
      if (this.painted !== windowKey) {
        series.setData([
          ...seed.points
            .filter((p) => p.time >= this.first && p.time <= this.last)
            .map((p) => ({ ...p, time: p.time as UTCTimestamp })),
          ...(visible ? [visible] : []),
        ])
        series.applyOptions({ visible: true, title: name, lastValueVisible: true })
      } else if (visible) series.update(visible)
    }
    const markerKey = `${windowKey}:${this.closedThrough}`
    if (markerKey !== this.paintedMarkers) {
      this.markers?.(emaAlignmentEvents(this.data,this.closedThrough).filter(p=>p.time>=this.first&&p.time<=this.last).map(p=>({time:p.time as UTCTimestamp,position:'atPriceMiddle',price:p.value,shape:'circle',size:0,text:'×',color:p.side==='up'?'#22c55e':'#ef4444',id:`ema-alignment-${p.time}`})))
      this.paintedMarkers = markerKey
    }
    this.painted = windowKey
  }
  destroy() {
    this.markers?.([])
    this.revisionToken = ''
    this.paintedMarkers = ''
    this.generation++
    this.controller?.abort()
    this.controller = null
    this.pending = false
    this.data = null
    this.key = ''
    this.painted = ''
  }
}
