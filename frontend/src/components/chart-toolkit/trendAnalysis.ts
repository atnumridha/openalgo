import type { Bar } from './model'

export type TrendDirection = 'up' | 'down' | 'sideways' | 'unavailable'
export interface TrendReading {
  direction: TrendDirection
  label: string
  reason: string
  time: number | null
  emaFast: number | null
  emaSlow: number | null
}
export interface CombinedTrend {
  direction: TrendDirection
  reason: string
  aligned: boolean
}

export function higherTrendInterval(interval: string): string | null {
  const intervals: Record<string, string> = {
    '1m': '5m',
    '3m': '15m',
    '5m': '15m',
    '15m': '1h',
    '30m': '1d',
    '1h': '1d',
  }
  return Object.hasOwn(intervals, interval) ? intervals[interval] : null
}
export interface TrendSession {
  start: number
  end: number
  offset: number
}
export interface TrendTimingOptions {
  seconds: number
  session?: TrendSession | null
  indian?: boolean
}

/** Scheduled cash-market closures are not missing candles. Times are UTC seconds. */
export function isScheduledTrendGap(
  previousTime: number,
  nextTime: number,
  seconds: number,
  session?: TrendSession | null,
  indian = false
): boolean {
  const window = session ?? (indian ? { start: 555, end: 930, offset: 19800 } : null)
  if (
    !window ||
    ![previousTime, nextTime, seconds, window.start, window.end, window.offset].every(
      Number.isFinite
    ) ||
    seconds <= 0 ||
    window.start < 0 ||
    window.end > 1440 ||
    window.end <= window.start ||
    window.end - window.start >= 1440
  )
    return false
  const previousDay = Math.floor((previousTime + window.offset) / 86400) * 86400 - window.offset
  const nextDay = Math.floor((nextTime + window.offset) / 86400) * 86400 - window.offset
  const days = (nextDay - previousDay) / 86400
  if (days < 1 || days > 5) return false
  // Daily provider timestamps may use midnight or the session opening clock.
  if (seconds === 86400) return nextTime - nextDay === previousTime - previousDay
  if (seconds > 86400) return false
  const start = previousDay + window.start * 60,
    end = previousDay + window.end * 60
  return (
    previousTime >= start &&
    previousTime < end &&
    previousTime + seconds >= end &&
    nextTime === nextDay + window.start * 60
  )
}

const valid = (b: Bar) =>
  [b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) &&
  b.time >= 0 &&
  Math.min(b.open, b.high, b.low, b.close) > 0 &&
  b.high >= Math.max(b.open, b.close, b.low) &&
  b.low <= Math.min(b.open, b.close)

/** Caller supplies only completed candles, in UTC and chronological order.
 * Calculations use only this prefix: two right candles must exist before a swing
 * can participate. Invalid candles and missing trading intervals reset evidence.
 * Explicit timing preserves scheduled cash-session closures; without timing,
 * gaps >3x the preceding median cadence reset. No synthetic candles are added.
 */
