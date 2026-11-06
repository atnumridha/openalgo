import type { Bar } from '../chart-toolkit/model'
import type { TrendDirection } from '../chart-toolkit/trendAnalysis'
export interface DeltaRiskContext {
  symbol: string
  intervalSeconds: number
  sourceTime: number
  observedAt: number
  direction: TrendDirection
  trendReason?: string
  trendSummary?: string
  /** Optional strict execution-data deadline, in UTC seconds; never limits existing protection. */
  entryExpiresAt?: number
  entryAligned?: boolean
  bars: readonly Bar[]
  support: number | null
  resistance: number | null
}
export interface DeltaProtectionPlan {
  stop: number
  target: number
  source_time: number
  interval_seconds: number
  reason: string
}
const positive = (v: number) => Number.isFinite(v) && v > 0
const rounded = (v: number, tick: number, up: boolean) => {
  const ticks = v / tick
  const nearest = Math.round(ticks)
  const normalized = Math.abs(ticks - nearest) <= Number.EPSILON * Math.max(1, Math.abs(ticks)) * 8 ? nearest : ticks
  return Number(((up ? Math.ceil : Math.floor)(normalized) * tick).toPrecision(12))
}
export function deltaRiskAtr(
  context: DeltaRiskContext | null,
  now = Date.now() / 1000
): number | null {
  if (
    !context ||
    !positive(context.intervalSeconds) ||
    !positive(context.observedAt) ||
    context.observedAt > now + 5 ||
    now - context.observedAt > context.intervalSeconds * 2 + 10
  )
    return null
  const bars = context.bars.slice(-15)
  if (
    bars.length < 15 ||
    bars.at(-1)?.time !== context.sourceTime ||
    now - (context.sourceTime + context.intervalSeconds) > context.intervalSeconds * 2 + 10 ||
    bars.some(
      (bar, i) =>
        ![bar.time, bar.open, bar.high, bar.low, bar.close].every(Number.isFinite) ||
        Math.min(bar.open, bar.high, bar.low, bar.close) <= 0 ||
        bar.high < Math.max(bar.open, bar.low, bar.close) ||
        bar.low > Math.min(bar.open, bar.close) ||
        bar.time + context.intervalSeconds > context.observedAt ||
        bar.time + context.intervalSeconds > now ||
        (i > 0 && bar.time - bars[i - 1].time !== context.intervalSeconds)
    )
  )
    return null
  const atr =
    bars
      .slice(1)
      .reduce(
        (sum, bar, i) =>
          sum +
          Math.max(
            bar.high - bar.low,
            Math.abs(bar.high - bars[i].close),
            Math.abs(bar.low - bars[i].close)
          ),
        0
      ) / 14
  return positive(atr) ? atr : null
}
export function deltaEntryPauseReason(
  context: DeltaRiskContext | null,
  side: 'buy' | 'sell',
  entry: number,
  now = Date.now() / 1000
): string | null {
  const atr = deltaRiskAtr(context, now)
  if (!context || atr === null || !positive(entry)) return null
  const latest = context.bars.at(-1)!,
    long = side === 'buy'
  if (context.direction === 'sideways')
    return context.trendReason || 'No confirmed trend yet. Entry is paused.'
  if (context.direction === 'unavailable')
    return 'The closed-candle trend could not be checked. Entry is paused.'
  if (context.direction !== (long ? 'up' : 'down'))
    return long
      ? 'Trend is down. Long is paused; wait for a confirmed uptrend.'
      : 'Trend is up. Short is paused; wait for a confirmed downtrend.'
  if (context.entryAligned === false)
    return (
      context.trendReason ||
      'The current and higher chart timeframes do not confirm the same direction. Entry is paused.'
    )
  const gap = (entry - latest.close) * (long ? 1 : -1)
  if (gap > atr * 0.5 || gap < -atr)
    return 'Price moved too far from the last confirmed candle. Wait for a pullback or a new confirmed setup.'
  if (latest.high - latest.low > atr * 2 || Math.abs(latest.close - latest.open) > atr * 1.5)
    return 'A sharp move just finished. Wait for a pullback or another confirmed candle.'
  if (
    (long &&
      context.resistance != null &&
      context.resistance > latest.close &&
      entry >= context.resistance) ||
    (!long && context.support != null && context.support < latest.close && entry <= context.support)
  )
    return 'This breakout has not closed beyond support or resistance. Entry is paused.'
  return null
}

