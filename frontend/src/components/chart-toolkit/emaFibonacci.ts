import type { Bar } from './model'
const valid = (b: Bar) =>
  [b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) &&
  Math.min(b.open, b.high, b.low, b.close) > 0 &&
  b.high >= Math.max(b.open, b.close) &&
  b.low <= Math.min(b.open, b.close)
/** SMA-seeded EMA; malformed or unordered candles restart the seed. */
export function emaPoints(bars: readonly Bar[], period: number): { time: number; value: number }[] {
  if (!Number.isInteger(period) || period < 1) return []
  const result: { time: number; value: number }[] = []
  let seed: number[] = [],
    value: number | null = null,
    previous = -Infinity
  for (const b of bars) {
    if (!valid(b) || b.time <= previous) {
      seed = []
      value = null
      previous = b.time
      continue
    }
    previous = b.time
    if (value === null) {
      seed.push(b.close)
      if (seed.length < period) continue
      value = seed.reduce((a, b) => a + b, 0) / period
    } else value += (2 / (period + 1)) * (b.close - value)
    result.push({ time: b.time, value })
  }
  return result
}
export interface FibonacciLevel {
  title: string
  price: number
  color: string
}
/** Previous completed calendar day; UTC for crypto, local midnight for Indian markets. */
export function fibonacciPivots(days: readonly Bar[], asOf: number, offset = 0): FibonacciLevel[] {
  if (!Number.isFinite(asOf) || asOf <= 0) return []
  const start = Math.floor((asOf + offset) / 86400) * 86400 - offset
  const previous = days
    .filter((b) => b.time < start)
    .sort((a, b) => a.time - b.time)
    .at(-1)
  if (!previous || !valid(previous)) return []
  const p = (previous.high + previous.low + previous.close) / 3,
    range = previous.high - previous.low
  return [
    { title: 'Fib P', price: p, color: '#dca94c' },
    ...[0.382, 0.618, 1].flatMap((ratio, i) => [
      { title: `Fib R${i + 1}`, price: p + range * ratio, color: '#ef5350' },
      { title: `Fib S${i + 1}`, price: p - range * ratio, color: '#26a69a' },
    ]),
  ]
}
