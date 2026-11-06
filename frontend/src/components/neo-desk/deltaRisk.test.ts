import { expect, it } from 'vitest'
import {
  buildDeltaProtection,
  deltaRiskAtr,
  deltaEntryPauseReason,
  deltaTrailingStop,
  type DeltaRiskContext,
} from './deltaRisk'
const now = 2000
const context = (direction: DeltaRiskContext['direction'] = 'up'): DeltaRiskContext => ({
  symbol: 'BTCUSD',
  intervalSeconds: 60,
  sourceTime: 1940,
  observedAt: 2000,
  direction,
  bars: Array.from({ length: 15 }, (_, i) => ({
    time: 1100 + i * 60,
    open: 100,
    high: 102,
    low: 98,
    close: 100,
    volume: 1,
  })),
  support: 96,
  resistance: null,
})
it('uses confirmed structure/ATR and tick-rounded 2R target for an aligned long', () => {
  const plan = buildDeltaProtection(context(), 'buy', 100, 0.5, now)
  expect(plan).toMatchObject({ stop: 95, target: 110, source_time: 1940, interval_seconds: 60 })
})
it('mirrors the rule for a short and respects nearby support', () => {
  expect(
    buildDeltaProtection(
      { ...context('down'), support: 80, resistance: 104 },
      'sell',
      100,
      0.5,
      now
    )
  ).toMatchObject({ stop: 105, target: 90 })
})
it('waits for a clear aligned trend and sufficient room to target', () => {
  for (const direction of ['down', 'sideways', 'unavailable'] as const)
    expect(buildDeltaProtection(context(direction), 'buy', 100, 0.5, now)).toBeNull()
  expect(
    buildDeltaProtection({ ...context(), entryAligned: false }, 'buy', 100, 0.5, now)
  ).toBeNull()
  expect(buildDeltaProtection({ ...context(), resistance: 104 }, 'buy', 100, 0.5, now)).toMatchObject({stop: 95, target: 110})
})
it('rejects stale, forming, gapped, malformed and short candle evidence', () => {
  const c = context()
  expect(deltaRiskAtr(c, 2300)).toBeNull()
  expect(deltaRiskAtr({ ...c, observedAt: 1999 }, now)).toBeNull()
  expect(deltaRiskAtr({ ...c, bars: c.bars.slice(1) }, now)).toBeNull()
  expect(
    deltaRiskAtr(
      { ...c, bars: c.bars.map((b, i) => (i === 4 ? { ...b, time: b.time + 1 } : b)) },
      now
    )
  ).toBeNull()
  expect(
    deltaRiskAtr({ ...c, bars: c.bars.map((b, i) => (i === 4 ? { ...b, low: 103 } : b)) }, now)
  ).toBeNull()
})
it('moves to fee-aware breakeven before 1R, trails later, and never widens', () => {
  expect(deltaTrailingStop(context(), 'buy', 100, 95, 95, 105, 0.5, 0.25, now)).toBe(101)
  const trailing = deltaTrailingStop(context(), 'buy', 100, 95, 101, 110, 0.5, 0.25, now)
  expect(trailing).toBe(106)
  expect(deltaTrailingStop(context(), 'buy', 100, 95, 107, 110, 0.5, 0.25, now)).toBeNull()
  expect(deltaTrailingStop(context(), 'buy', 100, 95, 95, 104, 0.5, 0.25, now)).toBe(101)
  expect(deltaTrailingStop(context(), 'buy', 100, 95, 95, 102, 0.5, 0.25, now)).toBeNull()
  expect(deltaTrailingStop(context(), 'buy', 100, 95, 95, 110, 0.5, null, now)).toBeNull()
})
it('mirrors fee-aware tightening for shorts and refuses counter-trend trailing', () => {
  const c = { ...context('down'), support: null, resistance: 104 }
  expect(deltaTrailingStop(c, 'sell', 100, 105, 105, 95, 0.5, 0.25, now)).toBe(99)
  expect(deltaTrailingStop(c, 'sell', 100, 105, 99, 90, 0.5, 0.25, now)).toBe(94)
  expect(deltaTrailingStop(context(), 'sell', 100, 105, 105, 95, 0.5, 0.25, now)).toBeNull()
})

it('blocks chasing an unclosed price jump and mirrors the rule for shorts', () => {
  expect(buildDeltaProtection(context(), 'buy', 103, 0.5, now)).toBeNull()
  expect(
    buildDeltaProtection({ ...context('down'), support: null }, 'sell', 97, 0.5, now)
  ).toBeNull()
  expect(buildDeltaProtection(context(), 'buy', 95, 0.5, now)).toBeNull()
})
it('waits after a large confirmed impulse and rejects an unconfirmed level crossing', () => {
  const c = context(),
    bars = c.bars.map((bar, i) =>
      i === 14 ? { ...bar, open: 98, close: 112, high: 113, low: 98 } : bar
    )
  expect(buildDeltaProtection({ ...c, bars, support: 96 }, 'buy', 112, 0.5, now)).toBeNull()
  expect(buildDeltaProtection({ ...context(), resistance: 101 }, 'buy', 101.5, 0.5, now)).toBeNull()
  expect(
    buildDeltaProtection(
      { ...context('down'), support: 99, resistance: 104 },
      'sell',
      98.5,
      0.5,
      now
    )
  ).toBeNull()
})

it('does not withhold protection for an existing position just because a new entry would be late or counter-trend', () => {
  const c = { ...context('down'), entryAligned: false, resistance: 108 }
  expect(buildDeltaProtection(c, 'buy', 105, 0.5, now)).toBeNull()
  expect(buildDeltaProtection(c, 'buy', 105, 0.5, now, 'position')).toMatchObject({ target: 125 })
})

