import { describe, expect, it } from 'vitest'
import { deltaMoney, DELTA_INR_PER_USD } from './deltaCurrency'
describe('Delta India display conversion', () => {
  it('uses the documented fixed 85 settlement rate', () => {
    expect(DELTA_INR_PER_USD).toBe(85)
    expect(deltaMoney(10, 'INR')).toBe('₹850.00')
    expect(deltaMoney(-1.08, 'INR')).toBe('-₹91.80')
  })
  it('supports USD, zero and unknown values without changing underlying amounts', () => {
    expect(deltaMoney(10, 'USD')).toBe('$10.00')
    expect(deltaMoney(0, 'INR')).toBe('₹0.00')
    expect(deltaMoney(null, 'INR')).toBe('-')
    expect(deltaMoney(0.001, 'INR', 3)).toBe('₹0.085')
  })
})
