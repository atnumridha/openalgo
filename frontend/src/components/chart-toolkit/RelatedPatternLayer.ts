import { patternExplanation } from './patternExplanation'
import { primaryArchiveLabels } from './archivePatternLabels'
import type { ISeriesApi } from 'lightweight-charts'
import { CandleMarkers, type Marker } from './CandleProbabilityLayer'
import { archivePatternEvents, type ArchiveGuide } from './archivePatternEngine'
import type { TimedArchiveMatch } from './archiveConfirmations'
import type { Bar } from './model'
export type RelatedGuide = ArchiveGuide
export function markersForArchiveEvents(
  events: TimedArchiveMatch[],
  bars: Bar[],
  first: number,
  last: number,
  includeNeutral = true
): Marker[] {
  const anchors = new Map(bars.map((bar, index) => [bar.time, { bar, index }]))
  return primaryArchiveLabels(
    events.filter(
      (m) => m.time >= first && m.time <= last && (includeNeutral || m.side !== 'NEUTRAL')
    )
  ).flatMap((match) => {
    const anchor = anchors.get(match.time)
    if (!anchor) return []
    const { bar, index } = anchor
    // Visual spacing only: these neighbors never enter pattern recognition.
    const nearby = bars.slice(Math.max(0, index - 2), index + 3)
    const color = match.side === 'CALL' ? '#34d399' : match.side === 'PUT' ? '#f87171' : '#cbd5e1'
    return [
      {
        time: bar.time,
        price: match.side === 'CALL' ? bar.low : bar.high,
        labelPrice:
          match.side === 'CALL'
            ? Math.min(...nearby.map((b) => b.low))
            : Math.max(...nearby.map((b) => b.high)),
        tooltip: patternExplanation(match.name, match.side, match.pattern),
        text: match.name
          .replace(/^(Bullish|Bearish|Bull|Bear)\s+/i, '')
          .replace(/\s+\(operational(?: re-entry)?\)/g, ''),
        above: match.side !== 'CALL',
        color,
        textColor: color,
        background: '#111827',
        pointer: true,
      },
    ]
  })
}
export function relatedPatternMarkers(
  bars: Bar[],
  mode: RelatedGuide,
  seconds: number,
  first: number,
  last: number,
  includeNeutral = true
): Marker[] {
  return markersForArchiveEvents(
    archivePatternEvents(bars, mode, seconds, first, last),
    bars,
    first,
    last,
    includeNeutral
  )
}
export class RelatedPatternLayer {
  private markers = new CandleMarkers()
  private attached = false
  private price: ISeriesApi<'Candlestick'>
  constructor(price: ISeriesApi<'Candlestick'>) {
    this.price = price
  }
  updateEvents(
    events: TimedArchiveMatch[],
    bars: Bar[],
    first: number,
    last: number,
    includeNeutral = true
  ) {
    if (events.length && !this.attached) {
      this.price.attachPrimitive(this.markers)
      this.attached = true
    }
    this.markers.set(markersForArchiveEvents(events, bars, first, last, includeNeutral), bars)
  }
  update(
    bars: Bar[],
    mode: RelatedGuide,
    seconds: number,
    first: number,
    last: number,
    includeNeutral = true
  ) {
    this.updateEvents(
      archivePatternEvents(bars, mode, seconds, first, last),
      bars,
      first,
      last,
      includeNeutral
    )
  }
}
