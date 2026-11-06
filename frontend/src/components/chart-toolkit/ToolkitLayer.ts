import {
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesPrimitive,
  type IPrimitivePaneRenderer,
  type IPrimitivePaneView,
  type SeriesAttachedParameter,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { mergeCoincidentNames, formatLevelPrice, nearestZones, layoutLevelNames } from './labels'
import { colors, type Reference, type Result } from './model'
import type { DisplaySettings } from './ToolkitPanel'

type Settings = DisplaySettings & { labelTop?: number; directional?: boolean }
interface Name {
  title: string
  price: number
  color: string
  y: number
}
// One bounded canvas primitive draws all structure, labels and historical tags.
// It adds no new times to the candle axis and never stretches the price scale.
class ToolkitPrimitive implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private result: Result | null = null
  private references: Reference[] = []
  private first = 0
  private last = 0
  private settings: Settings = { slow: 15, bands: false, markerLimit: 4 }
  private dark: boolean
  constructor(dark: boolean) {
    this.dark = dark
  }
  attached(a: SeriesAttachedParameter<Time>) {
    this.attachment = a
  }
  detached() {
    this.attachment = null
  }
  set(result: Result | null, refs: Reference[], first: number, last: number, settings: Settings) {
    this.result = result
    this.references = refs
    this.first = first
    this.last = last
    this.settings = settings
    this.attachment?.requestUpdate()
  }
  private render(target: Parameters<IPrimitivePaneRenderer['draw']>[0], labels: boolean) {
    const a = this.attachment,
      r = this.result
    if (!a || !r || !this.last) return
    // biome-ignore lint/correctness/useHookAtTopLevel: FancyCanvas coordinate API
    target.useMediaCoordinateSpace(({ context: c, mediaSize: size }) => {
      const names: Name[] = []
      const x = (time: number) => a.chart.timeScale().timeToCoordinate(time as UTCTimestamp)
      const y = (price: number) => a.series.priceToCoordinate(price)
      const end = Math.min(size.width - 8, (x(this.last) ?? size.width * 0.7) + 8)
      const ink = this.dark ? '#dce2eb' : '#283344',
        plate = this.dark ? '#131722' : '#ffffff'
      const name = (title: string, price: number, color: string) => {
        const value = y(price)
        if (value != null && value >= 6 && value < size.height - 6)
          names.push({ title, price, color, y: value })
      }
      c.save()
      c.beginPath()
      c.rect(0, 0, size.width, size.height)
      c.clip()
      const box = (
        time: number,
        endTime: number | undefined,
        high: number,
        low: number,
        color: string,
        opacity: string
      ) => {
        const top = y(high),
          bottom = y(low),
          left = Math.max(0, x(Math.max(time, this.first)) ?? 0),
          right = endTime ? (x(endTime) ?? end) : end
        if (top == null || bottom == null || right <= left) return
        c.fillStyle = color + opacity
        c.strokeStyle = color + (opacity === '0c' ? '60' : 'a0')
        c.lineWidth = 1
        c.setLineDash([])
        c.fillRect(left, top, right - left, Math.max(2, bottom - top))
        c.strokeRect(left, top, right - left, Math.max(2, bottom - top))
      }
      for (const z of nearestZones(r.zones)) {
        const color = z.above ? colors.bear : colors.bull
        if (!labels) box(z.time, undefined, z.high, z.low, color, '18')
        name(z.above ? 'Resistance' : 'Support', z.above ? z.high : z.low, color)
      }
      const pools = this.settings.liquidity
        ? [true, false].flatMap((above) => {
            const selected = r.pools.filter((p) => p.above === above)
            return selected.filter((p) => p.state === 'active').slice(-1)
          })
        : []
      for (const p of pools) {
        if (p.end != null && p.end < this.first) continue
        const color = p.above ? colors.highLiq : colors.lowLiq,
          active = p.state === 'active'
        if (!labels) box(p.time, p.end, p.high, p.low, color, active ? '18' : '0c')
        if (active || (p.end ?? 0) >= this.first)
          name(
            `${p.above ? 'High' : 'Low'} liq${active ? ` ×${p.touches}` : ` · ${p.state}`}`,
            p.level,
            color
          )
      }
      for (const ref of this.settings.references ? this.references : []) {
        const value = y(ref.price)
        if (!labels && value != null) {
          c.strokeStyle = ref.color + 'b0'
          c.lineWidth = 1
          c.setLineDash(
            ref.name.startsWith('1D') ? [8, 4] : ref.name.startsWith('4H') ? [4, 4] : [1, 4]
          )
          c.beginPath()
          c.moveTo(0, value)
          c.lineTo(size.width, value)
          c.stroke()
        }
        name(ref.name, ref.price, ref.color)
      }
      for (const trend of this.settings.trends ? r.trends : []) {
        const latestIndex = r.points.filter((p) => p.time <= (r.closedTime ?? 0)).length - 1
        const latestPrice = trend.start.price + trend.slope * (latestIndex - trend.start.index)
        const startIndex = Math.max(
          trend.start.index,
          r.points.findIndex((p) => p.time >= this.first)
        )
        const startTime = r.points[startIndex]?.time ?? this.first
        const y1 = y(trend.start.price + trend.slope * (startIndex - trend.start.index)),
          y2 = y(latestPrice),
          x1 = x(startTime)
        const color = trend.above ? colors.bear : colors.bull
        if (!labels && y1 != null && y2 != null && x1 != null) {
          c.strokeStyle = color
          c.lineWidth = 1.5
          c.setLineDash([7, 5])
          c.beginPath()
          c.moveTo(x1, y1)
          const lastX = x(r.closedTime!) ?? end,
            slope = (y2 - y1) / Math.max(1, lastX - x1)
          c.lineTo(size.width, y2 + slope * (size.width - lastX))
          c.stroke()
        }
        name(trend.above ? 'Trend resistance' : 'Trend support', latestPrice, color)
      }
      if (labels) {
        // Merge coincident references; keep a leader to the exact price when
        // collision avoidance shifts a label. Text and line share a color.
        const grouped = mergeCoincidentNames(names)
        c.font = '500 11px Inter, system-ui, sans-serif'
        c.textBaseline = 'middle'
        c.setLineDash([])
        for (const item of layoutLevelNames(
          grouped,
          size.height,
          size.width >= 560 ? this.settings.labelTop : 0
        )) {
          const text = `${item.title} ${formatLevelPrice(item.price)}`,
            width = Math.min(270, c.measureText(text).width + 10),
            left = end + 8
          const labelX = Math.min(size.width - width - 4, left),
            center = item.top + 11
          c.strokeStyle = item.color + '80'
          c.beginPath()
          c.moveTo(end, item.y)
          c.lineTo(labelX, center)
          c.stroke()
          c.globalAlpha = 0.94
          c.fillStyle = plate
          c.fillRect(labelX, item.top, width, 22)
          c.globalAlpha = 1
          c.fillStyle = item.color
          c.fillText(text, labelX + 5, center, width - 10)
        }
        // Signals and price-action glyphs are kept distinct and bounded.
        for (const event of this.settings.events ? r.events : []) {
          if (event.time < this.first || event.time > this.last) continue
          const px = x(event.time),
            py = y(event.price)
          if (px == null || py == null) continue
          const up = event.kind === 'breakout-up',
            down = event.kind === 'breakout-down'
          c.fillStyle = up
            ? colors.bull
            : down
              ? colors.bear
              : event.kind === 'sweep-high'
                ? colors.highLiq
                : colors.lowLiq
          c.font = 'bold 15px system-ui'
          c.fillText(up ? '▲' : down ? '▼' : '◇', px - 6, py + (up ? 15 : -15))
        }
        for (const signal of r.signals) {
          if (signal.time < this.first || signal.time > this.last) continue
          const px = x(signal.time),
            py = y(signal.price)
          if (px == null || py == null || px < 0 || px > size.width) continue
          const bull = signal.side === 'BULL',
            top = py + (bull ? 12 : -32)
          c.fillStyle = bull ? colors.bull : colors.bear
          c.fillRect(px - 22, top, 44, 20)
          c.fillStyle = '#fff'
          c.font = '600 11px system-ui'
          c.fillText(
            this.settings.directional ? (bull ? 'LONG' : 'SHORT') : signal.side,
            px - 16,
            top + 10
          )
        }
        c.fillStyle = ink
      }
      c.restore()
    })
  }
  private views: IPrimitivePaneView[] = [
    { zOrder: () => 'bottom', renderer: () => ({ draw: (target) => this.render(target, false) }) },
    { zOrder: () => 'top', renderer: () => ({ draw: (target) => this.render(target, true) }) },
  ]
  paneViews() {
    return this.views
  }
}

