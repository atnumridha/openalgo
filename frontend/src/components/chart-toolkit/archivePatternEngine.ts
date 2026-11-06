import { deduplicateArchiveMatches } from './archivePatternLabels'
import { recognizeArchiveCandlesA } from './archiveCandlesA'
import { recognizeArchiveCandlesB } from './archiveCandlesB'
import { recognizeExtendedCandles } from './extendedCandlePatterns'
import { recognizeHarmonicPatterns } from './harmonicChartPatterns'
import { recognizeChartShapes } from './chartShapePatterns'
import { recognizeFidelityShortPatterns } from './fidelityShortPatterns'
import { recognizeArchiveChartPatterns, parabolicSAR } from './archiveChartPatterns'
import { recognizeInstitutionalPatterns } from './archiveInstitutionalPatterns'
import {
  recognizeZoneConfirmations,
  recognizeCandleConfirmations,
  type ArchiveMatch,
  type TimedArchiveMatch,
} from './archiveConfirmations'
import type { Bar } from './model'
import { isScheduledTrendGap, type TrendSession } from './trendAnalysis'
export type ArchiveGuide = 'off' | 'all' | 'candles' | 'shapes' | 'setups'
export function recognizeArchiveCandles(bars: Bar[]): ArchiveMatch[] {
  return deduplicateArchiveMatches([
    ...recognizeExtendedCandles(bars),
    ...recognizeArchiveCandlesA(bars),
    ...recognizeArchiveCandlesB(bars),
  ])
}
/** Pure completed-bar collector. Recognition at each event receives only that
 * event's prefix. Gaps reset both context and path-dependent SAR. */
export function archivePatternEvents(
  bars: Bar[],
  mode: ArchiveGuide,
  seconds: number,
  first = -Infinity,
  last = Infinity,
  session?: TrendSession | null,
  indian = false,
  includePendingShapes = false
): TimedArchiveMatch[] {
  if (mode === 'off' || !(seconds > 0) || !Number.isFinite(seconds)) return []
  const result: TimedArchiveMatch[] = [],
    segments: Bar[][] = []
  for (const bar of bars) {
    const tail = segments.at(-1)
    if (
      !tail ||
      ((bar.time - tail.at(-1)!.time > seconds * 1.5 || bar.time <= tail.at(-1)!.time) &&
        !isScheduledTrendGap(tail.at(-1)!.time, bar.time, seconds, session, indian))
    )
      segments.push([bar])
    else tail.push(bar)
  }
  for (const segment of segments) {
    const sar =
      mode !== 'candles'
        ? new Map(
            parabolicSAR(segment)
              .filter((p) => p.flip)
              .map((p) => [p.time, p])
          )
        : new Map()
    for (let i = 0; i < segment.length; i++) {
      const bar = segment[i]
      if (bar.time < first || bar.time > last) continue
      const prefix = segment.slice(Math.max(0, i - 159), i + 1)
      const matches: ArchiveMatch[] = []
      if (mode === 'all' || mode === 'candles')
        matches.push(
          ...recognizeArchiveCandles(prefix).map((match) => ({ ...match, confirmed: false }))
        )
      if (mode === 'all' || mode === 'shapes')
        matches.push(
          ...[
            ...recognizeChartShapes(prefix, includePendingShapes),
            ...recognizeFidelityShortPatterns(prefix),
            ...recognizeArchiveChartPatterns(prefix),
            ...recognizeHarmonicPatterns(prefix),
          ].map((match) => ({ ...match, confirmed: match.confirmed ?? true }))
        )
      if (mode !== 'candles')
        matches.push(
          ...recognizeInstitutionalPatterns(prefix).map((match) => ({ ...match, confirmed: true }))
        )
      if (mode !== 'shapes')
        matches.push(
          ...recognizeZoneConfirmations(prefix, recognizeArchiveCandles).map((match) => ({
            ...match,
            confirmed: true,
          })),
          ...recognizeCandleConfirmations(prefix, recognizeArchiveCandles)
        )
      const point = sar.get(bar.time)
      if (point)
        matches.push({
          side: point.side,
          name: 'Parabolic SAR flip',
          pattern: 'parabolic-sar-flip',
          confirmed: true,
          extreme: point.value,
        })
      for (const match of deduplicateArchiveMatches(matches))
        result.push({ ...match, time: bar.time })
    }
  }
  return result
}
