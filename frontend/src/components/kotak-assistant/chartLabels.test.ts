import { describe, expect, it } from 'vitest'
import { layoutChartLabels } from './chartLabels'
describe('Visible chart line labels', () => {
  it('keeps nearby support and resistance labels readable without losing their line anchors', () => {
    const result = layoutChartLabels(
      [
        { title: 'Support', price: 100, color: 'cyan', y: 80 },
        { title: 'Resistance', price: 101, color: 'orange', y: 84 },
      ],
      200
    )
    expect(result).toHaveLength(2)
    expect(result[1].top - result[0].top).toBeGreaterThanOrEqual(24)
    expect(result.map((l) => l.y)).toEqual([80, 84])
  })
  it('does not label levels outside the visible price range or invalid prices', () => {
    expect(
      layoutChartLabels(
        [
          { title: 'SL', price: 0, color: 'red', y: 50 },
          { title: 'Target', price: 200, color: 'green', y: 220 },
        ],
        200
      )
    ).toEqual([])
  })
  it('keeps labels within the bottom edge of the chart', () => {
    const result = layoutChartLabels(
      [
        { title: 'Entry', price: 100, color: 'blue', y: 190 },
        { title: 'SL', price: 90, color: 'red', y: 198 },
      ],
      200
    )
    expect(result[0].top).toBeGreaterThanOrEqual(0)
    expect(result.at(-1)!.top + 22).toBeLessThanOrEqual(200)
  })
})
