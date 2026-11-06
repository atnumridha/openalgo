import { archivePatternEvents } from './archivePatternEngine'
import type { Bar } from './model'
import type { TrendSession } from './trendAnalysis'

/** Single production pipeline. Reference families feed the same completed-candle
 * confirmation path. Raw directional hints cannot appear as final signals.
 * Optional neutral observations carry no directional trade implication. */
export function finalPatternEvents(
  bars: Bar[],
  seconds: number,
  session?: TrendSession | null,
  indian = false
) {
  return archivePatternEvents(bars, 'all', seconds, -Infinity, Infinity, session, indian).filter(
    (match) => match.confirmed === true || match.side === 'NEUTRAL'
  )
}

import { latestArchiveReading, type TimedArchiveMatch } from './archiveConfirmations'
import { primaryArchiveLabels } from './archivePatternLabels'
/** One primary selection for markers and sidebar; conflicting confirmed directions wait. */
export function finalPatternReading(events: TimedArchiveMatch[], bars: Bar[]) {
  const last = bars.at(-1)
  if (!last) return latestArchiveReading([], bars)
  const candidates = events.filter(
    (match) =>
      match.time === last.time &&
      match.confirmed === true &&
      match.side !== 'NEUTRAL' &&
      Number.isFinite(match.extreme) &&
      (match.side === 'CALL' ? match.extreme < last.close : match.extreme > last.close)
  )
  if (new Set(candidates.map((match) => match.side)).size > 1)
    return { ...latestArchiveReading([], bars), name: 'Mixed signals' }
  return latestArchiveReading(primaryArchiveLabels(candidates), bars)
}
