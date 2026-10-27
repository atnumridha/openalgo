import { expect, it } from 'vitest'
import { mergeCoincidentNames, formatLevelPrice, nearestZones, layoutLevelNames } from './labels'
it('keeps nearby but different levels independently priced at any zoom', () => {
  expect(
    mergeCoincidentNames([
      { title: 'EMA 9', price: 100, color: 'blue', y: 20 },
      { title: '1H Low', price: 100.1, color: 'purple', y: 21 },
    ])
  ).toHaveLength(2)
  expect(
    mergeCoincidentNames([
      { title: '1D Low', price: 100, color: 'white', y: 20 },
      { title: '4H Low', price: 100, color: 'cyan', y: 20 },
    ])
  ).toEqual([{ title: '1D Low / 4H Low', price: 100, color: 'white', y: 20 }])
  expect(formatLevelPrice(0.00001234)).toBe('0.00001234')
})

it('shows only the nearest support and resistance from the engine’s nearest-first zones', () => {
  const zone = (id: number, low: number, above: boolean) => ({
    id,
    time: 1,
    confirmedTime: 2,
    low,
    high: low + 1,
    above,
  })
  const far = zone(1, 60, false)
  const support = zone(2, 95, false)
  const resistance = zone(3, 105, true)
  const zones = [support, far, resistance, zone(4, 140, true)]
  expect(nearestZones(zones)).toEqual([support, resistance])
  expect(nearestZones([support, far])).toEqual([support])
  expect(zones).toHaveLength(4)
})

it('keeps level labels below the signal panel while preserving their exact price anchors', () => {
  const labels = [
    { title: 'Resistance', price: 110, color: 'red', y: 35 },
    { title: '1H High', price: 109, color: 'purple', y: 50 },
    { title: 'Support', price: 95, color: 'green', y: 310 },
  ]
  const placed = layoutLevelNames(labels, 400, 100)
  expect(placed.map((l) => l.y)).toEqual([35, 50, 310])
  expect(placed[0].top).toBeGreaterThanOrEqual(100)
  expect(placed[1].top - placed[0].top).toBeGreaterThanOrEqual(24)
  expect(placed.at(-1)!.top + 22).toBeLessThanOrEqual(400)
})
