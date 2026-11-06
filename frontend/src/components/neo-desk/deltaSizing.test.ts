import { expect, it } from 'vitest'
import { calculateDeltaContracts } from './deltaSizing'
const sizing = {
  available_balance: 100,
  currency: 'USD',
  maker_fee_rate: 0.0002,
  fee_tax_rate: 0.18,
  version: 's1',
}
it.each([
  0.1, 0.25, 0.5, 0.75, 1,
] as const)('sizes fraction %s with fees, GST and a 1% reserve', (fraction) => {
  expect(calculateDeltaContracts(sizing, fraction, 70000.5, 0.001, 5)).toBe(
    Math.floor((fraction * 100 * 0.99) / (70000.5 * 0.001 * (1 / 5 + 0.0002 * 1.18)))
  )
})
it('returns zero rather than one contract when the balance is insufficient', () => {
  expect(calculateDeltaContracts({ ...sizing, available_balance: 0.01 }, 1, 70000, 0.001, 5)).toBe(
    0
  )
})
it.each([
  { ...sizing, currency: 'INR' },
  { ...sizing, available_balance: NaN },
  { ...sizing, maker_fee_rate: -1 },
  { ...sizing, version: '' },
  null,
])('rejects unavailable or invalid sizing %j', (source) => {
  expect(calculateDeltaContracts(source, 0.25, 70000, 0.001, 5)).toBeNull()
})

it('caps planned scalp loss at twenty INR using standard fees even with a waiver', async () => {
  const { scalpRiskLimitedContracts } = await import('./deltaSizing')
  const sizing = {currency: 'USD' as const, version:'v', available_balance:100, maker_fee_rate:.0002, taker_fee_rate:.0005, fee_tax_rate:.18}
  const n = scalpRiskLimitedContracts(4, 77622.5, 77730, .001, sizing)!
  expect(n).toBe(1)
  expect(scalpRiskLimitedContracts(4, 77622.5, 78000, .001, sizing)).toBe(0)
})
