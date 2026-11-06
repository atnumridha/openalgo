import type { Bar } from './model'
import { recognizeGuideReversal } from './pinterestCandlePatterns'
export const CANDLE_PATTERNS = [
  ['all', 'All patterns'],
  ['pinterest-reversals', 'Pinterest guide · 14 reversal patterns'],
  ['engulfing', 'Engulfing'],
  ['rejection', 'Wick rejection'],
  ['inside-break', 'Inside-bar breakout'],
  ['star', 'Morning / evening star'],
  ['marubozu', 'Marubozu'],
  ['three-candles', 'Three advancing / declining candles'],
  ['piercing', 'Piercing / dark cloud'],
] as const
export type PatternSelection = (typeof CANDLE_PATTERNS)[number][0]
export type PatternFamily =
  | Exclude<PatternSelection, 'all' | 'pinterest-reversals'>
  | 'guide-hammer'
  | 'guide-inverted-hammer'
  | 'guide-doji'
  | 'guide-engulfing'
  | 'guide-harami'
  | 'guide-piercing'
  | 'guide-star'
export const isPatternSelection = (v: unknown): v is PatternSelection =>
  CANDLE_PATTERNS.some(([key]) => key === v)
export interface Pattern {
  side: 'CALL' | 'PUT'
  pattern: PatternFamily
  name: string
  extreme: number
}
export function recognizePattern(
  history: Bar[],
  selected: PatternSelection = 'all'
): Pattern | null {
  if (selected === 'pinterest-reversals') return recognizeGuideReversal(history)
  const c = history.at(-1),
    p = history.at(-2),
    a = history.at(-3)
  if (!c || !p || !a) return null
  const body = Math.abs(c.close - c.open),
    range = c.high - c.low,
    pb = Math.abs(p.close - p.open),
    ab = Math.abs(a.close - a.open)
  if (!(range > 0 && body > range * 0.05)) return null
  const allow = (family: PatternFamily) => selected === 'all' || selected === family
  const result = (
    pattern: PatternFamily,
    bull: boolean,
    name: string,
    extreme: number
  ): Pattern => ({ pattern, side: bull ? 'CALL' : 'PUT', name, extreme })
  if (allow('engulfing')) {
    if (p.close < p.open && c.close > c.open && c.open <= p.close && c.close >= p.open && body > pb)
      return result('engulfing', true, 'Bullish engulfing', Math.min(c.low, p.low))
    if (p.close > p.open && c.close < c.open && c.open >= p.close && c.close <= p.open && body > pb)
      return result('engulfing', false, 'Bearish engulfing', Math.max(c.high, p.high))
  }
  if (allow('rejection')) {
    if (
      Math.min(c.open, c.close) - c.low >= 2 * body &&
      c.high - Math.max(c.open, c.close) <= body * 0.5 &&
      c.close >= c.low + range * 0.65
    )
      return result('rejection', true, 'Lower-wick rejection', c.low)
    if (
      c.high - Math.max(c.open, c.close) >= 2 * body &&
      Math.min(c.open, c.close) - c.low <= body * 0.5 &&
      c.close <= c.low + range * 0.35
    )
      return result('rejection', false, 'Upper-wick rejection', c.high)
  }
  if (allow('inside-break') && p.high < a.high && p.low > a.low) {
    if (c.close > a.high && c.close > c.open)
      return result('inside-break', true, 'Bullish inside-bar break', Math.min(c.low, p.low))
    if (c.close < a.low && c.close < c.open)
      return result('inside-break', false, 'Bearish inside-bar break', Math.max(c.high, p.high))
  }
  if (allow('star') && ab > 0 && pb <= ab * 0.35 && body >= ab * 0.5) {
    if (
      a.close < a.open &&
      Math.max(p.open, p.close) <= a.close + ab * 0.25 &&
      c.close > c.open &&
      c.close > (a.open + a.close) / 2
    )
      return result('star', true, 'Morning star', Math.min(a.low, p.low, c.low))
    if (
      a.close > a.open &&
      Math.min(p.open, p.close) >= a.close - ab * 0.25 &&
      c.close < c.open &&
      c.close < (a.open + a.close) / 2
    )
      return result('star', false, 'Evening star', Math.max(a.high, p.high, c.high))
  }
  if (allow('marubozu') && body >= range * 0.85)
    return result(
      'marubozu',
      c.close > c.open,
      c.close > c.open ? 'Bullish marubozu' : 'Bearish marubozu',
      c.close > c.open ? c.low : c.high
    )
  if (
    allow('three-candles') &&
    [a, p, c].every((b) => Math.abs(b.close - b.open) >= (b.high - b.low) * 0.6)
  ) {
    if (
      [a, p, c].every((b) => b.close > b.open) &&
      a.close < p.close &&
      p.close < c.close &&
      p.open >= a.open &&
      p.open <= a.close &&
      c.open >= p.open &&
      c.open <= p.close
    )
      return result('three-candles', true, 'Three advancing candles', Math.min(a.low, p.low, c.low))
    if (
      [a, p, c].every((b) => b.close < b.open) &&
      a.close > p.close &&
      p.close > c.close &&
      p.open <= a.open &&
      p.open >= a.close &&
      c.open <= p.open &&
      c.open >= p.close
    )
      return result(
        'three-candles',
        false,
        'Three declining candles',
        Math.max(a.high, p.high, c.high)
      )
  }
  if (allow('piercing')) {
    if (
      p.close < p.open &&
      c.close > c.open &&
      c.open <= p.close &&
      c.close > (p.open + p.close) / 2 &&
      c.close < p.open
    )
      return result('piercing', true, 'Piercing pattern', Math.min(c.low, p.low))
    if (
      p.close > p.open &&
      c.close < c.open &&
      c.open >= p.close &&
      c.close < (p.open + p.close) / 2 &&
      c.close > p.open
    )
      return result('piercing', false, 'Dark cloud cover', Math.max(c.high, p.high))
  }
  return null
}
