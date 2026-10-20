import { describe, it, expect } from 'vitest'
import { chartIndicators } from './chartIndicators'

function bars(step: number) {
  return Array.from({ length: 40 }, (_, i) => ({
    time: i * 60,
    open: 100 + i * step,
    high: 101 + i * step,
    low: 99 + i * step,
    close: 100 + i * step,
    volume: 10,
  }))
}
describe('Terminal RSI display', () => {
  it('waits for 14 price changes before showing RSI', () => {
    const values = chartIndicators(bars(1))
    expect(values[13].rsi14).toBeUndefined()
    expect(values[14].rsi14).toBe(100)
  })
  it('shows neutral RSI for flat prices and zero for uninterrupted declines', () => {
    expect(chartIndicators(bars(0)).at(-1)?.rsi14).toBe(50)
    expect(chartIndicators(bars(-1)).at(-1)?.rsi14).toBe(0)
  })
})
