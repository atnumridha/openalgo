import type { Bar } from './model'

export interface ArchiveCandleMatchA {
  side: 'CALL' | 'PUT' | 'NEUTRAL'
  name: string
  pattern: string
  extreme: number
}
const body = (b: Bar) => Math.abs(b.close - b.open)
const range = (b: Bar) => b.high - b.low
const upper = (b: Bar) => b.high - Math.max(b.open, b.close)
const lower = (b: Bar) => Math.min(b.open, b.close) - b.low
const up = (b: Bar) => b.close > b.open
const down = (b: Bar) => b.close < b.open
const long = (b: Bar) => body(b) >= range(b) * 0.55
const doji = (b: Bar) => body(b) <= range(b) * 0.1
const reflect = (b: Bar): Bar => ({
  ...b,
  open: -b.open,
  high: -b.low,
  low: -b.high,
  close: -b.close,
})

/** Additional archive observations, using final completed candles only.
 * Sources for names/geometry: https://ta-lib.org/functions/ and TA-Lib's
 * CDL{BELTHOLD,HARAMICROSS,HIGHWAVE,LONGLEGGEDDOJI,RICKSHAWMAN,DOJISTAR,
 * LONGLINE,SHORTLINE,MATCHINGLOW,HOMINGPIGEON,COUNTERATTACK,SEPARATINGLINES,
 * INNECK,ONNECK,THRUSTING} source. These are local operational thresholds,
 * not a TA-Lib port, confirmation forecast, or success probability.
 * Trend = net close movement of four bars BEFORE the whole pattern, exceeding
 * half their average range. Reversals require opposing trend; continuations
 * require same trend. Neutral range/body observations never imply a trade side.
 * Long body >=55% range; doji <=10%; short body <=35%. Equal prices tolerate
 * 5% of the larger range. Belt hold: opening shadow <=5%, body >=70%.
 * Pin: body <=30%, rejection shadow >=60%, opposite shadow <=15%.
 * High wave: body <=30%, each shadow >=30%; long-legged doji: each >=35%;
 * Rickshaw additionally has body midpoint within 10% of range midpoint.
 * Long/short line require body >=55% and each shadow <=20%; body must be
 * >=1.2 / <=0.6 times preceding four-body mean, respectively.
 * Inside/outside bars require strict FULL range nesting/engulfing, neutral
 * pending breakout. Window and island require strict FULL range gaps.
 * Two-candle doji star is distinct from the three-candle morning/evening star.
 * Northern/Southern Doji are contextual neutral aliases; no reversal inferred.
 * Mirrored neck labels explicitly denote reflected geometry, not standard names.
 */