export function analyzeTrend(bars: readonly Bar[], options?: TrendTimingOptions): TrendReading {
  let segment: Bar[] = []
  let gaps: number[] = []
  for (const bar of bars) {
    const previous = segment.at(-1)
    if (!valid(bar)) {
      segment = []
      gaps = []
      continue
    }
    if (previous) {
      const gap = bar.time - previous.time
      const sorted = [...gaps].sort((a, b) => a - b)
      const cadence = sorted.length ? sorted[Math.floor(sorted.length / 2)] : null
      const scheduled =
        options &&
        isScheduledTrendGap(
          previous.time,
          bar.time,
          options.seconds,
          options.session,
          options.indian
        )
      const interrupted = options
        ? gap !== options.seconds && !scheduled
        : cadence !== null && gap > 3 * cadence
      if (gap <= 0 || interrupted) {
        segment = []
        gaps = []
      } else if (!scheduled) {
        gaps.push(gap)
        if (gaps.length > 20) gaps.shift()
      }
    }
    segment.push(bar)
  }
  const last = segment.at(-1)
  const unavailable = (reason: string): TrendReading => ({
    direction: 'unavailable',
    label: 'Unavailable',
    reason,
    time: last?.time ?? null,
    emaFast: null,
    emaSlow: null,
  })
  if (segment.length < 55)
    return unavailable('Trend history is warming up after the latest start or interruption')

  // Seed each EMA with its period's simple mean. Five completed bars define slope.
  const averages = (period: number) => {
    let value = segment.slice(0, period).reduce((sum, b) => sum + b.close, 0) / period
    const values = [value]
    for (let i = period; i < segment.length; i++) {
      value += (2 / (period + 1)) * (segment[i].close - value)
      values.push(value)
    }
    return { value, slope: value - values[values.length - 6] }
  }
  const fast = averages(20),
    slow = averages(50)
  const recent = segment.slice(-14)
  const atr =
    recent.reduce((sum, b, i) => {
      const previous = segment[segment.length - 14 + i - 1]
      return (
        sum +
        Math.max(
          b.high - b.low,
          Math.abs(b.high - previous.close),
          Math.abs(b.low - previous.close)
        )
      )
    }, 0) / 14
  // Ignore movement below one tenth of a recent true range over five bars.
  const threshold = Math.max(atr * 0.1, last!.close * 1e-8)
  const highs: number[] = [],
    lows: number[] = []
  for (let i = 2; i < segment.length - 2; i++) {
    const b = segment[i],
      left = segment.slice(i - 2, i),
      right = segment.slice(i + 1, i + 3)
    if (left.every((x) => x.high < b.high) && right.every((x) => x.high <= b.high))
      highs.push(b.high)
    if (left.every((x) => x.low > b.low) && right.every((x) => x.low >= b.low)) lows.push(b.low)
  }
  const enoughSwings = highs.length >= 2 && lows.length >= 2
  const higher =
    (highs.length < 2 || highs.at(-1)! > highs.at(-2)!) &&
    (lows.length < 2 || lows.at(-1)! > lows.at(-2)!)
  const lower =
    (highs.length < 2 || highs.at(-1)! < highs.at(-2)!) &&
    (lows.length < 2 || lows.at(-1)! < lows.at(-2)!)
  const up =
    fast.value > slow.value &&
    fast.slope > threshold &&
    slow.slope > threshold &&
    last!.close > fast.value &&
    last!.close > slow.value
  const down =
    fast.value < slow.value &&
    fast.slope < -threshold &&
    slow.slope < -threshold &&
    last!.close < fast.value &&
    last!.close < slow.value
  // A completed break through both prior confirmed levels supersedes the old
  // opposing swing comparison. The current candle's wick cannot confirm it.
  const resistance = highs.length >= 2 ? Math.max(...highs.slice(-2)) : null
  const support = lows.length >= 2 ? Math.min(...lows.slice(-2)) : null
  const brokeUp = resistance !== null && last!.close > resistance
  const brokeDown = support !== null && last!.close < support
  const direction: TrendDirection =
    up && (higher || brokeUp) ? 'up' : down && (lower || brokeDown) ? 'down' : 'sideways'
  const quiet =
    Math.abs(fast.slope) <= threshold &&
    Math.abs(slow.slope) <= threshold &&
    Math.abs(fast.value - slow.value) <= atr * 0.5
  const pressure =
    last!.close < Math.min(fast.value, slow.value)
      ? 'falling'
      : last!.close > Math.max(fast.value, slow.value)
        ? 'rising'
        : null
  const label =
    direction === 'up'
      ? 'Uptrend'
      : direction === 'down'
        ? 'Downtrend'
        : quiet
          ? 'Sideways'
          : pressure === 'falling'
            ? 'Falling · unconfirmed'
            : pressure === 'rising'
              ? 'Rising · unconfirmed'
              : 'Mixed direction'
  const fmt = (n: number) => n.toLocaleString('en-IN', { maximumFractionDigits: 2 })
  const waiting = (rising: boolean) => {
    const rules: string[] = []
    if (rising ? fast.value <= slow.value : fast.value >= slow.value)
      rules.push(`EMA20 to move ${rising ? 'above' : 'below'} EMA50`)
    if (rising ? fast.slope <= threshold : fast.slope >= -threshold)
      rules.push(`EMA20 to keep ${rising ? 'rising' : 'falling'}`)
    if (rising ? slow.slope <= threshold : slow.slope >= -threshold)
      rules.push(`EMA50 to keep ${rising ? 'rising' : 'falling'}`)
    if (
      !(rising ? brokeUp : brokeDown) &&
      highs.length >= 2 &&
      (rising ? highs.at(-1)! <= highs.at(-2)! : highs.at(-1)! >= highs.at(-2)!)
    )
      rules.push(
        `a ${rising ? 'higher' : 'lower'} swing high (latest ${fmt(highs.at(-1)!)}, previous ${fmt(highs.at(-2)!)})`
      )
    if (
      !(rising ? brokeUp : brokeDown) &&
      lows.length >= 2 &&
      (rising ? lows.at(-1)! <= lows.at(-2)! : lows.at(-1)! >= lows.at(-2)!)
    )
      rules.push(
        `a ${rising ? 'higher' : 'lower'} swing low (latest ${fmt(lows.at(-1)!)}, previous ${fmt(lows.at(-2)!)})`
      )
    return `Price is ${rising ? 'rising' : 'falling'}. Trend is not confirmed. Waiting for ${rules.join('; ')}.`
  }
  const reason =
    direction === 'up'
      ? !higher && brokeUp
        ? `Closed above confirmed resistance ${fmt(resistance!)}; EMA20 and EMA50 rise`
        : enoughSwings
          ? 'EMA20 and EMA50 rise with higher confirmed swing highs and lows'
          : 'Price and moving averages rise; swing confirmation pending'
      : direction === 'down'
        ? !lower && brokeDown
          ? `Closed below confirmed support ${fmt(support!)}; EMA20 and EMA50 fall`
          : enoughSwings
            ? 'EMA20 and EMA50 fall with lower confirmed swing highs and lows'
            : 'Price and moving averages fall; swing confirmation pending'
        : quiet
          ? 'The moving averages are flat. No clear trend is confirmed.'
          : pressure === 'falling'
            ? waiting(false)
            : pressure === 'rising'
              ? waiting(true)
              : 'Price, moving averages and price swings disagree. No direction is confirmed.'
  return {
    direction,
    label,
    reason,
    time: last!.time,
    emaFast: fast.value,
    emaSlow: slow.value,
  }
}

export function combineTrend(current: TrendReading, higher: TrendReading | null): CombinedTrend {
  if (current.direction === 'unavailable' || !higher || higher.direction === 'unavailable')
    return {
      direction: 'unavailable',
      reason: 'Wait for a current and higher timeframe reading',
      aligned: false,
    }
  if (
    (current.direction === 'up' || current.direction === 'down') &&
    current.direction === higher.direction
  )
    return {
      direction: current.direction,
      reason: `Both timeframes point ${current.direction}`,
      aligned: true,
    }
  return {
    direction: 'sideways',
    reason: 'Wait: the current and higher timeframe do not share a clear direction',
    aligned: false,
  }
}

/** Display only: mixed readings retain the same entry eligibility. */
export function trendSummaryLabel(
  current: TrendReading,
  higher: TrendReading | null,
  live = true
): string {
  const combined = combineTrend(current, higher)
  if (combined.direction === 'up') return 'Uptrend'
  if (combined.direction === 'down') return 'Downtrend'
  if (combined.direction === 'unavailable') return live ? 'Checking candles' : 'Historical view'
  return current.label === 'Sideways' && higher?.label === 'Sideways' ? 'Sideways' : 'Not confirmed'
}
