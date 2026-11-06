import type { PlanSession } from '../neo-desk/chartTradePlan'
import { closeTime, type Bar } from './model'

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

const dailyAdjacent = (before: number, after: number) => {
  const previous = Math.floor((before + 19800) / 86400),
    current = Math.floor((after + 19800) / 86400)
  let next = previous + 1
  while ([0, 6].includes(new Date(next * 86400000).getUTCDay())) next++
  return next === current
}
// Native port of the Pine indicator's defaults. UTC seconds in and out.
// Uses price history only; neither order controls nor strategy state is involved.
export function calculateBBChikou(
  bars: Bar[],
  options: {
    seconds: number
    asOf: number
    continuous?: boolean
    reward?: 1 | 2
    tickSize?: number
    session?: PlanSession | null
    longOnly?: boolean
  }
): BBChikouResult {
  const { seconds, asOf, continuous = false, reward = 1, tickSize = 0, session } = options
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
    const closed = seconds > 0 && closeTime(b, seconds, !!session, session) <= asOf
    if (!continuous && seconds < 86400 && closed && previous && day(b.time) !== day(previous.time))
      result.latest = null
    if (closed && valid(b) && i >= 26)
      result.chikou.push({ time: bars[i - 26].time, value: b.close })
    const upperTouch = upper != null && b.high >= upper
    const lowerTouch = lower != null && b.low <= lower
    const historyReady = i >= 26 && result.points[i - 2]?.middle != null && valid(bars[i - 26])
    const minute = Math.floor(((b.time + (session?.offset ?? 19800)) % 86400) / 60)
    const weekday = new Date((b.time + (session?.offset ?? 19800)) * 1000).getUTCDay()
    // Daily bars identify a trading date; their midnight stamp is not an intraday quote.
    // closeTime above still requires that date's actual session close before confirmation.
    const inSession =
      continuous ||
      (seconds >= 86400
        ? !!session && weekday >= 1 && weekday <= 5
        : session
          ? minute >= session.start && minute < session.end
          : cashSession(b.time, seconds))
    const consecutive = bars
      .slice(Math.max(0, i - 26), i + 1)
      .every((bar, j, all) => j === 0 || bar.time - all[j - 1].time === seconds)
    const allowed = closed && valid(b) && inSession && historyReady && (!continuous || consecutive)
    const adjacent =
      previous &&
      valid(previous) &&
      (b.time === previous.time + seconds ||
        (seconds >= 86400 && dailyAdjacent(previous.time, b.time))) &&
      (continuous || seconds >= 86400 || day(b.time) === day(previous.time))
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
        const stop =
          tickSize > 0
            ? Number(
                (
                  (bull ? Math.floor : Math.ceil)(middle / tickSize + (bull ? 1e-8 : -1e-8)) *
                  tickSize
                ).toFixed(8)
              )
            : middle
        const target = Number(
          (b.close + (bull ? 1 : -1) * reward * Math.abs(b.close - stop)).toFixed(8)
        )
        if (stop <= 0 || target <= 0) continue
        const signal: BBChikouSignal = {
          time: b.time,
          side: bull ? 'BULL' : 'BEAR',
          entry: b.close,
          stop,
          target,
          price: bull ? b.low : b.high,
        }
        result.signals.push(signal)
        result.latest = options.longOnly && !bull ? null : signal
      }
    }
    previousLongSetup = allowed && upperTouch && !lowerTouch && !previousUpperTouch
    previousShortSetup = allowed && lowerTouch && !upperTouch && !previousLowerTouch
    previousUpperTouch = upperTouch
    previousLowerTouch = lowerTouch
  }
  return result
}
