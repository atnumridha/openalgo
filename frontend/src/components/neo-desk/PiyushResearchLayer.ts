import {
  LineSeries,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
  type SeriesMarker,
} from 'lightweight-charts'
import { compute, type ResearchBar } from './piyushResearchEngine.js'
import { ResearchTradeLevels } from './ResearchTradeLevels'
export const PIYUSH_MODES = [
  ['off', 'Off'],
  ['previous_day_break_5m', 'Previous-day breakout · 5m'],
  ['opening_range_break_5m', 'Opening-range breakout · 5m'],
  ['ema_cross_1m', 'EMA 8/33 cross · 1m'],
  ['ema_cross_5m', 'EMA 8/33 cross · 5m'],
  ['ema_pullback_1m', 'EMA 8 pullback · 1m'],
] as const
const PLOTS = [
  ['fast', '#38bdf8'],
  ['slow', '#c084fc'],
  ['upper', '#f59e0b'],
  ['lower', '#f59e0b'],
  ['entry', '#94a3b8'],
  ['stop', '#ef4444'],
  ['target', '#22c55e'],
] as const
export class PiyushResearchLayer {
  private cleared = false
  private cached: { bars: ResearchBar[]; key: string; status: string } | null = null
  private lines: ISeriesApi<'Line'>[]
  private markers: ReturnType<typeof createSeriesMarkers<Time>>
  private levels = new ResearchTradeLevels()
  constructor(chart: IChartApi, price: ISeriesApi<'Candlestick'>) {
    this.lines = PLOTS.map(([key, color]) =>
      chart.addSeries(LineSeries, {
        color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        title: (
          {
            fast: 'EMA 8',
            slow: 'EMA 33',
            upper: 'Resistance',
            lower: 'Support',
            entry: 'Entry',
            stop: 'Stop loss',
            target: 'Target',
          } as Record<string, string>
        )[key],
      })
    )
    this.markers = createSeriesMarkers(price, [])
    price.attachPrimitive(this.levels)
  }
  update(
    bars: ResearchBar[],
    mode: string,
    reward: number,
    symbol: string,
    interval: string,
    first: number,
    last: number,
    context?: {
      universal?: boolean
      continuous?: boolean
      tickSize?: number
      optionSide?: 'CE' | 'PE'
      session?: { start: number; end: number; offset: number } | null
      hostTimes?: number[]
      hostSeconds?: number
    }
  ): string {
    const key = JSON.stringify([mode, reward, symbol, interval, first, last, context])
    if (this.cached?.bars === bars && this.cached.key === key) return this.cached.status
    const host = context?.hostTimes ?? []
    const anchor = (time: number) => {
      let lo = 0,
        hi = host.length - 1
      while (lo <= hi) {
        const mid = (lo + hi) >> 1
        if (host[mid] <= time) lo = mid + 1
        else hi = mid - 1
      }
      return host[Math.max(0, hi)] ?? time
    }
    const end = last + (context?.hostSeconds ?? 1)
    const inRange = (time: number) => time >= first && time < end
    const r = compute(
      mode === 'off' ? [] : bars,
      { mode, reward },
      { symbol, interval, ...context }
    )
    if (mode === 'off' || !r.values.ready.at(-1)) {
      if (!this.cleared) {
        this.lines.forEach((line) => line.setData([]))
        this.markers.setMarkers([])
        this.levels.set([], first, last)
        this.cleared = true
      }
      const status = mode === 'off' ? 'Overlay off' : r.status
      this.cached = { bars, key, status }
      return status
    }
    this.cleared = false
    this.lines.forEach((line, j) => {
      const data = new Map<number, { time: UTCTimestamp; value?: number }>()
      if (j < 4)
        for (let i = 0; i < bars.length; i++) {
          const b = bars[i]
          if (!inRange(b.time)) continue
          const time = anchor(b.time),
            value = r.values[PLOTS[j][0]][i]
          data.set(
            time,
            value == null ? { time: time as UTCTimestamp } : { time: time as UTCTimestamp, value }
          )
        }
      line.setData([...data.values()])
    })
    this.levels.set(
      r.trades.map((t) => ({
        ...t,
        entry_time: anchor(t.entry_time),
        exit_time: t.exit_time == null ? undefined : anchor(t.exit_time),
      })),
      first,
      last
    )
    const markers: SeriesMarker<Time>[] = []
    if (mode !== 'off')
      for (let i = 0; i < bars.length; i++) {
        const b = bars[i]
        if (!inRange(b.time)) continue
        const side = r.values.direction[i],
          e = r.values.event[i]
        if (side)
          markers.push({
            time: anchor(b.time) as UTCTimestamp,
            position: side === 1 ? 'belowBar' : 'aboveBar',
            shape: side === 1 ? 'arrowUp' : 'arrowDown',
            color: side === 1 ? '#16a34a' : '#dc2626',
            text: context?.universal
              ? context.optionSide
                ? side === 1
                  ? `BUY ${context.optionSide}`
                  : `AVOID ${context.optionSide}`
                : side === 1
                  ? 'LONG entry'
                  : 'SHORT entry'
              : side === 1
                ? 'CE entry'
                : 'PE entry',
          })
        if (e === 6 || (e != null && e >= 12))
          markers.push({
            time: anchor(b.time) as UTCTimestamp,
            position: 'aboveBar',
            shape: 'circle',
            color: e === 12 ? '#16a34a' : '#d97706',
            text: (
              {
                6: 'Data gap',
                12: 'Target',
                13: 'Stop loss',
                14: 'SL first · both hit',
                15: 'Time exit',
              } as Record<number, string>
            )[e],
          })
      }
    this.markers.setMarkers(markers)
    const n = r.trades.filter((t) => t.entry_time >= first && t.entry_time < end).length
    const status = `${PIYUSH_MODES.find(([value]) => value === mode)?.[1] ?? 'Research'} · ${n ? `${n} displayed entries` : 'No confirmed entries in this range'} · ${context?.universal ? 'chart price levels · 1:2' : 'index levels'} · 2/day · 60 min · ${context?.continuous ? '23:45 UTC' : context?.session ? `${String(Math.floor((context.session.end - 15) / 60)).padStart(2, '0')}:${String((context.session.end - 15) % 60).padStart(2, '0')} IST` : '15:15 IST'} exit`
    this.cached = { bars, key, status }
    return status
  }
}
