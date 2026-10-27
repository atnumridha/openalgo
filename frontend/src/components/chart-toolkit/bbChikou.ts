import type { Bar } from './model'

export interface BBChikouSignal {
  time: number
  side: 'BULL' | 'BEAR'
  entry: number
  stop: number
  target: number
  price: number
}
export interface BBChikouResult {
  points: Array<{ time: number; upper: number | null; middle: number | null; lower: number | null }>
  chikou: Array<{ time: number; value: number }>
  signals: BBChikouSignal[]
  latest: BBChikouSignal | null
}
const valid = (b: Bar) =>
  [b.open, b.high, b.low, b.close].every(Number.isFinite) &&
  b.low <= Math.min(b.open, b.close) &&
  b.high >= Math.max(b.open, b.close)
const day = (time: number) => new Date((time + 19800) * 1000).toISOString().slice(0, 10)
const cashSession = (time: number, seconds: number) => {
  const local = new Date((time + 19800) * 1000)
  const second = local.getUTCHours() * 3600 + local.getUTCMinutes() * 60 + local.getUTCSeconds()
  return (
    seconds > 0 &&
    seconds < 86400 &&
    local.getUTCDay() >= 1 &&
    local.getUTCDay() <= 5 &&
    second >= 9 * 3600 + 15 * 60 &&
    second + seconds <= 15 * 3600 + 30 * 60
  )
}

// Native port of the Pine indicator's defaults. UTC seconds in and out.
// Uses price history only; neither order controls nor strategy state is involved.
export function calculateBBChikou(
  bars: Bar[],
  options: { seconds: number; asOf: number }
): BBChikouResult {
  const { seconds, asOf } = options
  const result: BBChikouResult = { points: [], chikou: [], signals: [], latest: null }
  let previousUpperTouch = false,
    previousLowerTouch = false
  let previousLongSetup = false,
    previousShortSetup = false
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i],
      previous = bars[i - 1]
    if (b.time > asOf) break
    const window = bars.slice(Math.max(0, i - 19), i + 1)
    const ready = window.length === 20 && window.every(valid)
    const middle = ready ? window.reduce((sum, p) => sum + p.close, 0) / 20 : null
    const deviation =
      middle == null
        ? null
        : 2 * Math.sqrt(window.reduce((sum, p) => sum + (p.close - middle) ** 2, 0) / 20)
    const upper = middle == null || deviation == null ? null : middle + deviation
    const lower = middle == null || deviation == null ? null : middle - deviation
    result.points.push({ time: b.time, upper, middle, lower })
    const closed = seconds > 0 && b.time + seconds <= asOf
    if (closed && previous && day(b.time) !== day(previous.time)) result.latest = null
    if (closed && valid(b) && i >= 26)
      result.chikou.push({ time: bars[i - 26].time, value: b.close })
    const upperTouch = upper != null && b.high >= upper
    const lowerTouch = lower != null && b.low <= lower
    const historyReady = i >= 26 && result.points[i - 2]?.middle != null && valid(bars[i - 26])
    const allowed = closed && valid(b) && cashSession(b.time, seconds) && historyReady
    const adjacent =
      previous &&
      valid(previous) &&
      b.time === previous.time + seconds &&
      day(b.time) === day(previous.time)
    if (allowed && adjacent && middle != null) {
      const bull =
        previousLongSetup &&
        b.close > previous.high &&
        b.close > bars[i - 26].high &&
        b.close > middle
      const bear =
        previousShortSetup &&
        b.close < previous.low &&
        b.close < bars[i - 26].low &&
        b.close < middle
      if (bull || bear) {
        const signal: BBChikouSignal = {
          time: b.time,
          side: bull ? 'BULL' : 'BEAR',
          entry: b.close,
          stop: middle,
          target: bull ? b.close + (b.close - middle) : b.close - (middle - b.close),
          price: bull ? b.low : b.high,
        }
        result.signals.push(signal)
        result.latest = signal
      }
    }
    previousLongSetup = allowed && upperTouch && !lowerTouch && !previousUpperTouch
    previousShortSetup = allowed && lowerTouch && !upperTouch && !previousLowerTouch
    previousUpperTouch = upperTouch
    previousLowerTouch = lowerTouch
  }
  return result
}
