import { expect, it } from 'vitest'
import { higherTimeframeLevels } from './higherTimeframeLevels'
import type { Bar } from './model'
const start = Date.UTC(2026, 10, 1, 0) / 1000
const hours: Bar[] = Array.from({ length: 8 }, (_, i) => ({
  time: start + i * 3600,
  open: 100 + i,
  high: 110 + i,
  low: 90 + i,
  close: 105 + i,
  volume: 100,
}))
it('uses the last completed hour and UTC-aligned four-hour block, excluding forming extremes', () => {
  const result = higherTimeframeLevels(hours, start + 6.5 * 3600)
  expect(result.map((l) => [l.title, l.price])).toEqual([
    ['1H HIGH', 115],
    ['1H LOW', 95],
    ['4H HIGH', 113],
    ['4H LOW', 90],
  ])
  expect(result.every((l) => l.end <= start + 6.5 * 3600)).toBe(true)
})
it('changes four-hour levels exactly when a whole new block has closed', () => {
  expect(higherTimeframeLevels(hours, start + 8 * 3600).map((l) => [l.title, l.price])).toEqual([
    ['1H HIGH', 117],
    ['1H LOW', 97],
    ['4H HIGH', 117],
    ['4H LOW', 94],
  ])
})
it('rejects gaps, duplicate hours and invalid OHLC instead of inventing four-hour extremes', () => {
  for (const bars of [
    hours.filter((_, i) => i !== 2),
    [...hours, hours[2]],
    hours.map((b, i) => (i === 2 ? { ...b, high: 1 } : b)),
  ]) {
    expect(higherTimeframeLevels(bars, start + 6.5 * 3600).map((l) => l.title)).toEqual([
      '1H HIGH',
      '1H LOW',
    ])
  }
  expect(higherTimeframeLevels(hours, NaN)).toEqual([])
})
it('is stable for a historical cutoff even when later bars are available', () => {
  const before = JSON.stringify(hours)
  expect(higherTimeframeLevels(hours, start + 6 * 3600)).toEqual(
    higherTimeframeLevels(hours.slice(0, 6), start + 6 * 3600)
  )
  expect(JSON.stringify(hours)).toBe(before)
})
