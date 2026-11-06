import { describe, expect, it } from 'vitest'
import {
  calculateEntryPlan,
  confirmedTrend,
  findAutomaticSetup,
  advanceFrozenPlan,
  type PlanBar,
} from './chartTradePlan'
const start = Date.UTC(2026, 9, 30, 4) / 1000
const bars = (n = 35): PlanBar[] =>
  Array.from({ length: n }, (_, i) => ({
    time: start + i * 300,
    open: 100,
    high: 102,
    low: 98,
    close: 100,
  }))
const shaped = () => {
  const result = bars()
  result[25] = { ...result[25], open: 98, high: 100, low: 94, close: 98 }
  result[29] = { ...result[29], open: 104, high: 108, low: 102, close: 104 }
  return result
}
describe('external entry and exact 2R chart plans', () => {
  it('keeps the user entry authoritative and uses structure plus Wilder ATR for a long premium', () => {
    const result = calculateEntryPlan(shaped(), 100, 0.05, 'long')
    expect(result.plan).not.toBeNull()
    const p = result.plan!
    expect(p.entry).toBe(100)
    expect(p.stop).toBeLessThan(94)
    expect(p.entry - p.stop).toBeGreaterThanOrEqual(1.5 * p.atr - 1e-8)
    expect(p.target - p.entry).toBeCloseTo(2 * (p.entry - p.stop), 8)
    expect(p.stop / 0.05).toBeCloseTo(Math.round(p.stop / 0.05), 8)
  })
  it('reverses SL and target correctly for BTC shorts without changing the external entry', () => {
    const p = calculateEntryPlan(shaped(), 100, 0.5, 'short').plan!
    expect(p.entry).toBe(100)
    expect(p.stop).toBeGreaterThan(108)
    expect(p.target).toBeLessThan(p.entry)
    expect(p.entry - p.target).toBeCloseTo(2 * (p.stop - p.entry), 8)
  })
  it('does not invent a stop from the latest candle when structure or ATR is missing', () => {
    expect(calculateEntryPlan(bars(), 100, 0.05, 'long').plan).toBeNull()
    expect(calculateEntryPlan(shaped().slice(0, 10), 100, 0.05, 'long').plan).toBeNull()
  })
  it('rejects off-tick average fills and invalid values instead of rounding away exact 2R', () => {
    for (const entry of [100.025, 0, -1, NaN, Infinity])
      expect(calculateEntryPlan(shaped(), entry, 0.05, 'long').plan).toBeNull()
    expect(calculateEntryPlan(shaped(), 100, 0, 'long').plan).toBeNull()
  })
  it('cannot use a pivot until the two candles to its right have closed', () => {
    const source = bars(28)
    source[25] = { ...source[25], low: 94 }
    expect(calculateEntryPlan(source.slice(0, 27), 100, 0.05, 'long').plan).toBeNull()
    expect(calculateEntryPlan(source, 100, 0.05, 'long').plan).not.toBeNull()
  })
  it('treats CE and PE as long premium geometry and never changes an entry to fit a distant stop', () => {
    for (const entry of [99, 100, 105]) {
      const p = calculateEntryPlan(shaped(), entry, 0.05, 'long').plan!
      expect(p.entry).toBe(entry)
      expect(p.stop).toBeLessThan(p.entry)
      expect(p.target).toBeGreaterThan(p.entry)
    }
  })
})
describe('confirmed automatic entry setup', () => {
  it('does not create an automatic entry without a known directional trend', () => {
    expect(findAutomaticSetup(shaped(), [], 0.05, 'both').plan).toBeNull()
    expect(confirmedTrend(bars(), start + 999999, 900)).toBe('none')
  })
})
const upTrend = () => {
  const result = Array.from({ length: 25 }, (_, i) => ({
    time: start - 30000 + i * 900,
    open: 100,
    high: 102,
    low: 98,
    close: 100,
  }))
  result[3].high = 110
  result[9].high = 115
  result[6].low = 90
  result[12].low = 95
  return result
}
const retest = () => {
  const result = bars(26)
  result[20].high = 104
  result[24] = { time: start + 24 * 300, open: 102, high: 107, low: 101, close: 106 }
  result[25] = { time: start + 25 * 300, open: 105, high: 106, low: 103.5, close: 105.5 }
  return result
}
it('arms only after the retest close, preserves exact 2R and requires the correct option bias', () => {
  expect(confirmedTrend(upTrend(), start, 900)).toBe('long')
  const before = findAutomaticSetup(retest().slice(0, -1), upTrend(), 0.05, 'CE')
  expect(before.plan).toBeNull()
  const result = findAutomaticSetup(retest(), upTrend(), 0.05, 'CE')
  expect(result.status).toBe('Armed')
  expect(result.plan?.entry).toBe(106.05)
  expect(result.plan!.target - result.plan!.entry).toBeCloseTo(2 * result.plan!.risk, 8)
  expect(findAutomaticSetup(retest(), upTrend(), 0.05, 'PE').plan).toBeNull()
})
it('expires an untouched automatic entry after two actual source bars', () => {
  const source = [
    ...retest(),
    { time: start + 26 * 300, open: 105, high: 106, low: 104, close: 105 },
    { time: start + 27 * 300, open: 105, high: 106, low: 104, close: 105 },
  ]
  expect(findAutomaticSetup(source, upTrend(), 0.05, 'CE').status).toBe('Expired')
})
it('marks ambiguous intrabar entry/invalidation without claiming a fill or a winner', () => {
  const source = [
    ...retest(),
    { time: start + 26 * 300, open: 105, high: 107, low: 100, close: 104 },
  ]
  expect(findAutomaticSetup(source, upTrend(), 0.05, 'CE').status).toBe('Ambiguous candle')
})
it('does not seed an ATR from a short fragment after missing intraday candles', () => {
  const source = shaped().map((b, i) => (i >= 30 ? { ...b, time: b.time + 600 } : b))
  expect(calculateEntryPlan(source, 100, 0.05, 'long').plan).toBeNull()
})

it.each([
  1800, 3600, 86400,
])('preserves ATR across normal Indian trading closures for %s second bars', (seconds) => {
  const source: PlanBar[] = []
  for (let d = 0; d < 75; d++) {
    const date = new Date(Date.UTC(2026, 6, 1 + d))
    if ([0, 6].includes(date.getUTCDay())) continue
    const day = date.getTime() / 1000 + 13500
    const offsets =
      seconds === 86400
        ? [0]
        : Array.from({ length: Math.ceil(22500 / seconds) }, (_, i) => i * seconds)
    for (const offset of offsets)
      source.push({ time: day + offset, open: 100, high: 102, low: 98, close: 100 })
  }
  source[source.length - 4].low = 94
  const result = calculateEntryPlan(source, 100, 0.05, 'long', seconds, true)
  expect(result.plan).not.toBeNull()
  expect(result.plan?.atr).toBeGreaterThan(0)
})
it('advances a frozen automatic plan from new bars without recalculating its stop from corrected history', () => {
  const initial = findAutomaticSetup(retest(), upTrend(), 0.05, 'CE').plan!
  const after = [
    ...retest(),
    { time: start + 26 * 300, open: 106, high: 107, low: 104, close: 106.5 },
  ]
  expect(advanceFrozenPlan(initial, after, 0.05, 300).status).toBe('Entry touched')
  const revised = after.map((b, i) => (i === 18 ? { ...b, low: 90 } : b))
  expect(advanceFrozenPlan(initial, revised, 0.05, 300).plan).toEqual(initial)
})
