import type { TimedArchiveMatch } from '../chart-toolkit/archiveConfirmations'
import type { Bar } from '../chart-toolkit/model'
import { deduplicateArchiveMatches } from '../chart-toolkit/archivePatternLabels'
import { comparePatternDisplay } from '../chart-toolkit/patternDisplaySelection'
import { isScheduledTrendGap, type TrendSession } from '../chart-toolkit/trendAnalysis'
import { patternExplanation } from '../chart-toolkit/patternExplanation'
export type PatternGuidanceStatus =
  | 'none'
  | 'neutral'
  | 'mixed'
  | 'confirmed'
  | 'active'
  | 'invalidated'
  | 'target'
  | 'ambiguous'
export interface PatternGuidance {
  status: PatternGuidanceStatus
  event: TimedArchiveMatch | null
  others: string[]
  otherCount: number
  side: 'CALL' | 'PUT' | 'NEUTRAL'
  explanation: string
  expectation: string
  next: string
  boundary: number | null
  stop: number | null
  target: number | null
  liveNote: string
}
const finitePrice = (n: unknown): n is number =>
  typeof n === 'number' && Number.isFinite(n) && n > 0
const validBar = (b: Bar) =>
  [b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) &&
  b.time > 0 &&
  b.low > 0 &&
  b.high >= Math.max(b.open, b.close, b.low) &&
  b.low <= Math.min(b.open, b.close)
function boundaryAt(e: TimedArchiveMatch, time: number) {
  const a = e.boundary?.at(-2),
    b = e.boundary?.at(-1)
  if (!a || !b || b.time <= a.time || !finitePrice(a.price) || !finitePrice(b.price)) return null
  const price = b.price + ((b.price - a.price) * (time - b.time)) / (b.time - a.time)
  return finitePrice(price) ? price : null
}
/** Lightweight guidance from the existing verified detections. It never detects an entry from a quote.
 * The caller supplies the source candle time only after live receipt/OHLC freshness checks. */
