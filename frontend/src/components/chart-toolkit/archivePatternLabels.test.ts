import { expect, it } from 'vitest'
import { deduplicateArchiveMatches, primaryArchiveLabels } from './archivePatternLabels'
import type { TimedArchiveMatch } from './archiveConfirmations'
const raw: TimedArchiveMatch = {
  time: 60,
  side: 'CALL',
  name: 'Bullish Marubozu',
  pattern: 'extended-marubozu',
  extreme: 90,
  confirmed: false,
}
const confirmed = {
  ...raw,
  name: 'Marubozu confirmed',
  pattern: 'confirmed-extended-marubozu',
  confirmed: true,
}
const zone = {
  ...confirmed,
  name: 'Marubozu confirmed at demand',
  pattern: 'zone-extended-marubozu',
}
it('merges repeated sources and stages of the same pattern, keeping the strongest confirmation', () => {
  expect(
    deduplicateArchiveMatches([raw, confirmed, zone, { ...raw, name: 'Bull Marubozu' }])
  ).toEqual([zone])
  expect(deduplicateArchiveMatches([zone, confirmed, raw])).toEqual([zone])
})
it('preserves different candles, opposite directions and genuinely distinct formations', () => {
  const other = { ...confirmed, name: 'Engulfing confirmed', pattern: 'confirmed-guide-engulfing' }
  expect(
    deduplicateArchiveMatches([raw, { ...raw, time: 120 }, { ...raw, side: 'PUT' }, other])
  ).toHaveLength(4)
  expect(
    deduplicateArchiveMatches([
      { ...raw, side: 'NEUTRAL', name: 'Doji' },
      { ...raw, side: 'NEUTRAL', name: 'Dragonfly Doji' },
    ])
  ).toHaveLength(2)
})
it('shows one primary label per candle and direction while retaining all distinct detections', () => {
  const engulf = { ...confirmed, name: 'Engulfing confirmed', pattern: 'confirmed-guide-engulfing' }
  const top = {
    ...confirmed,
    side: 'PUT' as const,
    name: 'Double Top',
    pattern: 'double-top',
    entry: 100,
    target: 80,
    extreme: 110,
  }
  const candidates = [raw, confirmed, zone, engulf, top, { ...raw, time: 120 }]
  expect(primaryArchiveLabels(candidates)).toEqual([zone, top, { ...raw, time: 120 }])
  expect(deduplicateArchiveMatches(candidates)).toHaveLength(4)
})
it('prefers a named structural breakout without discarding its levels', () => {
  const shape = {
    ...confirmed,
    name: 'Double Bottom',
    pattern: 'double-bottom',
    entry: 100,
    target: 120,
    extreme: 90,
  }
  expect(primaryArchiveLabels([zone, shape])).toEqual([shape])
})

it('treats the old Broadening Wedge name and Megaphone as one formation', () => {
  const old = {
    side: 'CALL' as const,
    name: 'Broadening Wedge',
    pattern: 'broadening-wedge',
    extreme: 90,
    confirmed: true,
  }
  expect(
    deduplicateArchiveMatches([
      old,
      {
        ...old,
        name: 'Megaphone',
        structure: [
          [
            { time: 1, price: 100 },
            { time: 2, price: 101 },
          ],
        ],
        entry: 105,
        target: 115,
      },
    ])
  ).toHaveLength(1)
})
