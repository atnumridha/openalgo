import type {
  IPriceLine,
  IPrimitivePaneRenderer,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from 'lightweight-charts'
import type {
  BookBar,
  BookEvent,
  BookGuideResult,
  BookPoint,
  BookSegment,
  BookSettings,
} from './engine'
import { bookOrdinaryEventVisible } from './engine'
export type BookDisplayOptions = Pick<
  BookSettings,
  | 'showPending'
  | 'showNeutral'
  | 'showTrendLines'
  | 'fullHistory'
  | 'labelLookback'
  | 'maxDrawings'
  | 'maxPolylines'
  | 'maxLabels'
  | 'maxLines'
>
const bounded = (n: number, cap: number) =>
  Number.isFinite(n) ? Math.max(0, Math.min(cap, Math.floor(n))) : cap
function segments(event: BookEvent, bars: readonly BookBar[]): BookSegment[] {
  if (event.segments.length) return event.segments
  if (event.kind !== 'candle') return []
  const formation = bars.filter(
    (b) => b.time >= event.formationStart && b.time <= event.formationEnd
  )
  if (!formation.length) return []
  const high = Math.max(...formation.map((b) => b.high)),
    low = Math.min(...formation.map((b) => b.low))
  const first = formation[0].time,
    last = formation.at(-1)!.time
  const p = (time: number, price: number): BookPoint => ({
    time,
    price,
    index: 0,
    role: 'formation',
  })
  // Single-candle outlines retain width in the renderer while keeping their actual time anchor.
  return [
    { from: p(first, high), to: p(last, high), role: 'formation top' },
    { from: p(last, high), to: p(last, low), role: 'formation right' },
    { from: p(last, low), to: p(first, low), role: 'formation bottom' },
    { from: p(first, low), to: p(first, high), role: 'formation left' },
  ]
}
/** Two context lines at most, after reserving the selected plan. No pattern visibility dependency. */
export function bookTrendWorklist(
  result: BookGuideResult | null,
  view: BookDisplayOptions
): BookSegment[] {
  if (!result || !view.showTrendLines) return []
  const reserved = result.activePlan ? 3 : 0
  return (result.trendLines ?? []).slice(
    0,
    Math.max(
      0,
      Math.min(2, bounded(view.maxLines, 120) - reserved, bounded(view.maxLabels, 160) - reserved)
    )
  )
}
/** Whole formations only. The chart window includes its forming candle, unlike engine completed-bar retention. */
export function bookDrawingWorklist(
  result: BookGuideResult | null,
  bars: readonly BookBar[],
  view: BookDisplayOptions
): BookEvent[] {
  if (!result || !bars.length) return []
  const times = new Set(bars.map((b) => b.time)),
    first = view.fullHistory
      ? -Infinity
      : bars[Math.max(0, bars.length - Math.max(1, view.labelLookback))].time
  const candidates = [...result.events, ...(view.showPending ? result.pendingEvents : [])]
    .filter(
      (e) =>
        bookOrdinaryEventVisible(e, view.showNeutral) &&
        (view.showPending || e.status === 'confirmed') &&
        times.has(e.confirmationTime ?? e.recognitionTime) &&
        (e.confirmationTime ?? e.recognitionTime) >= first
    )
    .sort(
      (a, b) =>
        (b.confirmationTime ?? b.recognitionTime) - (a.confirmationTime ?? a.recognitionTime) ||
        a.id.localeCompare(b.id)
    )
  const picked: BookEvent[] = [],
    ids = new Set<string>()
  const trendCount = bookTrendWorklist(result, view).length
  let lines = (result.activePlan ? 3 : 0) + trendCount,
    polylines = 0,
    labels = (result.activePlan ? 3 : 0) + trendCount
  for (const e of candidates) {
    const count = segments(e, bars).length,
      labelCount = 1 + e.points.length,
      lineCount = count + labelCount // Reserve a dotted leader for every displaced label.
    if (ids.has(e.id) || picked.length >= bounded(view.maxDrawings, 40)) continue
    if (
      lines + lineCount > bounded(view.maxLines, 120) ||
      polylines + count > bounded(view.maxPolylines, 80) ||
      labels + labelCount > bounded(view.maxLabels, 160)
    )
      continue
    picked.push(e)
    ids.add(e.id)
    lines += lineCount
    polylines += count
    labels += labelCount
  }
  return picked.reverse()
}
class BookPrimitive implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private events: BookEvent[] = []
  private bars: readonly BookBar[] = []
  private trends: BookSegment[] = []
  attached(a: SeriesAttachedParameter<Time>) {
    this.attachment = a
  }
  detached() {
    this.attachment = null
  }
  set(events: BookEvent[], bars: readonly BookBar[], trends: BookSegment[] = []) {
    this.trends = trends
    this.events = events
    this.bars = bars
    this.attachment?.requestUpdate()
  }
  paneViews() {
    return [
      {
        zOrder: () => 'top' as const,
        renderer: () => ({
          draw: (target: Parameters<IPrimitivePaneRenderer['draw']>[0]) => this.draw(target),
        }),
      },
    ]
  }
  private draw(target: Parameters<IPrimitivePaneRenderer['draw']>[0]) {
    const a = this.attachment
    if (!a) return
    // biome-ignore lint/correctness/useHookAtTopLevel: FancyCanvas coordinate API, not a React hook
    target.useMediaCoordinateSpace(({ context: c, mediaSize: size }) => {
      c.save()
      c.beginPath()
      c.rect(0, 0, size.width, size.height)
      c.clip()
      c.font = '11px sans-serif'
      c.lineWidth = 1.5
      const x = (t: number) => a.chart.timeScale().timeToCoordinate(t as UTCTimestamp),
        y = (p: number) => a.series.priceToCoordinate(p)
      type LabelRect = { x: number; y: number; width: number; height: number }
      const occupied: LabelRect[] = []
      const captions: (() => void)[] = [],
        roles: (() => void)[] = [],
        contextLabels: (() => void)[] = [],
        labelPaint: (() => void)[] = []
      const markers: { point: BookPoint; color: string }[] = []
      // Reserve the near-candle band for preserved studies. Only already-selected
      // formation highs/lows participate; confirmation points never widen it.
      const candlePrices = this.events
        .filter((event) => event.kind === 'candle')
        .flatMap((event) => event.points)
        .filter((point) => point.role === 'high' || point.role === 'low')
        .map((point) => point.price)
      const captionHigh = candlePrices.length ? y(Math.max(...candlePrices)) : null,
        captionLow = candlePrices.length ? y(Math.min(...candlePrices)) : null
      const label = (
        p: BookPoint,
        text: string,
        color: string,
        below = p.role === 'low',
        leader = true,
        displayEdge?: number,
        mainCaption = false
      ) => {
        const px = x(p.time),
          py = y(p.price)
        if (px == null || py == null) return
        // Wrap only at the viewport width; retain the complete pattern name.
        const textLines: string[] = []
        let row = ''
        for (const word of text.split(' ')) {
          const next = row ? `${row} ${word}` : word
          if (row && c.measureText(next).width + 8 > size.width - 4) {
            textLines.push(row)
            row = word
          } else row = next
        }
        textLines.push(row)
        const width = Math.max(...textLines.map((line) => c.measureText(line).width)) + 8,
          height = textLines.length * 14,
          maxLeft = Math.max(2, size.width - width - 2),
          preferredLeft = Math.max(2, Math.min(maxLeft, px + 3))
        const candle = leader ? this.bars.find((b) => b.time === p.time) : undefined
        const edge =
          displayEdge !== undefined
            ? (y(displayEdge) ?? py)
            : candle
              ? (y(below ? candle.low : candle.high) ?? py)
              : py
        const sharedEdge = mainCaption ? (below ? captionLow : captionHigh) : null
        const captionEdge =
          sharedEdge == null ? edge : (below ? Math.max : Math.min)(edge, sharedEdge)
        const gap = sharedEdge == null ? (below ? 11 : 5) : 40
        const firstTop = Math.max(
          2,
          Math.min(size.height - height - 2, below ? captionEdge + gap : captionEdge - height - gap)
        )
        // Candidate boundaries are bounded by the existing label cap. Search both
        // axes using each rectangle's own dimensions, not an arbitrary lane count.
        const xs = [
          ...new Set([
            preferredLeft,
            2,
            maxLeft,
            ...occupied.flatMap((o) => [o.x + o.width + 4, o.x - width - 4]),
          ]),
        ]
          .filter((left) => left >= 2 && left <= maxLeft)
          .sort((a, b) => Math.abs(a - preferredLeft) - Math.abs(b - preferredLeft) || a - b)
        const ys = [
          ...new Set([
            firstTop,
            ...occupied.map((o) => (below ? o.y + o.height + 4 : o.y - height - 4)),
          ]),
        ]
          .filter(
            (top) =>
              top >= 2 &&
              top + height <= size.height - 2 &&
              (below ? top >= firstTop : top <= firstTop)
          )
          .sort((a, b) => (below ? a - b : b - a))
        let rect: LabelRect = { x: preferredLeft, y: firstTop, width, height }
        let leastOverlap = Infinity
        search: for (const top of ys) {
          for (const left of xs) {
            const overlap = occupied.reduce(
              (sum, o) =>
                sum +
                Math.max(0, Math.min(left + width + 2, o.x + o.width) - Math.max(left - 2, o.x)) *
                  Math.max(0, Math.min(top + height + 2, o.y + o.height) - Math.max(top - 2, o.y)),
              0
            )
            if (overlap < leastOverlap) {
              leastOverlap = overlap
              rect = { x: left, y: top, width, height }
            }
            if (overlap === 0) break search
          }
        }
        occupied.push(rect)
        // Labels can move for collision avoidance; the leader always starts at
        // the real candle/geometry coordinate on this candlestick series.
        const endX = Math.max(rect.x, Math.min(rect.x + width, px)),
          endY = Math.max(rect.y, Math.min(rect.y + height, py))
        if (leader && (endX !== px || endY !== py)) {
          c.save()
          c.strokeStyle = color
          c.lineWidth = 1
          c.setLineDash([2, 3])
          c.beginPath()
          c.moveTo(px, py)
          c.lineTo(endX, endY)
          c.stroke()
          c.restore()
        }
        labelPaint.push(() => {
          c.fillStyle = '#131722'
          c.fillRect(rect.x, rect.y, width, height)
          c.fillStyle = color
          textLines.forEach((line, i) => c.fillText(line, rect.x + 2, rect.y + 11 + i * 14))
        })
      }
      for (const trend of this.trends) {
        const x1 = x(trend.from.time),
          x2 = x(trend.to.time),
          y1 = y(trend.from.price),
          y2 = y(trend.to.price)
        if (x1 == null || x2 == null || y1 == null || y2 == null) continue
        const color = trend.role === 'Support trend' ? '#38bdf8' : '#fb923c'
        c.strokeStyle = color
        c.lineWidth = 1.5
        c.setLineDash([])
        c.beginPath()
        c.moveTo(x1, y1)
        c.lineTo(x2, y2)
        c.stroke()
        contextLabels.push(() =>
          label(trend.to, `${trend.role} · context`, color, trend.role === 'Support trend', false)
        )
      }
      for (const e of this.events) {
        const color = e.side === 'long' ? '#34d399' : e.side === 'short' ? '#f87171' : '#fbbf24'
        c.strokeStyle = color
        c.setLineDash(e.status === 'confirmed' ? [] : [4, 3])
        for (const line of segments(e, this.bars)) {
          let x1: number | null = x(line.from.time),
            x2: number | null = x(line.to.time)
          const y1 = y(line.from.price),
            y2 = y(line.to.price)
          if (x1 == null || x2 == null || y1 == null || y2 == null) continue
          if (e.kind === 'candle' && e.formationStart === e.formationEnd) {
            if (line.role === 'formation top' || line.role === 'formation bottom') {
              x1 -= 4
              x2 += 4
            } else if (line.role === 'formation left') {
              x1 -= 4
              x2 -= 4
            } else if (line.role === 'formation right') {
              x1 += 4
              x2 += 4
            }
          }
          c.beginPath()
          c.moveTo(x1, y1)
          c.lineTo(x2, y2)
          c.stroke()
        }
        let anchor = e.points.at(-1)
        const formationPoints = e.points.filter((p) => p.role === 'high' || p.role === 'low')
        if (e.kind === 'candle') {
          const sourceRole = e.side === 'short' ? 'high' : 'low'
          for (const point of formationPoints) if (point.role === sourceRole) anchor = point
        }
        if (anchor) {
          // Keep the source endpoint separate from the caption's display edge.
          // Confirmation points never replace a candle's source high/low.
          const envelope =
            e.kind === 'candle' && formationPoints.length
              ? (e.side === 'long' ? Math.min : Math.max)(...formationPoints.map((p) => p.price))
              : anchor.price
          const source = anchor
          captions.push(() =>
            label(
              source,
              `${e.name} · ${e.status === 'confirmed' ? 'confirmed' : 'pending'}`,
              color,
              e.side === 'long',
              true,
              envelope,
              true
            )
          )
        }
        for (const p of e.points) {
          markers.push({ point: p, color })
          if (p.role !== 'high' && p.role !== 'low' && p.role !== 'confirmation')
            roles.push(() => label(p, p.role, color, false))
        }
      }
      // Main pattern names get available lanes before secondary context/role names.
      for (const draw of [...captions, ...contextLabels, ...roles]) draw()
      // Paint names above every leader, including leaders to later captions.
      for (const paint of labelPaint) paint()
      for (const { point, color } of markers) {
        const px = x(point.time),
          py = y(point.price)
        if (px == null || py == null) continue
        c.fillStyle = color
        c.fillRect(px - 1.5, py - 1.5, 3, 3)
      }
      c.restore()
    })
  }
}
export class BookPatternLayer {
  private readonly price: ISeriesApi<'Candlestick'>
  private readonly primitive = new BookPrimitive()
  private lines: IPriceLine[] = []
  private key = ''
  private destroyed = false
  constructor(price: ISeriesApi<'Candlestick'>) {
    this.price = price
    price.attachPrimitive(this.primitive)
  }
  update(
    result: BookGuideResult | null,
    bars: readonly BookBar[],
    displayOptions: BookDisplayOptions
  ) {
    if (this.destroyed) return
    this.primitive.set(
      bookDrawingWorklist(result, bars, displayOptions),
      bars,
      bookTrendWorklist(result, displayOptions)
    )
    const p = result?.activePlan
    const levels = p
      ? ([
          ['Book Entry', p.entry, '#ffffff'],
          ['Book SL', p.stop, '#ef4444'],
          ['Book Target', p.target, '#22c55e'],
        ] as const)
      : []
    const key = JSON.stringify(levels)
    if (key === this.key) return
    for (const line of this.lines) this.price.removePriceLine(line)
    this.lines = []
    this.key = key
    for (const [title, price, color] of levels)
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
    if (this.destroyed) return
    this.update(null, [], {
      showPending: false,
      showNeutral: false,
      showTrendLines: false,
      fullHistory: false,
      labelLookback: 10,
      maxDrawings: 40,
      maxPolylines: 80,
      maxLabels: 160,
      maxLines: 120,
    })
    this.price.detachPrimitive?.(this.primitive)
    this.destroyed = true
  }
}