/** One calculation supplies both the order plan and its precise rejection reason. */
function evaluateDeltaProtection(
  context: DeltaRiskContext | null,
  side: 'buy' | 'sell',
  entry: number,
  tick: number,
  now: number,
  mode: 'entry' | 'position' | 'manual'
): { plan: DeltaProtectionPlan | null; reason: string | null } {
  const reject = (reason: string) => ({ plan: null, reason })
  if (!context)
    return reject(
      'The current chart has no verified closed-candle context for an automatic SL and target.'
    )
  const atr = deltaRiskAtr(context, now)
  if (atr === null)
    return reject(
      'The SL calculation has stale or incomplete candle history. Waiting for fresh verified candles.'
    )
  if (!positive(entry) || !positive(tick))
    return reject('A valid entry price and contract tick size are required for the SL and target.')
  if (
    mode !== 'position' &&
    context.entryExpiresAt !== undefined &&
    (!Number.isFinite(context.entryExpiresAt) || now > context.entryExpiresAt)
  )
    return reject('Scalping data expired. Waiting for fresh 1m and 5m candles.')
  const long = side === 'buy'
  if (mode === 'entry') {
    const pause = deltaEntryPauseReason(context, side, entry, now)
    if (pause) return reject(pause)
  }
  const level = long ? context.support : context.resistance
  const structural =
    level != null && positive(level) && (long ? level < entry : level > entry)
      ? Math.abs(entry - level) + atr * 0.25
      : atr * 1.5
  const risk = Math.max(atr, Math.min(atr * (context.entryExpiresAt !== undefined ? 1.5 : 3), structural), tick * 3)
  const stop = rounded(entry + (long ? -risk : risk), tick, !long)
  const actualRisk = Math.abs(entry - stop)
  const target = rounded(entry + (long ? 2 * actualRisk : -2 * actualRisk), tick, !long)
  if (
    !positive(stop) ||
    !positive(target) ||
    (long ? stop >= entry || target <= entry : stop <= entry || target >= entry)
  )
    return reject('The rounded SL or target is on the wrong side of entry. No order was sent.')
  return {
    plan: {
      stop,
      target,
      source_time: context.sourceTime,
      interval_seconds: context.intervalSeconds,
      reason:
        mode === 'entry'
          ? 'Closed-candle EMA trend + ATR/structure SL; fixed 2R target.'
          : mode === 'manual'
            ? 'Manual maker entry: ATR/structure SL, 2R target and fee-aware trailing; trend approval bypassed.'
            : 'Existing-position protection: ATR stop and 2R target; does not authorize a new entry.',
    },
    reason: null,
  }
}
export function buildDeltaProtection(
  context: DeltaRiskContext | null,
  side: 'buy' | 'sell',
  entry: number,
  tick: number,
  now = Date.now() / 1000,
  mode: 'entry' | 'position' | 'manual' = 'entry'
): DeltaProtectionPlan | null {
  return evaluateDeltaProtection(context, side, entry, tick, now, mode).plan
}
export function deltaProtectionPauseReason(
  context: DeltaRiskContext | null,
  side: 'buy' | 'sell',
  entry: number,
  tick: number,
  now = Date.now() / 1000
): string | null {
  return evaluateDeltaProtection(context, side, entry, tick, now, 'entry').reason
}
/** Protect fee-covered gains after a volatility buffer; subsequent trailing never widens a stop. */
export function deltaTrailingStop(
  context: DeltaRiskContext | null,
  side: 'buy' | 'sell',
  entry: number,
  initialStop: number,
  currentStop: number,
  mark: number,
  tick: number,
  feePerCoin: number | null,
  now = Date.now() / 1000,
  allowCountertrend = false,
  smartProfitPerCoin: number | null = null
): number | null {
  const atr = deltaRiskAtr(context, now)
  const long = side === 'buy'
  if (
    !context ||
    atr === null ||
    ![entry, initialStop, currentStop, mark, tick].every(positive) ||
    feePerCoin == null ||
    !Number.isFinite(feePerCoin) ||
    feePerCoin < 0 ||
    (!allowCountertrend &&
      context.direction !== (long ? 'up' : 'down') &&
      context.direction !== 'sideways')
  )
    return null
  const risk = Math.abs(entry - initialStop),
    profit = (mark - entry) * (long ? 1 : -1)
  const smart = smartProfitPerCoin !== null && positive(smartProfitPerCoin)
  if (risk < tick || profit < feePerCoin + (smart ? smartProfitPerCoin + tick * 2 : Math.max(atr * 0.5, tick * 4))) return null
  const breakeven = entry + (long ? 1 : -1) * (feePerCoin + tick * 2)
  let next = smart
    ? entry + (long ? 1 : -1) * (feePerCoin + Math.max(smartProfitPerCoin!, profit - feePerCoin - (profit - feePerCoin > smartProfitPerCoin! * 3 ? smartProfitPerCoin! / 2 : smartProfitPerCoin!)))
    : breakeven
  if (profit >= risk * 1.5) {
    const level = long ? context.support : context.resistance
    const trailing = mark + (long ? -atr : atr)
    next = long ? Math.max(next, trailing, level ?? 0) : Math.min(next, trailing, level ?? Infinity)
  }
  next = rounded(next, tick, smart ? long : !long)
  if (
    !positive(next) ||
    (long ? next <= currentStop || next >= mark - tick : next >= currentStop || next <= mark + tick)
  )
    return null
  return next
}

/** Reduces possible loss without claiming to protect profit. */
export function deltaRiskReductionStop(context: DeltaRiskContext | null, side: 'buy' | 'sell', entry: number,
  initialStop: number, currentStop: number, mark: number, tick: number, now = Date.now() / 1000): number | null {
  if (deltaRiskAtr(context, now) === null || ![entry, initialStop, currentStop, mark, tick].every(positive)) return null
  const long = side === 'buy', risk = Math.abs(entry - initialStop)
  if (risk < tick || (mark - entry) * (long ? 1 : -1) < Math.max(risk / 3, tick * 4)) return null
  const next = rounded(entry + (long ? -1 : 1) * risk / 2, tick, !long)
  if (long ? next <= currentStop || next >= entry || next >= mark - tick : next >= currentStop || next <= entry || next <= mark + tick) return null
  return next
}