export function makePatternGuidance(
  events: readonly TimedArchiveMatch[],
  input: readonly Bar[],
  seconds: number,
  asOf: number,
  price: number | null,
  session?: TrendSession | null,
  indian = false,
  liveCandleTime: number | null = null
): PatternGuidance {
  const empty: PatternGuidance = {
    status: 'none',
    event: null,
    others: [],
    otherCount: 0,
    side: 'NEUTRAL',
    explanation: 'No matching confirmed pattern in the recent ten candles.',
    expectation: 'No pattern direction established.',
    next: 'Wait for a completed boundary break or candle confirmation.',
    boundary: null,
    stop: null,
    target: null,
    liveNote: '',
  }
  if (!Number.isFinite(seconds) || seconds <= 0 || !Number.isFinite(asOf)) return empty
  let bars: Bar[] = []
  for (const b of input) {
    if (b.time + seconds > asOf) continue
    if (!validBar(b)) {
      bars = []
      continue
    }
    const previous = bars.at(-1)
    if (
      previous &&
      b.time - previous.time !== seconds &&
      !isScheduledTrendGap(previous.time, b.time, seconds, session, indian)
    )
      bars = []
    bars.push(b)
  }
  const last = bars.at(-1)
  if (!last) return empty
  // Count the source chart's forming slot, without treating it as confirmed evidence.
  const hasLiveTime =
    liveCandleTime !== null && Number.isFinite(liveCandleTime) && liveCandleTime > last.time
  const hasFormingSlot =
    hasLiveTime ||
    input.some(
      (b) => validBar(b) && b.time > last.time && b.time <= asOf && b.time + seconds > asOf
    )
  const recent = new Map(bars.slice(hasFormingSlot ? -9 : -10).map((b) => [b.time, b]))
  const eligible = events.filter(
    (e) => recent.has(e.time) && (e.confirmed === true || e.side === 'NEUTRAL')
  )
  const latest = Math.max(...eligible.map((e) => e.time))
  const current = deduplicateArchiveMatches(eligible.filter((e) => e.time === latest))
  if (!current.length) return empty
  const directional = current.filter((e) => e.confirmed === true && e.side !== 'NEUTRAL')
  if (new Set(directional.map((e) => e.side)).size > 1)
    return {
      ...empty,
      status: 'mixed',
      others: current.slice(0, 3).map((e) => e.name),
      otherCount: current.length,
      explanation: 'Confirmed patterns at the same candle point in opposite directions.',
      expectation: 'Direction is unresolved.',
      next: 'Wait for the conflict to resolve on a later completed candle.',
    }
  const chosen = [...current].sort(comparePatternDisplay)[0]
  const stop = finitePrice(chosen.extreme) && chosen.side !== 'NEUTRAL' ? chosen.extreme : null
  const target = finitePrice(chosen.target) && chosen.side !== 'NEUTRAL' ? chosen.target : null
  const r: PatternGuidance = {
    ...empty,
    event: chosen,
    others: current
      .filter((e) => e !== chosen)
      .slice(0, 3)
      .map((e) => e.name),
    otherCount: current.length - 1,
    side: chosen.side,
    status:
      chosen.side === 'NEUTRAL' ? 'neutral' : chosen.time === last.time ? 'confirmed' : 'active',
    boundary: boundaryAt(chosen, hasLiveTime ? liveCandleTime : last.time),
    stop,
    target,
    explanation: patternExplanation(chosen.name, chosen.side, chosen.pattern)
      .split('\n')
      .slice(1, -2)
      .join(' '),
    expectation:
      chosen.side === 'CALL'
        ? 'An upward continuation or reversal is possible if buying holds the broken boundary.'
        : chosen.side === 'PUT'
          ? 'A downward continuation or reversal is possible if selling holds the broken boundary.'
          : 'Indecision; this pattern alone has no confirmed direction.',
    next:
      chosen.side === 'NEUTRAL'
        ? 'Wait for a directional completed close.'
        : chosen.boundary?.length
          ? 'Watch whether the broken boundary holds; a later retest and directional closing rejection can add evidence.'
          : 'Watch for follow-through beyond the confirmed candle; reassess if its structural extreme fails.',
  }
  if (chosen.side === 'NEUTRAL') return r
  const bull = chosen.side === 'CALL'
  // The confirming candle range predates knowledge of the pattern at its close.
  for (const b of bars.filter((b) => b.time > chosen.time)) {
    const stopped = stop !== null && (bull ? b.low <= stop : b.high >= stop)
    const reached = target !== null && (bull ? b.high >= target : b.low <= target)
    if (stopped || reached) {
      r.status = stopped && reached ? 'ambiguous' : stopped ? 'invalidated' : 'target'
      r.next =
        stopped && reached
          ? 'Both reference barriers were touched in one candle; their order is unknown. Wait for a new setup.'
          : stopped
            ? 'The structural invalidation reference was touched. Wait for a new confirmed setup.'
            : 'The projected target was touched. Reassess; this is not a fresh entry or an assumed profitable fill.'
      r.expectation = 'The previous directional reference has ended; a new pattern is needed.'
      return r
    }
    const boundary = boundaryAt(chosen, b.time)
    if (boundary !== null && (bull ? b.close <= boundary : b.close >= boundary)) {
      r.status = 'invalidated'
      r.next =
        'A completed close returned through the breakout boundary. The breakout failed; wait for a new setup.'
      r.expectation = 'The prior breakout expectation is no longer active.'
      return r
    }
  }
  if (finitePrice(price)) {
    if (stop !== null && (bull ? price <= stop : price >= stop))
      r.liveNote =
        'Price crossed the invalidation reference intrabar. Reassess; the candle is still forming.'
    else if (target !== null && (bull ? price >= target : price <= target))
      r.liveNote =
        'Price reached the projected target intrabar. Reassess; no fill or exit is assumed.'
    else if (hasLiveTime && r.boundary !== null)
      r.liveNote = (bull ? price > r.boundary : price < r.boundary)
        ? 'Live price is holding beyond the breakout boundary; wait for the candle close.'
        : 'Live price is back through the boundary intrabar; wait for the candle close.'
  }
  return r
}
export interface CandleProgress {
  state: 'history' | 'stale' | 'waiting' | 'forming'
  direction?: 'bullish' | 'bearish' | 'flat'
  remaining?: number
}
/** Receipts, not a wall clock alone, prove that the current candle is live. */
export function liveCandleProgress(
  bar: Bar | null,
  seconds: number,
  observed: number | null,
  now: number,
  live: boolean
): CandleProgress {
  if (!live) return { state: 'history' }
  if (
    !observed ||
    !Number.isFinite(observed) ||
    !Number.isFinite(now) ||
    observed > now ||
    now - observed > 15
  )
    return { state: 'stale' }
  if (
    !bar ||
    !validBar(bar) ||
    !(seconds > 0) ||
    !Number.isFinite(seconds) ||
    now < bar.time ||
    now >= bar.time + seconds ||
    observed < bar.time
  )
    return { state: 'waiting' }
  return {
    state: 'forming',
    direction: bar.close > bar.open ? 'bullish' : bar.close < bar.open ? 'bearish' : 'flat',
    remaining: Math.ceil(bar.time + seconds - now),
  }
}
