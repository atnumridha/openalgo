import { expect, it } from 'vitest'
import { emaPoints, fibonacciPivots } from './emaFibonacci'
const bar = (time: number, close: number) => ({
  time,
  open: close,
  high: close + 2,
  low: close - 2,
  close,
  volume: 1,
})
it('seeds EMA with the period mean, then applies the exponential weight', () => {
  const values = Array.from({ length: 16 }, (_, i) => bar(i * 60, 100 + i))
  expect(emaPoints(values, 9)[0]).toEqual({ time: 480, value: 104 })
  expect(emaPoints(values, 9)[1].value).toBe(105)
  expect(emaPoints(values, 15)[0]).toEqual({ time: 840, value: 107 })
  expect(emaPoints(values.slice(0, 8), 9)).toEqual([])
})
it('resets EMA evidence on invalid or unordered prices', () => {
  const values = Array.from({ length: 20 }, (_, i) => bar(i * 60, 100 + i))
  expect(emaPoints([...values, bar(1, 100)], 9)).toEqual(emaPoints(values, 9))
  expect(emaPoints([...values, { ...bar(1200, 100), close: NaN }, bar(1260, 100)], 9)).toEqual(
    emaPoints(values, 9)
  )
})
it('uses only a completed daily candle and standard Fibonacci pivot distances', () => {
  const day = 86400
  const previous = { ...bar(day, 110), open: 100, high: 120, low: 90 }
  const levels = fibonacciPivots([previous, { ...bar(day * 2, 1000), high: 2000 }], day * 2 + 3600)
  const p = (120 + 90 + 110) / 3
  expect(levels.find((l) => l.title === 'Fib P')?.price).toBeCloseTo(p)
  expect(levels.find((l) => l.title === 'Fib R1')?.price).toBeCloseTo(p + 30 * 0.382)
  expect(levels.find((l) => l.title === 'Fib S2')?.price).toBeCloseTo(p - 30 * 0.618)
  expect(levels.find((l) => l.title === 'Fib R3')?.price).toBeCloseTo(p + 30)
  expect(levels).toHaveLength(7)
  expect(fibonacciPivots([bar(day * 2, 100)], day * 2 + 3600)).toEqual([])
})
it('does not fall back from a corrupt latest completed daily candle', () => {
  expect(fibonacciPivots([bar(86400, 100), { ...bar(172800, 100), high: 1 }], 259200)).toEqual([])
})
