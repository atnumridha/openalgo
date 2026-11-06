import type { TimeframePriceLevel } from './higherTimeframeLevels'
import type { TimedArchiveMatch } from './archiveConfirmations'
import { deduplicateArchiveMatches } from './archivePatternLabels'
import { comparePatternDisplay } from './patternDisplaySelection'
import type {
  ISeriesApi,
  IPriceLine,
  ISeriesPrimitive,
  IPrimitivePaneRenderer,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from 'lightweight-charts'
import type { Bar } from './model'
import { isScheduledTrendGap, type TrendSession } from './trendAnalysis'

export interface TrendLinePoint {
  time: number
  price: number
}
export interface TrendLineSegment {
  points: TrendLinePoint[]
  color: string
  title: string
  kind?: 'pattern'
}

/** Keep the newest visible confirmed formation; generic trend lines remain independent. */
export function cryptoFormationSegments(
  events: readonly TimedArchiveMatch[],
  bars: readonly Bar[],
  first: number,
  last: number,
  showPending = false
): TrendLineSegment[] {
  const times = new Set(bars.map((bar) => bar.time))
  const geometry = (event: TimedArchiveMatch) =>
    (event.structure ?? []).filter(
      (line) =>
        line.length >= 2 &&
        line.every(
          (point, index) =>
            times.has(point.time) &&
            point.time <= event.time &&
            Number.isFinite(point.price) &&
            point.price > 0 &&
            (!index || point.time > line[index - 1].time)
        )
    )
  // Filter geometry before any reduction: candle-label winners are a separate view.
  const latest = deduplicateArchiveMatches(
    events.filter(
      (event) =>
        (event.confirmed === true || (showPending && event.confirmed === false)) &&
        event.side !== 'NEUTRAL' &&
        event.time >= first &&
        event.time <= last &&
        times.has(event.time) &&
        geometry(event).length > 0
    )
  ).sort(comparePatternDisplay)[0]
  if (!latest) return []
  return geometry(latest).map((points) => ({
    points: points.map((point) => ({ ...point })),
    color: latest.confirmed === false ? '#fbbf24' : latest.side === 'CALL' ? '#34d399' : '#f87171',
    title: latest.name + (latest.confirmed === false ? ' · forming' : ''),
    kind: 'pattern',
  }))
}

function completedTrendSegment(
  bars: readonly Bar[],
  seconds: number,
  session?: TrendSession | null,
  indian = false
): Bar[] {
  if (!Number.isFinite(seconds) || seconds <= 0) return []
  let segment: Bar[] = []
  for (const bar of bars) {
    if (
      ![bar.time, bar.open, bar.high, bar.low, bar.close].every(Number.isFinite) ||
      bar.time < 0 ||
      Math.min(bar.open, bar.low, bar.close) <= 0 ||
      bar.high < Math.max(bar.open, bar.close, bar.low) ||
      bar.low > Math.min(bar.open, bar.close)
    ) {
      segment = []
      continue
    }
    if (
      segment.length &&
      bar.time - segment.at(-1)!.time !== seconds &&
      !isScheduledTrendGap(segment.at(-1)!.time, bar.time, seconds, session, indian)
    )
      segment = []
    segment.push(bar)
  }
  return segment
}

/** One price level per side, confirmed by two candles on each side of the swing.
 * A completed close through a level invalidates it; the clock never confirms it. */
export function supportResistanceLevels(
  bars: readonly Bar[],
  seconds: number,
  session?: TrendSession | null,
  indian = false
): { support: number | null; resistance: number | null } {
  const segment = completedTrendSegment(bars, seconds, session, indian).slice(-300)
  const latest = segment.at(-1)
  let support: number | null = null,
    resistance: number | null = null
  if (!latest) return { support, resistance }
  for (let i = 2; i + 2 < segment.length; i++) {
    const bar = segment[i],
      left = segment.slice(i - 2, i),
      right = segment.slice(i + 1, i + 3)
    if (
      bar.low < latest.close &&
      left.every((b) => b.low > bar.low) &&
      right.every((b) => b.low >= bar.low) &&
      segment.slice(i + 1).every((b) => b.close >= bar.low)
    ) {
      support = support == null ? bar.low : Math.max(support, bar.low)
    }
    if (
      bar.high > latest.close &&
      left.every((b) => b.high < bar.high) &&
      right.every((b) => b.high <= bar.high) &&
      segment.slice(i + 1).every((b) => b.close <= bar.high)
    ) {
      resistance = resistance == null ? bar.high : Math.min(resistance, bar.high)
    }
  }
  return { support, resistance }
}

/** Only completed candles belong in this prefix. Nothing extends past its last time. */
export function trendLineSegments(
  bars: readonly Bar[],
  seconds: number,
  boundary?: TrendLinePoint[],
  session?: TrendSession | null,
  indian = false
): TrendLineSegment[] {
  const segment = completedTrendSegment(bars, seconds, session, indian)
  const latest = segment.at(-1)
  if (!latest) return []
  const lines: TrendLineSegment[] = []
  for (const support of [true, false]) {
    const pivots: Array<TrendLinePoint & { index: number }> = []
    for (let i = 2; i < segment.length - 2; i++) {
      const price = support ? segment[i].low : segment[i].high
      const left = segment.slice(i - 2, i),
        right = segment.slice(i + 1, i + 3)
      if (
        left.every((b) => (support ? b.low > price : b.high < price)) &&
        right.every((b) => (support ? b.low >= price : b.high <= price))
      )
        pivots.push({ time: segment[i].time, price, index: i })
    }
    if (pivots.length < 2) continue
    const [start, end] = pivots.slice(-2)
    const slope = (end.price - start.price) / (end.index - start.index)
    const priceAt = (index: number) => start.price + slope * (index - start.index)
    const tolerance = Math.max(start.price, end.price) * 1e-10
    if (
      segment
        .slice(start.index)
        .some((b, offset) =>
          support
            ? b.close < priceAt(start.index + offset) - tolerance
            : b.close > priceAt(start.index + offset) + tolerance
        )
    )
      continue
    const projected = priceAt(segment.length - 1)
    if (!Number.isFinite(projected) || projected <= 0) continue
    lines.push({
      points: [
        { time: start.time, price: start.price },
        { time: end.time, price: end.price },
        { time: latest.time, price: projected },
      ],
      color: support ? '#26a69a' : '#ef5350',
      title: support ? 'Trend support' : 'Trend resistance',
    })
  }
  const points = (boundary ?? [])
    .filter(
      (p) =>
        Number.isFinite(p.time) &&
        Number.isFinite(p.price) &&
        p.price > 0 &&
        p.time >= segment[0].time &&
        p.time <= latest.time
    )
    .map((p) => ({ ...p }))
    .sort((a, b) => a.time - b.time)
    .filter((p, i, all) => !i || p.time > all[i - 1].time)
  if (points.length >= 2) lines.push({ points, color: '#3988ff', title: 'Breakout boundary' })
  return lines
}

class TrendLines implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private segments: TrendLineSegment[] = []
  attached(value: SeriesAttachedParameter<Time>) {
    this.attachment = value
  }
  detached() {
    this.attachment = null
  }
  set(segments: TrendLineSegment[]) {
    this.segments = segments
    this.attachment?.requestUpdate()
  }
  paneViews() {
    return [
      {
        zOrder: () => 'top' as const,
        renderer: () => ({
          draw: (target: Parameters<IPrimitivePaneRenderer['draw']>[0]) => {
            const attachment = this.attachment
            if (!attachment || !this.segments.length) return
            // biome-ignore lint/correctness/useHookAtTopLevel: FancyCanvas coordinate API
            target.useMediaCoordinateSpace(({ context, mediaSize }) => {
              context.save()
              context.beginPath()
              context.rect(0, 0, mediaSize.width, mediaSize.height)
              context.clip()
              context.lineWidth = 2
              context.font = '600 10px Inter, system-ui, sans-serif'
              for (const segment of this.segments) {
                const points = segment.points.map((p) => ({
                  x: attachment.chart.timeScale().timeToCoordinate(p.time as UTCTimestamp),
                  y: attachment.series.priceToCoordinate(p.price),
                }))
                // Skip only absent coordinates; clipping preserves off-screen geometry.
                if (points.some((p) => p.x == null || p.y == null)) continue
                context.strokeStyle = segment.color
                context.fillStyle = segment.color
                context.setLineDash(
                  segment.kind === 'pattern'
                    ? [4, 3]
                    : segment.title === 'Breakout boundary'
                      ? [5, 3]
                      : []
                )
                context.beginPath()
                points.forEach((p, i) =>
                  i ? context.lineTo(p.x!, p.y!) : context.moveTo(p.x!, p.y!)
                )
                context.stroke()
                // The existing 6px candle label names the formation; no duplicate caption.
                if (
                  segment.kind === 'pattern' ||
                  (segment.title === 'Breakout boundary' &&
                    this.segments.some((line) => line.kind === 'pattern'))
                )
                  continue
                const end = points.at(-1)!
                context.fillText(
                  segment.title,
                  Math.max(4, Math.min(mediaSize.width - 110, end.x! + 5)),
                  Math.max(12, Math.min(mediaSize.height - 4, end.y! - 6))
                )
              }
              context.restore()
            })
          },
        }),
      },
    ]
  }
}