export function recognizeArchiveCandlesA(history: Bar[]): ArchiveCandleMatchA[] {
  if (
    !history.length ||
    history.some(
      (b, i) =>
        ![b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) ||
        Math.min(b.open, b.high, b.low, b.close) <= 0 ||
        b.high <= b.low ||
        b.high < Math.max(b.open, b.close) ||
        b.low > Math.min(b.open, b.close) ||
        (i > 0 && b.time <= history[i - 1].time)
    )
  )
    return []
  const result: ArchiveCandleMatchA[] = []
  const last = history.at(-1)!
  const neutral = (name: string, id: string) =>
    result.push({ side: 'NEUTRAL', name, pattern: `archive-${id}`, extreme: last.close })
  const trend = (bars: Bar[], span: number) => {
    const prior = bars.slice(0, -span).slice(-4)
    if (prior.length !== 4) return 0
    const move = prior[3].close - prior[0].close
    return Math.abs(move) > prior.reduce((a, b) => a + range(b), 0) / 8 ? Math.sign(move) : 0
  }
  if (
    body(last) <= range(last) * 0.3 &&
    upper(last) >= range(last) * 0.3 &&
    lower(last) >= range(last) * 0.3
  )
    neutral('High Wave', 'high-wave')
  if (doji(last) && upper(last) >= range(last) * 0.35 && lower(last) >= range(last) * 0.35) {
    neutral('Long Legged Doji', 'long-legged-doji')
    if (Math.abs((last.open + last.close - last.high - last.low) / 2) <= range(last) * 0.1)
      neutral('Rickshaw Man', 'rickshaw-man')
  }
  if (doji(last) && trend(history, 1) !== 0)
    neutral(
      trend(history, 1) > 0 ? 'Northern Doji' : 'Southern Doji',
      trend(history, 1) > 0 ? 'northern-doji' : 'southern-doji'
    )
  const prior = history.slice(0, -1).slice(-4)
  if (
    prior.length === 4 &&
    long(last) &&
    upper(last) <= range(last) * 0.2 &&
    lower(last) <= range(last) * 0.2
  ) {
    const average = prior.reduce((a, b) => a + body(b), 0) / 4
    if (body(last) >= average * 1.2) neutral('Long Line', 'long-line')
    if (body(last) <= average * 0.6) neutral('Short Line', 'short-line')
  }
  const previous = history.at(-2)
  if (previous && last.high < previous.high && last.low > previous.low)
    neutral('Inside Bar', 'inside-bar')
  if (previous && last.high > previous.high && last.low < previous.low)
    neutral('Outside Bar', 'outside-bar')
  for (const bullish of [true, false]) {
    const bars = bullish ? history : history.map(reflect)
    const c = bars.at(-1)!,
      p = bars.at(-2),
      a = bars.at(-3)
    const add = (
      name: string,
      opposite: string,
      id: string,
      span: number,
      continuation = false
    ) => {
      const direction = bullish ? 1 : -1
      const side = (continuation ? -direction : direction) > 0 ? 'CALL' : 'PUT'
      const shape = history.slice(-span)
      result.push({
        side,
        name: bullish ? name : opposite,
        pattern: `archive-${id}-${bullish ? 'bull' : 'bear'}`,
        extreme:
          side === 'CALL'
            ? Math.min(...shape.map((b) => b.low))
            : Math.max(...shape.map((b) => b.high)),
      })
    }
    if (trend(bars, 1) < 0) {
      if (up(c) && body(c) >= range(c) * 0.7 && lower(c) <= range(c) * 0.05)
        add('Bullish Belt Hold', 'Bearish Belt Hold', 'belt-hold', 1)
      if (body(c) <= range(c) * 0.3 && lower(c) >= range(c) * 0.6 && upper(c) <= range(c) * 0.15)
        add('Bullish Pin Bar', 'Bearish Pin Bar', 'pin-bar', 1)
    }
    if (p) {
      const tolerance = Math.max(range(p), range(c)) * 0.05
      if (trend(bars, 2) < 0 && down(p) && long(p)) {
        if (doji(c) && Math.min(c.open, c.close) > p.close && Math.max(c.open, c.close) < p.open)
          add('Bullish Harami Cross', 'Bearish Harami Cross', 'harami-cross', 2)
        if (doji(c) && Math.max(c.open, c.close) < p.close)
          add('Bullish Doji Star', 'Bearish Doji Star', 'doji-star-two', 2)
        if (down(c) && Math.abs(c.close - p.close) <= tolerance)
          add('Matching Low', 'Matching High', 'matching', 2)
        if (down(c) && c.open < p.open && c.close > p.close && body(c) < body(p) * 0.6)
          add('Homing Pigeon', 'Descending Hawk', 'homing-pigeon', 2)
        if (up(c) && long(c) && c.open < p.close && Math.abs(c.close - p.close) <= tolerance)
          add(
            'Bullish Counterattack / Meeting Lines',
            'Bearish Counterattack / Meeting Lines',
            'counterattack',
            2
          )
        if (up(c) && c.open < p.low) {
          if (Math.abs(c.close - p.low) <= tolerance)
            add('On Neck', 'Mirrored On Neck', 'on-neck', 2, true)
          if (c.close > p.close && c.close <= p.close + tolerance)
            add('In Neck', 'Mirrored In Neck', 'in-neck', 2, true)
          if (c.close > p.close + tolerance && c.close < (p.open + p.close) / 2)
            add('Thrusting', 'Mirrored Thrusting', 'thrusting', 2, true)
        }
      }
      if (trend(bars, 2) > 0) {
        if (
          down(p) &&
          up(c) &&
          long(c) &&
          Math.abs(c.open - p.open) <= tolerance &&
          lower(c) <= range(c) * 0.05
        )
          add('Bullish Separating Lines', 'Bearish Separating Lines', 'separating-lines', 2)
        if (c.low > p.high) add('Rising Window', 'Falling Window', 'window', 2)
      }
    }
    if (a && p && trend(bars, 3) < 0 && down(a) && up(c) && p.high < a.low && c.low > p.high)
      add('Bullish Island Reversal', 'Bearish Island Reversal', 'island-reversal', 3)
  }
  return result
}
