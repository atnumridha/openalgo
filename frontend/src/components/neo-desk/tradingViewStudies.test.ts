import { describe, expect, it } from 'vitest'
import {
  chartBars,
  reconcileHistory,
  computeStudies,
  formatIST,
  openingRange,
} from './tradingViewStudies'

const bar = (i: number, close: number) => ({
  time: 1791863100 + i * 300,
  open: close,
  high: close + 1,
  low: close - 1,
  close,
  volume: 20,
})
describe('TradingView broker data and studies', () => {
  it('normalizes the broker display offset once, sorts and removes duplicate/invalid observations', () => {
    const a = bar(0, 100),
      b = bar(1, 102)
    const input = [
      { ...b, time: b.time + 19800 },
      { ...a, time: a.time + 19800 },
      { ...b, time: b.time + 19800 },
      { ...a, time: a.time + 19800 + 600, low: 200 },
    ]
    expect(chartBars(input)).toEqual([a, b])
    expect(formatIST(a.time, true)).toContain('09:15')
  })
  it('excludes the breakout candle from Donchian and uses the existing EMA formula', () => {
    const bars = Array.from({ length: 21 }, (_, i) => bar(i, i === 20 ? 500 : 100))
    const result = computeStudies(bars)
    expect(result.upper.at(-1)?.value).toBe(101)
    expect(result.lower.at(-1)?.value).toBe(99)
    expect(result.ema.at(-1)?.value).toBeCloseTo(100 + (2 / 201) * 400)
  })
  it('computes Wilder RSI without future bars and confirms pivots only after completed bars', () => {
    const rising = Array.from({ length: 18 }, (_, i) => bar(i, 100 + i))
    expect(computeStudies(rising).rsi.at(-1)?.value).toBe(100)
    const p = [100, 101, 102, 110, 103, 102, 101, 100].map((v, i) => bar(i, v))
    expect(computeStudies(p.slice(0, 7)).resistance).toBeNull()
    expect(computeStudies(p).resistance).toBe(111)
  })
  it('retains only unfilled intraday FVGs and removes mitigated gaps', () => {
    const bars = Array.from({ length: 22 }, (_, i) => bar(i, 100 + i * 5))
    expect(computeStudies(bars).zones.length).toBe(3)
    const filled = [...bars, { ...bar(22, 100), low: 99, high: 210 }]
    expect(computeStudies(filled).zones).toEqual([])
  })
  it('shows opening range only after the first 15-minute window is complete', () => {
    const bars = Array.from({ length: 4 }, (_, i) => bar(i, 100 + i))
    expect(openingRange(bars.slice(0, 3))).toBeNull()
    expect(openingRange(bars)).toEqual({ high: 103, low: 99 })
  })
})

it('corrects the candle open and missing extremes from history while retaining the latest quote close', () => {
  const original = { time: 1791863100, open: 100, high: 120, low: 90, close: 110, volume: 300 }
  const live = { ...original, open: 109, high: 115, low: 95, close: 115, volume: 0 }
  expect(reconcileHistory([original], live)).toEqual([{ ...original, close: 115 }])
})
