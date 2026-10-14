import { describe, expect, it } from 'vitest'
import { pivotHigh, pivotLow, nulls } from 'openalgo-charts'
import install from '../../../../strategies/templates/indicators/neo_context.js'
const descriptors = []
install({ registerIndicator: (d) => descriptors.push(d), pivotHigh, pivotLow, nulls })
const structure = descriptors.find((d) => d.id === 'neo-structure')
const bar = (i, low, high, close = (low + high) / 2) => ({
  time: 1791863100 + i * 300,
  open: close,
  low,
  high,
  close,
  volume: 100,
})
const empty = (n) => ({ ph: Array(n).fill(null), pl: Array(n).fill(null) })

describe('unobstructed market structure overlays', () => {
  it('bounds unfilled gap zones and keeps their explanations on hover rather than over candles', () => {
    const bars = Array.from({ length: 22 }, (_, i) => bar(i, 100 + i * 5, 101 + i * 5))
    const draws = structure.draws({
      bars,
      values: empty(bars.length),
      settings: { zones: true, levels: false, zoneCount: 3, zoneLabels: false },
    })
    const boxes = draws.filter((d) => d.kind === 'box')
    expect(boxes).toHaveLength(3)
    expect(boxes.every((d) => !d.text && d.tooltip?.includes('Bullish FVG'))).toBe(true)
  })
  it('removes a completely filled bullish gap and never calls it an active zone', () => {
    const bars = [
      bar(0, 99, 100),
      bar(1, 100, 101),
      bar(2, 103, 104),
      bar(3, 105, 106),
      bar(4, 99, 107),
      bar(5, 101, 102),
      bar(6, 101, 102),
      bar(7, 101, 102),
    ]
    const draws = structure.draws({
      bars,
      values: empty(bars.length),
      settings: { zones: true, levels: false, zoneCount: 3, zoneLabels: false },
    })
    expect(draws.some((d) => d.kind === 'box' && d.from.price === 101 && d.to.price === 105)).toBe(
      false
    )
  })
  it('keeps nearest confirmed support and resistance even when numerous gaps exist', () => {
    const bars = Array.from({ length: 20 }, (_, i) => bar(i, 100 + i * 5, 101 + i * 5))
    const values = empty(bars.length)
    values.ph[4] = 210
    values.ph[5] = 230
    values.pl[3] = 190
    values.pl[4] = 170
    const draws = structure.draws({
      bars,
      values,
      settings: { zones: true, levels: true, zoneCount: 3, zoneLabels: false },
    })
    const levels = draws.filter((d) => d.kind === 'line').map((d) => d.from.price)
    expect(levels).toEqual([210, 190])
    expect(draws.filter((d) => d.kind === 'box').length).toBeLessThanOrEqual(3)
  })
  it('lets the user hide zones and levels through native indicator settings', () => {
    const bars = Array.from({ length: 22 }, (_, i) => bar(i, 100 + i * 5, 101 + i * 5))
    const values = empty(bars.length)
    values.pl[4] = 190
    expect(structure.draws({ bars, values, settings: { zones: false, levels: false } })).toEqual([])
  })
})
