import { describe, expect, it } from 'vitest'
import { deltaGuideCash, readTradeGuidance, type GuidePlan } from './tradeGuidance'

const now = 1793718000
const plan: GuidePlan = { entry: 100, stop: 95, target: 110, side: 'buy', asOf: now - 60, label: 'Chart plan', protection: 'planned' }
const input = { live: true, now, seconds: 60, current: { direction: 'up' as const, time: now - 60, reason: 'EMA 9 is above EMA 15.' }, higher: { direction: 'up' as const, time: now - 300, reason: 'Higher trend is up.' }, plan, quote: { price: 100, time: now }, tick: 0.05 }

describe('advisory trade guidance', () => {
  it('explains agreement without calling it an approved order', () => {
    const result = readTradeGuidance(input)
    expect(result.headline).toBe('Upward bias')
    expect(result.reason).toContain('EMA 9')
    expect(result.warnings).toEqual([])
    expect(result).not.toHaveProperty('entryAllowed')
  })
  it('explains mixed direction without changing order eligibility', () => {
    expect(readTradeGuidance({ ...input, higher: { ...input.higher, direction: 'down' } }).headline).toBe('Mixed direction')
  })
  it('does not present replay or old candles as current guidance', () => {
    expect(readTradeGuidance({ ...input, live: false }).headline).toBe('Historical review')
    expect(readTradeGuidance({ ...input, now: now + 1000 }).headline).toBe('Check live data')
  })
  it('warns that a frozen long plan has crossed its stop, without moving it', () => {
    expect(readTradeGuidance({ ...input, quote: { price: 94, time: now } }).warnings.join(' ')).toContain('SL has been crossed')
    expect(plan.stop).toBe(95)
  })
  it('checks short stops in the opposite price direction', () => {
    expect(readTradeGuidance({ ...input, plan: { ...plan, side: 'sell', stop: 105, target: 90 }, quote: { price: 106, time: now } }).warnings.join(' ')).toContain('SL has been crossed')
  })
  it('does not use a stale quote to claim a target or stop was reached', () => {
    const warnings = readTradeGuidance({ ...input, quote: { price: 200, time: now - 100 } }).warnings.join(' ')
    expect(warnings).toContain('Live quote unavailable')
    expect(warnings).not.toContain('target has been crossed')
  })
  it('handles a profitable trailing stop as positive net at SL', () => {
    const result = deltaGuideCash({ ...plan, stop: 105 }, 4, 0.001, { maker: 0.0002, taker: 0.0005, tax: 0.18, entryPaid: 0.001 })!
    expect(result.atStop).toBeCloseTo(((105 - 100) * 0.004 - 0.001 - 105 * 0.004 * 0.0005 * 1.18) * 85)
    expect(result.atStop).toBeGreaterThan(0)
    expect(result.atTarget).toBeGreaterThan(result.atStop)
  })
  it('values short crypto with contract size and maker-entry / taker-exit fees', () => {
    const p = { ...plan, side: 'sell' as const, stop: 105, target: 90 }
    const result = deltaGuideCash(p, 4, 0.001, { maker: 0.0002, taker: 0.0005, tax: 0.18 })!
    expect(result.atTarget).toBeCloseTo((0.04 - (100 * 0.004 * 0.0002 + 90 * 0.004 * 0.0005) * 1.18) * 85)
    expect(deltaGuideCash(p, 8, 0.001, { maker: 0.0002, taker: 0.0005, tax: 0.18 })!.atTarget).toBeCloseTo(result.atTarget! * 2)
  })
  it('does not fabricate money when quantity, fees or protection are missing', () => {
    expect(deltaGuideCash(plan, 0, 0.001, { maker: 0, taker: 0.0005, tax: 0.18 })).toBeNull()
    expect(deltaGuideCash({ ...plan, stop: null }, 4, 0.001, { maker: 0, taker: 0.0005, tax: 0.18 })).toBeNull()
    expect(deltaGuideCash(plan, 4, 0.001, { maker: NaN, taker: 0.0005, tax: 0.18 })).toBeNull()
  })
})
