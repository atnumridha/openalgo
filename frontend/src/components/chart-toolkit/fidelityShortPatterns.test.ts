import { expect, it } from 'vitest'
import { recognizeFidelityShortPatterns } from './fidelityShortPatterns'
import { cryptoFormationSegments } from './TrendLineLayer'
import { archivePatternEvents } from './archivePatternEngine'
const b = (i: number, open: number, high: number, low: number, close: number) => ({
  time: 1000 + i * 60,
  open,
  high,
  low,
  close,
  volume: 1,
})
const nr = [
  b(0, 110, 115, 105, 110),
  b(1, 110, 114, 106, 110),
  b(2, 110, 113, 107, 110),
  b(3, 110, 111, 109, 110),
  b(4, 110, 114, 109.5, 113),
]
const pipe = [
  ...Array.from({ length: 5 }, (_, i) => b(i, 121 - i * 2, 122 - i * 2, 120 - i * 2, 121 - i * 2)),
  b(5, 112, 113, 100, 101),
  b(6, 101, 114, 100, 113),
  b(7, 113, 116, 112, 115),
]
const mirror = (bs: typeof nr) =>
  bs.map((x) => ({
    ...x,
    open: 300 - x.open,
    close: 300 - x.close,
    high: 300 - x.low,
    low: 300 - x.high,
  }))
it('confirms NR4 and inside-bar breakouts only on a later boundary close', () => {
  expect(recognizeFidelityShortPatterns(nr)).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ pattern: 'nr4-breakout', side: 'CALL', entry: 113, extreme: 109 }),
      expect.objectContaining({ pattern: 'inside-bar-breakout' }),
    ])
  )
  expect(recognizeFidelityShortPatterns(nr.slice(0, -1))).toEqual([])
  const wick = nr.map((x) => ({ ...x }))
  wick.at(-1)!.close = 110
  expect(recognizeFidelityShortPatterns(wick)).toEqual([])
  expect(recognizeFidelityShortPatterns(mirror(nr))).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ pattern: 'nr4-breakout', side: 'PUT', entry: 187, extreme: 191 }),
    ])
  )
})
it('requires a pipe reversal context and later break; mirrors the top', () => {
  expect(recognizeFidelityShortPatterns(pipe)).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        pattern: 'pipe-bottom',
        side: 'CALL',
        entry: 115,
        extreme: 100,
        target: 128,
      }),
    ])
  )
  expect(
    recognizeFidelityShortPatterns(pipe.slice(0, -1)).some((x) => x.pattern === 'pipe-bottom')
  ).toBe(false)
  expect(recognizeFidelityShortPatterns(mirror(pipe))).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        pattern: 'pipe-top',
        side: 'PUT',
        entry: 185,
        extreme: 200,
        target: 172,
      }),
    ])
  )
  const bad = pipe.map((x) => ({ ...x }))
  bad[5].low = 90
  bad[5].close = 91
  expect(recognizeFidelityShortPatterns(bad).some((x) => x.pattern === 'pipe-bottom')).toBe(false)
})
it('does not draw only crypto-catalogue names: a verified triple bottom outline is retained', () => {
  const bs = nr,
    e = {
      time: bs.at(-1)!.time,
      name: 'Triple Bottom',
      pattern: 'triple-bottom',
      side: 'CALL' as const,
      confirmed: true,
      extreme: 100,
      structure: [
        [
          { time: bs[0].time, price: 100 },
          { time: bs.at(-1)!.time, price: 110 },
        ],
      ],
    }
  expect(cryptoFormationSegments([e], bs, bs[0].time, bs.at(-1)!.time)).toEqual([
    expect.objectContaining({ title: 'Triple Bottom', kind: 'pattern' }),
  ])
})

it('routes short-term source patterns through the actual confirmed production collector', () => {
  const events = archivePatternEvents(nr, 'shapes', 60)
  expect(events).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ pattern: 'nr4-breakout', confirmed: true, time: 1240 }),
    ])
  )
  expect(
    archivePatternEvents(nr.slice(0, -1), 'shapes', 60).some((e) => e.pattern === 'nr4-breakout')
  ).toBe(false)
})
it('draws optional pending geometry only when the existing pending option is enabled', () => {
  const e = {
    time: nr.at(-1)!.time,
    name: 'Double Bottom',
    pattern: 'double-bottom',
    side: 'CALL' as const,
    confirmed: false,
    extreme: 100,
    structure: [
      [
        { time: nr[0].time, price: 100 },
        { time: nr.at(-1)!.time, price: 110 },
      ],
    ],
  }
  expect(cryptoFormationSegments([e], nr, nr[0].time, e.time)).toEqual([])
  expect(cryptoFormationSegments([e], nr, nr[0].time, e.time, true)[0]).toMatchObject({
    title: 'Double Bottom · forming',
    color: '#fbbf24',
  })
})