export class TrendLineLayer {
  private primitive = new TrendLines()
  private attached = false
  private destroyed = false
  private priceLines: IPriceLine[] = []
  private levelKey = ''
  private series: ISeriesApi<'Candlestick'>
  constructor(series: ISeriesApi<'Candlestick'>) {
    this.series = series
  }
  update(
    bars: readonly Bar[],
    seconds: number,
    boundary?: TrendLinePoint[],
    session?: TrendSession | null,
    indian = false,
    formations: TrendLineSegment[] = [],
    timeframeLevels: TimeframePriceLevel[] = []
  ) {
    if (this.destroyed) return
    if (!this.attached) {
      this.series.attachPrimitive(this.primitive)
      this.attached = true
    }
    const levels = supportResistanceLevels(bars, seconds, session, indian)
    const levelKey = JSON.stringify([levels, timeframeLevels])
    if (levelKey !== this.levelKey) {
      for (const line of this.priceLines) this.series.removePriceLine(line)
      this.priceLines = []
      this.levelKey = levelKey
      const candidates = [
        ...timeframeLevels.map((level) => ({
          price: level.price,
          color: level.color,
          title: level.title,
          swing: false,
        })),
        ...(
          [
            [levels.support, '#22c55e', 'SUPPORT'],
            [levels.resistance, '#ef4444', 'RESISTANCE'],
          ] as const
        ).flatMap(([price, color, title]) =>
          price == null ? [] : [{ price, color, title, swing: true }]
        ),
      ]
      // Equal levels share one stroke and retain every name on its price label.
      const grouped: { price: number; color: string; title: string; swing: boolean }[] = []
      for (const level of candidates) {
        const existing = grouped.find((other) => Math.abs(other.price - level.price) < 1e-8)
        if (existing) {
          existing.title += ` / ${level.title}`
          if (level.swing) {
            existing.color = level.color
            existing.swing = true
          }
        } else grouped.push({ ...level })
      }
      for (const level of grouped) {
        this.priceLines.push(
          this.series.createPriceLine({
            price: level.price,
            color: level.color,
            title: level.title,
            lineWidth: level.swing ? 2 : 1,
            lineStyle: level.swing ? 0 : 2,
            lineVisible: true,
            axisLabelVisible: true,
          })
        )
      }
    }
    const base = trendLineSegments(bars, seconds, boundary, session, indian)
    const uniqueFormations = formations.filter(
      (formation) =>
        !base.some(
          (line) =>
            line.points.length === formation.points.length &&
            line.points.every(
              (point, index) =>
                point.time === formation.points[index].time &&
                Math.abs(point.price - formation.points[index].price) <=
                  Math.max(1, point.price) * 1e-10
            )
        )
    )
    this.primitive.set([...base, ...uniqueFormations])
  }
  destroy() {
    for (const line of this.priceLines) this.series.removePriceLine(line)
    this.priceLines = []
    this.levelKey = ''
    if (this.attached) this.series.detachPrimitive(this.primitive)
    this.primitive.set([])
    this.attached = false
    this.destroyed = true
  }
}
