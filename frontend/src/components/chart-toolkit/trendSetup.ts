import type { Bar } from './model'
import { isScheduledTrendGap, type TrendSession } from './trendAnalysis'

/** Shape geometry observed at confirmation; prices use underlying chart units. */
export interface TrendSetupEvent {
  time: number
  side: 'CALL' | 'PUT' | 'NEUTRAL'
  name: string
  confirmed?: boolean
  extreme: number
  entry?: number
  target?: number
  startTime?: number
  boundary?: Array<{ time: number; price: number }>
}

export interface TrendSetupTiming {
  seconds: number
  session?: TrendSession | null
  indian?: boolean
}

export interface TrendSetup {
  time: number
  side: 'CALL' | 'PUT'
  name: string
  entry: number
  stop: number
  target: number
  rewardRisk: number
  status: 'active' | 'stopped' | 'target-hit' | 'ambiguous'
  reason: string
  startTime?: number
  boundary?: Array<{ time: number; price: number }>
}

function tickRound(price: number, tick: number, up: boolean): number {
  const units = price / tick
  const nearest = Math.round(units)
  // Preserve exact tick prices despite binary floating point representation.
  const aligned = Math.abs(units - nearest) <= Number.EPSILON * Math.max(1, Math.abs(units)) * 4
  const rounded = aligned ? nearest : up ? Math.ceil(units) : Math.floor(units)
  return Number((rounded * tick).toPrecision(15))
}

/**
 * Replays completed bars only. The caller must exclude the forming candle.
 * Only the latest valid confirmed shape is considered; terminal setups never
 * fall back to an older shape. The confirmation bar cannot exit its own setup.
 */
export function selectTrendSetup(
  events: readonly TrendSetupEvent[],
  bars: readonly Bar[],
  tickSize: number,
  timing?: TrendSetupTiming
): TrendSetup | null {
  if (!Number.isFinite(tickSize) || tickSize <= 0) return null
  const anchors = new Set(bars.map((bar) => bar.time))
  const candidates: TrendSetup[] = []
  for (const event of events) {
    if (event.confirmed !== true || event.side === 'NEUTRAL' || !anchors.has(event.time)) continue
    if (!Number.isFinite(event.time)) continue
    if (![event.entry, event.target, event.extreme].every((value) => typeof value === 'number' && Number.isFinite(value) && value > 0)) continue
    const bullish = event.side === 'CALL'
    const entry = tickRound(event.entry!, tickSize, bullish)
    const stop = tickRound(event.extreme, tickSize, !bullish)
    const target = tickRound(event.target!, tickSize, !bullish)
    if (![entry, stop, target].every((value) => Number.isFinite(value) && value > 0)) continue
    if (bullish ? !(stop < entry && entry < target) : !(target < entry && entry < stop)) continue
    candidates.push({
      time: event.time, side: event.side, name: event.name, entry, stop, target,
      rewardRisk: Math.abs(target - entry) / Math.abs(entry - stop),
      status: 'active', reason: 'Confirmed shape; stop and target remain untouched.',
      startTime: event.startTime,
      boundary: event.boundary?.map((point) => ({ ...point })),
    })
  }
  const newestTime = Math.max(...candidates.map((candidate) => candidate.time))
  const newest = candidates.filter((candidate) => candidate.time === newestTime)
  if (!newest.length || new Set(newest.map((candidate) => candidate.side)).size > 1) return null
  const setup = newest[0]
  const bullish = setup.side === 'CALL'
  const chronological = [...bars].sort((a, b) => a.time - b.time)
  const intervals = chronological.slice(1)
    .map((bar, index) => bar.time - chronological[index].time)
    .filter((interval) => Number.isFinite(interval) && interval > 0)
    .sort((a, b) => a - b)
  // Lower median avoids letting one missing interval hide a short-history gap.
  const cadence = timing && Number.isFinite(timing.seconds) && timing.seconds > 0
    ? timing.seconds
    : intervals[Math.floor((intervals.length - 1) / 2)]
  let previousTime = setup.time
  for (const bar of chronological) {
    if (bar.time <= setup.time) continue
    if (cadence && bar.time - previousTime > cadence * 1.5
      && !isScheduledTrendGap(previousTime, bar.time, cadence, timing?.session, timing?.indian)) {
      setup.status = 'ambiguous'
      setup.reason = 'Missing completed candles leave a gap in the setup history.'
      break
    }
    if (![bar.open, bar.high, bar.low, bar.close].every((price) => Number.isFinite(price) && price > 0)
      || bar.high < Math.max(bar.open, bar.close, bar.low)
      || bar.low > Math.min(bar.open, bar.close, bar.high)) {
      setup.status = 'ambiguous'
      setup.reason = 'Invalid or incomplete candle prices prevent evaluating the setup.'
      break
    }
    previousTime = bar.time
    const openingStop = bullish ? bar.open <= setup.stop : bar.open >= setup.stop
    const openingTarget = bullish ? bar.open >= setup.target : bar.open <= setup.target
    const stopped = bullish ? bar.low <= setup.stop : bar.high >= setup.stop
    const targetHit = bullish ? bar.high >= setup.target : bar.low <= setup.target
    if (openingStop) {
      setup.status = 'stopped'
      setup.reason = 'A subsequent candle opened at or beyond the stop.'
    } else if (openingTarget) {
      setup.status = 'target-hit'
      setup.reason = 'A subsequent candle opened at or beyond the target.'
    } else if (stopped && targetHit) {
      setup.status = 'ambiguous'
      setup.reason = 'Stop and target were both touched in one candle; their order is unknown.'
    } else if (stopped) {
      setup.status = 'stopped'
      setup.reason = 'A subsequent completed candle touched the stop.'
    } else if (targetHit) {
      setup.status = 'target-hit'
      setup.reason = 'A subsequent completed candle touched the target.'
    }
    if (setup.status !== 'active') break
  }
  return setup
}
