import { describe, expect, it } from 'vitest'
import type { Bar } from './model'
import { recognizeArchiveCandlesB } from './archiveCandlesB'
const scan = (history: Bar[]) =>
  recognizeArchiveCandlesB(history.map((x, time) => ({ ...x, time })))
const b = (o: number, c: number, h = Math.max(o, c) + 0.2, l = Math.min(o, c) - 0.2): Bar => ({
  time: 0,
  open: o,
  close: c,
  high: h,
  low: l,
  volume: 100,
})
const flip = (x: Bar): Bar => ({
  ...x,
  open: 100 - x.open,
  close: 100 - x.close,
  high: 100 - x.low,
  low: 100 - x.high,
})
const context = (up: boolean) => [
  b(20, up ? 21 : 19),
  b(20, up ? 23 : 17),
  b(20, up ? 25 : 15),
  b(20, up ? 27 : 13),
]
type Case = [string, boolean, Bar[], boolean?]
const cases: Case[] = [
  ['three-methods', true, [b(30, 40), b(39, 37), b(37, 35), b(35, 33), b(34, 42)]],
  ['two-gapping-lines', false, [b(10, 8), b(8, 6)]],
  ['gapping-doji', true, [b(30, 34), b(37, 37.02, 38, 36)]],
  ['collapsing-doji-star', true, [b(30, 36), b(26, 26.02, 27, 25), b(23, 20)], false],
  ['shooting-star-two-line', true, [b(30, 36), b(37, 37.5, 40, 36.8)], false],
  ['mat-hold', true, [b(30, 40), b(42, 41), b(41, 39), b(39, 38), b(40, 44)]],
  ['breakaway', false, [b(40, 34), b(32, 30), b(30, 29), b(29, 28), b(28, 33)]],
  ['advance-block', true, [b(30, 36), b(35, 39, 41), b(38, 40, 44)], false],
  ['stalled', true, [b(30, 36), b(35, 41), b(41, 42, 42.2, 40.8)], false],
  [
    'concealing-baby-swallow',
    false,
    [b(40, 36, 40, 36), b(35, 31, 35, 31), b(29, 28, 32, 27), b(33, 26, 33, 26)],
  ],
  ['gap-three-methods', true, [b(30, 34), b(36, 40), b(39, 33)]],
  ['tasuki-gap', true, [b(30, 34), b(36, 40), b(39, 35)]],
  ['upside-gap-two-crows', true, [b(30, 36), b(40, 39), b(41, 38)], false],
  ['two-crows', true, [b(30, 36), b(40, 39), b(39.5, 34)], false],
  ['side-by-side-white-up', true, [b(30, 34), b(36, 40), b(36.05, 40.05)], false],
  ['side-by-side-white-down', false, [b(40, 36), b(32, 34), b(32.05, 34.05)], false],
  ['three-stars', false, [b(40, 34, 40.2, 29.5), b(35, 32, 35.2, 31), b(33, 32, 33.05, 31.95)]],
  ['unique-three-river', false, [b(40, 34), b(38, 35, 38.2, 30), b(32, 33, 33.2, 31.8)]],
  ['stick-sandwich', false, [b(40, 34), b(35, 38, 38.2, 34.5), b(39, 34.02)]],
  ['identical-three', false, [b(30, 34), b(34.01, 38), b(38.01, 42)]],
  ['tristar', false, [b(35, 35.05, 36, 34), b(31, 31.05, 32, 30), b(35, 35.05, 36, 34)]],
  ['ladder', false, [b(40, 36), b(36, 32), b(32, 28), b(28, 27, 30, 26.8), b(31, 36)]],
  ['last-engulfing', false, [b(35, 37), b(38, 34)]],
  ['stomach', false, [b(40, 34), b(38, 39)]],
]
const bullish = (id: string, trendUp: boolean) =>
  [
    'gapping-doji',
    'three-methods',
    'mat-hold',
    'gap-three-methods',
    'tasuki-gap',
    'side-by-side-white-up',
  ].includes(id) ||
  (!trendUp && !id.startsWith('side-by-side') && id !== 'two-gapping-lines')
