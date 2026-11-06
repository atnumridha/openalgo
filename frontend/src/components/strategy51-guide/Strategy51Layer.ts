import type { IPriceLine, ISeriesApi } from 'lightweight-charts'
import { BookPatternLayer } from '../book-pattern-guide/BookPatternLayer'
import type { BookEvent, BookGuideResult } from '../book-pattern-guide/types'
import type { Strategy51Result, Strategy51Settings, StrategyBar } from './types'
import { STRATEGY51_CHART_NAMES } from './chartNames'
import { DEFAULT_STRATEGY51_SETTINGS } from './settings'
export function toStrategy51Drawing(
  result: Strategy51Result,
  settings = DEFAULT_STRATEGY51_SETTINGS
): BookGuideResult {
  const frames = result.frames ?? [],
    events: BookEvent[] = result.events
      .filter((e) => settings.showOtherSetups || settings.fullHistory || e.id === result.plan?.id)
      .flatMap((e) => {
        const source = frames[e.signalIndex]?.bar,
          confirmed = frames[e.index]?.bar
        if (!source || !confirmed) return []
        const sourceRole = e.side === 'long' ? 'low' : 'high'
        const points = e.points.flatMap((p) =>
          frames[p.index]
            ? [
                {
                  time: frames[p.index].bar.time,
                  index: p.index,
                  price: p.price,
                  role: p.role === 'signal' ? sourceRole : p.role,
                },
              ]
            : []
        )
        // The Book renderer chooses the last source-role point for its dotted leader.
        // Keep that endpoint on the signal candle, independent of later confirmation.
        if (!points.some((p) => p.index === e.signalIndex && p.role === sourceRole))
          points.push({
            time: source.time,
            index: e.signalIndex,
            price: e.side === 'long' ? source.low : source.high,
            role: sourceRole,
          })
        const firstIndex = Math.min(
          e.signalIndex,
          ...points.filter((p) => p.role !== 'confirmation').map((p) => p.index)
        )
        return [
          {
            id: e.id,
            patternId: e.strategyId,
            name: `${e.strategyId} · ${STRATEGY51_CHART_NAMES[e.strategyId] ?? e.name}`,
            side: e.side,
            sourcePhotos: [],
            kind: 'candle' as const,
            mode: 'neutral' as const,
            startIndex: firstIndex,
            endIndex: e.signalIndex,
            recognitionIndex: e.index,
            trigger: e.entry,
            stopAnchor: e.stop ?? (e.side === 'long' ? source.low : source.high),
            stopMethod: e.stopMethod,
            targetMethod: 'r-fallback' as const,
            scale: 1,
            contacts: 1,
            rank: 3,
            points,
            segments: e.segments ?? [],
            notes: e.notes,
            formationStart: frames[firstIndex].bar.time,
            formationEnd: source.time,
            recognitionTime: confirmed.time,
            status: 'confirmed' as const,
            nextCondition: e.next,
            confirmationTime: confirmed.time,
            confirmationIndex: e.index,
          },
        ]
      })
  return {
    events,
    visibleEvents: events,
    pendingEvents: [],
    observations: [],
    alternatives: [],
    explanation: result.expected,
    nextCondition: result.next,
    alerts: [],
    readiness: result.readiness,
    unavailableReasons: result.readiness === 'unavailable' ? [result.reason] : [],
    indicators: { trend: result.trend },
    filters: [],
    levels: [],
    trendLines: result.trendLines,
  }
}
/** Independent primitive/line ownership; the existing Book indicator is never updated. */
export class Strategy51Layer {
  private drawing?: BookPatternLayer
  private lines: IPriceLine[] = []
  private key = ''
  private destroyed = false
  private readonly price: ISeriesApi<'Candlestick'>
  constructor(price: ISeriesApi<'Candlestick'>) {
    this.price = price
  }
  update(result: Strategy51Result | null, bars: readonly StrategyBar[], s: Strategy51Settings) {
    if (this.destroyed) return
    if (result && !this.drawing) this.drawing = new BookPatternLayer(this.price)
    if (!result && this.drawing) {
      this.drawing.destroy()
      this.drawing = undefined
    }
    this.drawing?.update(result ? toStrategy51Drawing(result, s) : null, bars, {
      showPending: false,
      showNeutral: true,
      showTrendLines: s.showTrendLines,
      fullHistory: s.fullHistory,
      labelLookback: s.labelLookback,
      maxDrawings: 8,
      maxPolylines: 32,
      maxLabels: 32,
      maxLines: 64,
    })
    const p = result?.plan,
      levels: { title: string; price: number; color: string }[] = p
        ? [
            { title: '51 Entry', price: p.entry, color: '#ffffff' },
            { title: '51 SL', price: p.currentStop ?? p.stop, color: '#ef4444' },
            ...(p.target != null
              ? [
                  {
                    title:
                      p.targetOrigin === 'local'
                        ? '51 Local target'
                        : p.targetOrigin === 'supplied'
                          ? '51 Supplied target'
                          : '51 Target',
                    price: p.target,
                    color: '#22c55e',
                  },
                ]
              : []),
          ]
        : []
    const key = JSON.stringify(levels)
    if (key === this.key) return
    for (const line of this.lines) this.price.removePriceLine(line)
    this.lines = []
    this.key = key
    for (const v of levels)
      if (Number.isFinite(v.price) && v.price > 0)
        this.lines.push(
          this.price.createPriceLine({ ...v, lineWidth: 1, lineStyle: 2, axisLabelVisible: true })
        )
  }
  destroy() {
    if (this.destroyed) return
    this.drawing?.destroy()
    for (const l of this.lines) this.price.removePriceLine(l)
    this.lines = []
    this.destroyed = true
  }
}