export class ToolkitLayer {
  private fast: ISeriesApi<'Line'>
  private slow: ISeriesApi<'Line'>
  private upper: ISeriesApi<'Line'>
  private lower: ISeriesApi<'Line'>
  private primitive: ToolkitPrimitive
  private lastClosed = ''
  private visibility = new Map<ISeriesApi<'Line'>, boolean>()
  constructor(chart: IChartApi, price: ISeriesApi<'Candlestick'>, dark: boolean) {
    const line = (color: string, width: 1 | 2) =>
      chart.addSeries(LineSeries, {
        color,
        lineWidth: width,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
    this.fast = line(colors.fast, 2)
    this.slow = line(colors.slow, 2)
    this.upper = line('#8391a8', 1)
    this.lower = line('#8391a8', 1)
    this.primitive = new ToolkitPrimitive(dark)
    price.attachPrimitive(this.primitive)
  }
  update(
    result: Result | null,
    refs: Reference[],
    first: number,
    last: number,
    settings: Settings
  ) {
    // The host batches this call with its candle update. Reuse closed geometry
    // between ticks; EMA tails alone change while the current bar is forming.
    const key = `${result?.revision}:${first}:${last}:${settings.slow}:${result?.sourceCount}`
    for (const [series, field, visible] of [
      [this.fast, 'ema9', true],
      [this.slow, 'emaSlow', true],
      [this.upper, 'bbHigh', settings.bands],
      [this.lower, 'bbLow', settings.bands],
    ] as const) {
      const show = !!result && visible
      const wasVisible = this.visibility.get(series)
      if (show) {
        if (key !== this.lastClosed || !wasVisible) {
          series.setData(
            result!.points
              .filter((p) => p.time >= first && p.time <= last && p.metrics[field] != null)
              .map((p) => ({ time: p.time as UTCTimestamp, value: p.metrics[field]! }))
          )
        } else {
          const tail = result!.points.at(-1)
          if (tail && tail.time >= first && tail.time <= last && tail.metrics[field] != null)
            series.update({ time: tail.time as UTCTimestamp, value: tail.metrics[field]! })
        }
      } else if (wasVisible) series.setData([])
      if (wasVisible !== show) {
        series.applyOptions({ visible: show })
        this.visibility.set(series, show)
      }
    }
    this.lastClosed = `${result?.revision}:${first}:${last}:${settings.slow}:${result?.sourceCount}`
    this.primitive.set(result, refs, first, last, settings)
  }
}
