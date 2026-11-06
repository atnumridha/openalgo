import type { Bar } from './model'
import type { Pattern, PatternFamily } from './candlePatterns'

/** Operational definitions for the supplied 14-pattern reference, not proprietary trading rules.
 * Trend: four completed candles before the pattern, net move larger than half their average range.
 * Small bodies: <=35% of range; doji: <=10%; long shadow: >=2 bodies.
 * All observations come from the supplied history; confirmation/entry remains separate.
 */
export function recognizeGuideReversal(history: Bar[]): Pattern | null {
  if (
    history.some(
      (bar) =>
        ![bar.open, bar.high, bar.low, bar.close].every(Number.isFinite) ||
        bar.high < Math.max(bar.open, bar.close) ||
        bar.low > Math.min(bar.open, bar.close) ||
        bar.high <= bar.low
    )
  )
    return null
  const c = history.at(-1),
    p = history.at(-2),
    a = history.at(-3)
  if (!c) return null
  const body = (bar: Bar) => Math.abs(bar.close - bar.open)
  const range = c.high - c.low,
    b = body(c),
    upper = c.high - Math.max(c.open, c.close),
    lower = Math.min(c.open, c.close) - c.low
  const trend = (span: number): number => {
    const before = history.slice(0, -span).slice(-4)
    if (before.length < 4) return 0
    const move = before[3].close - before[0].close
    const average = before.reduce((sum, bar) => sum + bar.high - bar.low, 0) / 4
    return Math.abs(move) > average * 0.5 ? Math.sign(move) : 0
  }
  const result = (pattern: PatternFamily, bull: boolean, name: string, span: number): Pattern => ({
    pattern,
    side: bull ? 'CALL' : 'PUT',
    name,
    extreme: bull
      ? Math.min(...history.slice(-span).map((bar) => bar.low))
      : Math.max(...history.slice(-span).map((bar) => bar.high)),
  })
  const t3 = trend(3)
  if (p && a && body(a) > 0 && body(p) <= body(a) * 0.35 && b >= body(a) * 0.5) {
    if (
      t3 < 0 &&
      a.close < a.open &&
      c.close > c.open &&
      Math.max(p.open, p.close) <= a.close + body(a) * 0.25 &&
      c.close > (a.open + a.close) / 2
    )
      return result('guide-star', true, 'Morning Star', 3)
    if (
      t3 > 0 &&
      a.close > a.open &&
      c.close < c.open &&
      Math.min(p.open, p.close) >= a.close - body(a) * 0.25 &&
      c.close < (a.open + a.close) / 2
    )
      return result('guide-star', false, 'Evening Star', 3)
  }
  const t2 = trend(2)
  if (p) {
    if (
      t2 < 0 &&
      p.close < p.open &&
      c.close > c.open &&
      c.open <= p.close &&
      c.close >= p.open &&
      b > body(p)
    )
      return result('guide-engulfing', true, 'Bullish Engulfing', 2)
    if (
      t2 > 0 &&
      p.close > p.open &&
      c.close < c.open &&
      c.open >= p.close &&
      c.close <= p.open &&
      b > body(p)
    )
      return result('guide-engulfing', false, 'Bearish Engulfing', 2)
    if (
      t2 < 0 &&
      p.close < p.open &&
      c.close > c.open &&
      c.open > p.close &&
      c.close < p.open &&
      b <= body(p) * 0.6
    )
      return result('guide-harami', true, 'Bullish Harami', 2)
    if (
      t2 > 0 &&
      p.close > p.open &&
      c.close < c.open &&
      c.open < p.close &&
      c.close > p.open &&
      b <= body(p) * 0.6
    )
      return result('guide-harami', false, 'Bearish Harami', 2)
    if (
      t2 < 0 &&
      p.close < p.open &&
      c.close > c.open &&
      c.open <= p.close &&
      c.close > (p.open + p.close) / 2 &&
      c.close < p.open
    )
      return result('guide-piercing', true, 'Piercing Pattern', 2)
    if (
      t2 > 0 &&
      p.close > p.open &&
      c.close < c.open &&
      c.open >= p.close &&
      c.close < (p.open + p.close) / 2 &&
      c.close > p.open
    )
      return result('guide-piercing', false, 'Dark Cloud Cover', 2)
  }
  const t1 = trend(1)
  if (b <= range * 0.1) {
    if (t1 < 0 && lower >= range * 0.7 && upper <= range * 0.1)
      return result('guide-doji', true, 'Dragonfly Doji', 1)
    if (t1 > 0 && upper >= range * 0.7 && lower <= range * 0.1)
      return result('guide-doji', false, 'Gravestone Doji', 1)
    return null
  }
  if (b <= range * 0.35 && lower >= 2 * b && upper <= b * 0.5) {
    if (t1 < 0) return result('guide-hammer', true, 'Hammer', 1)
    if (t1 > 0) return result('guide-hammer', false, 'Hanging Man', 1)
  }
  if (b <= range * 0.35 && upper >= 2 * b && lower <= b * 0.5) {
    if (t1 < 0) return result('guide-inverted-hammer', true, 'Inverted Hammer', 1)
    if (t1 > 0) return result('guide-inverted-hammer', false, 'Shooting Star', 1)
  }
  return null
}
