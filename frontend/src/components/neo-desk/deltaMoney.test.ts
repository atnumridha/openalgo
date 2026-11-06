import { expect, it } from 'vitest'
import { DELTA_USD_INR, formatDeltaINR } from './deltaMoney'
it('uses the user-fixed85 conversion and converts net after fee deductions', () => {
  expect(DELTA_USD_INR).toBe(85)
  expect(formatDeltaINR(2)).toBe('₹170.00')
  expect(formatDeltaINR(2 - 0.2 - 0.3)).toBe('₹127.50')
  expect(formatDeltaINR(0.0002)).toBe('₹0.017')
})
it('formats losses, zero and unknown values without fabricating zero or negative zero', () => {
  expect(formatDeltaINR(-2.5)).toBe('-₹212.50')
  expect(formatDeltaINR(-0)).toBe('₹0.00')
  expect(formatDeltaINR(-0.0000001)).toBe('₹0.00')
  for (const value of [null, undefined, NaN, Infinity]) expect(formatDeltaINR(value)).toBe('—')
})