it('protects fee-covered profit during sideways conditions, with volatility buffer and no widening', () => {
  expect(deltaTrailingStop(context('sideways'), 'buy', 100, 90, 90, 103, 0.5, 0.25, now)).toBe(101)
  expect(
    deltaTrailingStop(context('sideways'), 'buy', 100, 90, 102, 103, 0.5, 0.25, now)
  ).toBeNull()
  expect(deltaTrailingStop(context('sideways'), 'sell', 100, 110, 110, 97, 0.5, 0.25, now)).toBe(99)
  expect(
    deltaTrailingStop(context('unavailable'), 'buy', 100, 90, 90, 103, 0.5, 0.25, now)
  ).toBeNull()
  expect(deltaTrailingStop(context('sideways'), 'buy', 100, 90, 90, 103, 0.5, 2, now)).toBeNull()
})

it('explains unconfirmed pressure while preserving the entry block', () => {
  const c = {
    ...context('sideways'),
    entryAligned: false,
    trendReason: 'Price is falling, but a downtrend is not confirmed.',
  }
  expect(deltaEntryPauseReason(c, 'sell', 100, now)).toBe(c.trendReason)
  expect(buildDeltaProtection(c, 'sell', 100, 0.5, now)).toBeNull()
  expect(
    deltaEntryPauseReason({ ...context('down'), entryAligned: false }, 'sell', 100, now)
  ).toMatch(/timeframes/)
  expect(deltaEntryPauseReason(context('up'), 'sell', 100, now)).toMatch(/Trend is up/)
})

it('does not clip 2R targets at nearby support/resistance while keeping freshness checks', async () => {
  const { deltaProtectionPauseReason } = await import('./deltaRisk')
  expect(deltaProtectionPauseReason({ ...context(), resistance: 104 }, 'buy', 100, .5, now)).toBeNull()
  expect(deltaProtectionPauseReason({ ...context('down'), support: 96, resistance: 104 }, 'sell', 100, .5, now)).toBeNull()
  expect(deltaProtectionPauseReason(null, 'buy', 100, .5, now)).toMatch(/closed-candle/i)
  expect(deltaProtectionPauseReason(context(), 'buy', 100, .5, 2300)).toMatch(/stale|fresh/i)
})

it('manual entries ignore trend approval and chase filters but keep fresh ATR-based SL and a 2R target', () => {
  const c = { ...context('sideways'), entryAligned: false, resistance: 101 }
  expect(buildDeltaProtection(c, 'buy', 110, 0.5, now, 'manual')).toMatchObject({
    stop: 98,
    target: 134,
  })
  expect(buildDeltaProtection({ ...c, bars: [] }, 'buy', 110, 0.5, now, 'manual')).toBeNull()
})

it('reduces risk before fees are covered without claiming breakeven', async () => {
  const { deltaRiskReductionStop } = await import('./deltaRisk')
  expect(deltaRiskReductionStop(context(), 'buy', 100, 94, 94, 103, .5, now)).toBe(97)
  expect(deltaRiskReductionStop(context(), 'buy', 100, 94, 98, 103, .5, now)).toBeNull()
  expect(deltaRiskReductionStop(context(), 'buy', 100, 94, 94, 101, .5, now)).toBeNull()
  expect(deltaRiskReductionStop(context('down'), 'sell', 100, 106, 106, 97, .5, now)).toBe(103)
  expect(deltaRiskReductionStop(context(), 'buy', 100, 94, 94, 103, .5, 3000)).toBeNull()
})

it('smart trailing locks ten net and allows only five giveback above thirty', () => {
  // 1 USD per coin corresponds to INR10 for this synthetic position.
  const c = context()
  expect(deltaTrailingStop(c, 'buy', 100, 94, 94, 102, .1, 1, now, false, 1)).toBeNull()
  expect(deltaTrailingStop(c, 'buy', 100, 94, 94, 103.5, .1, 1, now, false, 1)).toBe(102.5)
  expect(deltaTrailingStop(c, 'buy', 100, 94, 102.5, 105, .1, 1, now, false, 1)).toBe(104.5)
  expect(deltaTrailingStop(c, 'buy', 100, 94, 104.5, 104, .1, 1, now, false, 1)).toBeNull()
  expect(deltaTrailingStop(context('down'), 'sell', 100, 106, 106, 95, .1, 1, now, false, 1)).toBe(95.5)
})

it('keeps exactly 2R despite nearby support or resistance for new orders', () => {
  for (const [side, c] of [['buy', { ...context(), resistance: 101 }], ['sell', { ...context('down'), support: 99, resistance: 104 }]] as const) {
    const plan = buildDeltaProtection(c, side, 100, .5, now)!
    expect(plan).not.toBeNull()
    expect(Math.abs(plan.target - 100)).toBe(2 * Math.abs(plan.stop - 100))
  }
})

it.each([.01, .1])('retains exactly two risk units on decimal tick %s', (tick) => {
  const entry = tick * 100
  const c = context()
  const bars = c.bars.map(b => ({...b, open:b.open*tick, high:b.high*tick, low:b.low*tick, close:b.close*tick}))
  for (const side of ['buy','sell'] as const) {
    const plan=buildDeltaProtection({...c,bars,direction:side==='buy'?'up':'down',support:entry-tick*6,resistance:entry+tick*6},side,entry,tick,now)!
    expect(plan).not.toBeNull()
    expect(Math.abs(plan.target-entry)).toBeCloseTo(2*Math.abs(entry-plan.stop),10)
  }
})