describe('archive complex candles', () => {
  for (const [id, trendUp, shape, mirror = true] of cases) {
    it(`${id} has a causal contextual positive and rejects insufficient context`, () => {
      const history = [...context(trendUp), ...shape].map((x, i) => ({ ...x, time: i }))
      const side = bullish(id, trendUp) ? 'CALL' : 'PUT'
      const match = scan(history).find((x) => x.pattern === `archive-${id}`)
      expect(match?.side).toBe(side)
      expect(match?.extreme).toBe(
        side === 'CALL'
          ? Math.min(...shape.map((x) => x.low))
          : Math.max(...shape.map((x) => x.high))
      )
      const prior = shape.at(-2)!
      const broken = [
        ...context(trendUp),
        ...shape.slice(0, -1),
        { ...prior, open: prior.close, close: prior.close },
      ]
      expect(scan(broken).some((x) => x.pattern === `archive-${id}`)).toBe(false)
      expect(scan(shape).some((x) => x.pattern === `archive-${id}`)).toBe(false)
      expect(
        scan([...context(!trendUp), ...shape]).some((x) => x.pattern === `archive-${id}`)
      ).toBe(false)
      if (mirror)
        expect(scan(history.map(flip)).find((x) => x.pattern === `archive-${id}`)?.side).toBe(
          side === 'CALL' ? 'PUT' : 'CALL'
        )
      expect(history.at(-1)).toEqual({ ...shape.at(-1), time: history.length - 1 })
    })
  }
  for (const count of [8, 10, 12, 13])
    it(`${count} new price lines require opposite confirmation`, () => {
      const run = Array.from({ length: count }, (_, i) => b(40 - i * 2, 39 - i * 2))
      const history = [...context(false), ...run, b(40 - count * 2, 43 - count * 2)]
      expect(scan(history).find((x) => x.pattern === `archive-new-price-${count}`)?.side).toBe(
        'CALL'
      )
      expect(
        scan(history.map(flip)).find((x) => x.pattern === `archive-new-price-${count}`)?.side
      ).toBe('PUT')
      expect(
        scan(history.slice(0, -1)).some((x) => x.pattern === `archive-new-price-${count}`)
      ).toBe(false)
    })
  it('stomach uses the first body midpoint, including equality and gaps above it', () => {
    for (const shape of [
      [b(40, 34), b(37, 38)],
      [b(40, 34), b(41, 42)],
    ]) {
      expect(
        scan([...context(false), ...shape]).find((x) => x.pattern === 'archive-stomach')?.side
      ).toBe('CALL')
    }
  })
  it('rejects invalid timestamps, duplicate or reversed time, and nonpositive prices', () => {
    const valid = [...context(false), b(40, 34), b(38, 39)].map((x, time) => ({ ...x, time }))
    expect(recognizeArchiveCandlesB(valid).some((x) => x.pattern === 'archive-stomach')).toBe(true)
    for (const invalid of [
      valid.map((x) => ({ ...x, time: NaN })),
      valid.map((x) => ({ ...x, time: 0 })),
      [...valid].reverse(),
      valid.map((x) => ({ ...x, open: -x.open, close: -x.close, high: -x.low, low: -x.high })),
      valid.map((x) => ({ ...x, low: 0 })),
    ])
      expect(recognizeArchiveCandlesB(invalid)).toEqual([])
  })
  it('three stars requires second open above first close and a second lower shadow', () => {
    for (const shape of [
      [b(40, 34, 40.2, 29.5), b(33, 32, 33.2, 31), b(32.5, 32, 32.52, 31.98)],
      [b(40, 34, 40.2, 29.5), b(35, 32, 35.2, 32), b(33, 32.5, 33.02, 32.48)],
    ])
      expect(
        scan([...context(false), ...shape]).some((x) => x.pattern === 'archive-three-stars')
      ).toBe(false)
  })
  it('rejects empty and invalid OHLC', () => {
    expect(scan([])).toEqual([])
    expect(scan([...context(true), b(30, 40, 35)])).toEqual([])
  })
  it('new gapping families reject touching shadows', () => {
    const examples: Array<[string, boolean, Bar[]]> = [
      ['gapping-doji', true, [b(30, 34, 36), b(37, 37.02, 38, 36)]],
      ['collapsing-doji-star', true, [b(30, 36, 36.2, 27), b(26, 26.02, 27, 25), b(23, 20)]],
      ['collapsing-doji-star', true, [b(30, 36), b(26, 26.02, 27, 25), b(23, 20, 25)]],
      ['two-gapping-lines', false, [b(12, 8, 12.8, 7.8), b(8, 6)]],
    ]
    for (const [id, trendUp, shape] of examples)
      expect(scan([...context(trendUp), ...shape]).some((x) => x.pattern === `archive-${id}`)).toBe(
        false
      )
  })
  it('two-line shooting star rejects a doji and an excessive lower shadow', () => {
    for (const final of [b(37, 37, 40, 36.8), b(37, 37.5, 40, 36)])
      expect(
        scan([...context(true), b(30, 36), final]).some(
          (x) => x.pattern === 'archive-shooting-star-two-line'
        )
      ).toBe(false)
  })
  it('requires a strict gap for tasuki and gap methods', () => {
    for (const close of [35, 33]) {
      const history = [...context(true), b(30, 34, 35), b(35.2, 40, 40.2, 35), b(39, close)]
      expect(
        scan(history).some((x) =>
          ['archive-tasuki-gap', 'archive-gap-three-methods'].includes(x.pattern)
        )
      ).toBe(false)
    }
  })
})
