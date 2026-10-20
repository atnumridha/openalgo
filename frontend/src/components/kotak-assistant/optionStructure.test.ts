import { describe, expect, it } from 'vitest'
import { optionStructure } from './optionStructure'
const base = 1800000000
const bars = [105, 108, 120, 110, 109, 112, 115].map((high, i) => ({
  time: base + 19800 + i * 60,
  open: 100,
  high,
  low: [99, 98, 90, 95, 96, 97, 98][i],
  close: 100,
  volume: 100,
}))
describe('Selected option support and resistance', () => {
  it('finds nearest confirmed option premium pivots, independent of index prices', () => {
    expect(optionStructure(bars, 60, base + 7 * 60, 100)).toEqual({ support: 90, resistance: 120 })
  })
  it('requires two completed candles after a pivot', () => {
    expect(optionStructure(bars.slice(0, 4), 60, base + 4 * 60, 100)).toEqual({
      support: null,
      resistance: null,
    })
    expect(optionStructure(bars.slice(0, 5), 60, base + 5 * 60, 100)).toEqual({
      support: 90,
      resistance: 120,
    })
  })
  it('excludes the forming candle and never invents a missing level', () => {
    const forming = {
      time: base + 19800 + 7 * 60,
      open: 100,
      high: 200,
      low: 10,
      close: 110,
      volume: 10,
    }
    expect(optionStructure([...bars, forming], 60, base + 7 * 60 + 20, 100)).toEqual({
      support: 90,
      resistance: 120,
    })
    expect(optionStructure(bars, 60, base + 7 * 60, 130)).toEqual({ support: 90, resistance: null })
  })
})
