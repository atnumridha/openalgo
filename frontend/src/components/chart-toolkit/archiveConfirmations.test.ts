import { expect, it } from 'vitest'
import {
  recognizeZoneConfirmations,
  recognizeCandleConfirmations,
  latestArchiveReading,
} from './archiveConfirmations'
import type { Bar } from './model'
const bar = (time: number, open: number, close: number, high: number, low: number): Bar => ({
  time,
  open,
  close,
  high,
  low,
  volume: 1,
})
const base = [
  bar(60, 110, 109, 111, 108),
  bar(120, 108, 107, 109, 106),
  bar(180, 101, 102, 103, 100),
  bar(240, 105, 106, 107, 104),
  bar(300, 110, 111, 112, 109),
  bar(360, 108, 109, 110, 107),
  bar(420, 104, 103, 105, 102),
  bar(480, 102, 103, 104, 100.2),
  bar(540, 103, 106, 107, 102.5),
]
const hammer = () => [{ side: 'CALL' as const, name: 'Hammer', pattern: 'hammer', extreme: 100.2 }]
it('requires a pre-existing demand zone and a next-candle confirming close', () => {
  expect(recognizeZoneConfirmations(base, hammer)).toContainEqual(
    expect.objectContaining({ side: 'CALL', name: 'Hammer confirmed at demand' })
  )
  expect(recognizeZoneConfirmations(base.slice(0, -1), hammer)).toEqual([])
  const bad = base.map((b) => ({ ...b }))
  bad[5].close = 99
  bad[5].low = 98
  expect(recognizeZoneConfirmations(bad, hammer)).toEqual([])
  const unconfirmed = base.map((b) => ({ ...b }))
  unconfirmed[8].close = 103.5
  expect(recognizeZoneConfirmations(unconfirmed, hammer)).toEqual([])
})
it('uses supply mirror and does not mutate source', () => {
  const mirror = base.map((b) => ({
      ...b,
      open: 300 - b.open,
      close: 300 - b.close,
      high: 300 - b.low,
      low: 300 - b.high,
    })),
    before = JSON.stringify(mirror)
  expect(
    recognizeZoneConfirmations(mirror, () => [
      { side: 'PUT', name: 'Shooting Star', pattern: 'star', extreme: 200 },
    ])
  ).toContainEqual(
    expect.objectContaining({ side: 'PUT', name: 'Shooting Star confirmed at supply' })
  )
  expect(JSON.stringify(mirror)).toBe(before)
})
it('only treats the latest closed candle as fresh and gives WAIT for conflicting signals', () => {
  const bull = {
    time: 540,
    side: 'CALL' as const,
    name: 'Hammer',
    pattern: 'zone-hammer',
    extreme: 100,
    confirmed: true,
  }
  expect(latestArchiveReading([bull], base)).toMatchObject({
    side: 'BULL',
    name: 'Hammer',
    invalid: 100,
  })
  expect(latestArchiveReading([{ ...bull, time: 480 }], base)).toMatchObject({ side: 'WAIT' })
  expect(
    latestArchiveReading([bull, { ...bull, side: 'PUT', name: 'Bear', extreme: 110 }], base)
  ).toMatchObject({ side: 'WAIT', name: 'Mixed signals' })
  expect(latestArchiveReading([{ ...bull, extreme: 108 }], base)).toMatchObject({ side: 'WAIT' })
})
it('does not attach an unrelated earlier zone touch to a single-candle pattern', () => {
  const bars = base.map((b) => ({ ...b }))
  bars[6] = { ...bars[6], low: 100.5 }
  bars[7] = { ...bars[7], open: 106, close: 107, high: 108, low: 105 }
  bars[8] = { ...bars[8], open: 107, close: 110, high: 111, low: 106 }
  expect(recognizeZoneConfirmations(bars, hammer)).toEqual([])
})
it('waits on an unconfirmed shape even if it is on the latest candle', () => {
  expect(
    latestArchiveReading(
      [
        {
          time: 540,
          side: 'CALL',
          name: 'Hammer',
          pattern: 'hammer',
          extreme: 100,
          confirmed: false,
        },
      ],
      base
    )
  ).toMatchObject({ side: 'WAIT' })
})

it('confirms candle direction only on a new close through its preceding range', () => {
  expect(recognizeCandleConfirmations(base, hammer)).toContainEqual(
    expect.objectContaining({ side: 'CALL', confirmed: true, name: 'Hammer confirmed' })
  )
  const no = base.map((b) => ({ ...b }))
  no[8].close = 103.5
  expect(recognizeCandleConfirmations(no, hammer)).toEqual([])
})
