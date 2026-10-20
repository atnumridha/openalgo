import { describe, expect, it } from 'vitest'
import { chartWindow, recentTickEpoch } from './chartViewport'

describe('Trading chart viewport', () => {
  it('preserves the exact user view while browsing older candles', () => {
    expect(chartWindow(200, 400, { from: 20, to: 50 }, false)).toEqual({ from: 20, to: 50 })
  })
  it('follows new bars without changing the chosen zoom width', () => {
    expect(chartWindow(200, 400, { from: 150, to: 183 }, true)).toEqual({ from: 169, to: 202 })
  })
  it('starts with readable candle spacing for the actual chart width', () => {
    const narrow = chartWindow(200, 400, null, true)
    expect(narrow.to - narrow.from).toBeLessThan(45)
    expect(narrow.to).toBe(202)
  })
  it('never fabricates current candles from missing or stale exchange timestamps', () => {
    expect(recentTickEpoch(undefined, 1800000000)).toBeNull()
    expect(recentTickEpoch('bad', 1800000000)).toBeNull()
    expect(recentTickEpoch('2026-01-01T09:00:00Z', 1800000000)).toBeNull()
    expect(recentTickEpoch(1800000000000, 1800000001)).toBe(1800000000)
  })
})
