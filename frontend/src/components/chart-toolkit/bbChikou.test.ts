import { describe, expect, it } from 'vitest'
import { calculateBBChikou } from './bbChikou'
import { closeTime, type Bar } from './model'

const start = Date.parse('2025-10-27T09:15:00+05:30') / 1000
const make = (close: number, i: number): Bar => ({
  time: start + i * 60,
  open: close,
  high: close + 0.1,
  low: close - 0.1,
  close,
  volume: 0,
})
const base = () => Array.from({ length: 60 }, (_, i) => make(i % 2 ? 101 : 99, i))
const bull = () => [...base(), make(103, 60), make(104, 61)]
const options = { seconds: 60, asOf: start + 63 * 60 }

describe('BB + Chikou confirmed price signals', () => {
  it('confirms BULL on the next candle and freezes middle-band stop and 1R', () => {
    const r = calculateBBChikou(bull(), options)
    expect(r.signals).toHaveLength(1)
    expect(r.latest).toMatchObject({ side: 'BULL', time: start + 61 * 60, entry: 104 })
    expect(r.latest!.stop).toBeCloseTo(r.points[61].middle!, 8)
    expect(r.latest!.target).toBeCloseTo(208 - r.latest!.stop, 8)
    const later = calculateBBChikou([...bull(), make(105, 62)], options)
    expect(later.latest).toEqual(r.latest)
  })
  it('confirms BEAR with symmetric risk levels', () => {
    const r = calculateBBChikou([...base(), make(97, 60), make(96, 61)], options)
    expect(r.latest).toMatchObject({ side: 'BEAR', entry: 96 })
    expect(r.latest!.target).toBeCloseTo(192 - r.latest!.stop, 8)
  })
  it('does not confirm a live candle or consume future history', () => {
    expect(calculateBBChikou(bull(), { ...options, asOf: start + 61 * 60 + 30 }).signals).toEqual(
      []
    )
    const full = [...bull(), make(105, 62)]
    const r = calculateBBChikou(full, { ...options, asOf: start + 62 * 60 })
    expect(r.signals).toEqual(calculateBBChikou(bull(), options).signals)
    expect(r.points.every((p) => p.time <= start + 62 * 60)).toBe(true)
  })
  it('rejects wick-only breaks and expires setups after one candle', () => {
    const wick = bull()
    wick[61] = { ...wick[61], close: 102, low: 101.9 }
    expect(calculateBBChikou(wick, options).signals).toEqual([])
    const expired = [...base(), make(103, 60), make(101, 61), make(104, 62)]
    expect(calculateBBChikou(expired, options).signals).toEqual([])
  })
  it('uses the historical full candle, not its close, for Chikou clearance', () => {
    const bars = bull()
    bars[35].high = 110
    expect(calculateBBChikou(bars, options).signals).toEqual([])
  })
  it('rejects gaps, overnight setups, and premarket bars', () => {
    for (const offset of [60, 86400]) {
      const bars = bull()
      bars[61].time += offset
      expect(calculateBBChikou(bars, { ...options, asOf: bars[61].time + 60 }).signals).toEqual([])
    }
    expect(
      calculateBBChikou(
        bull().map((b) => ({ ...b, time: b.time - 3 * 3600 })),
        options
      ).signals
    ).toEqual([])
  })
  it('has no signal before warmup and is stable across index price scales', () => {
    expect(calculateBBChikou(bull().slice(-20), options).signals).toEqual([])
    for (const scale of [250, 800]) {
      const bars = bull().map((b) => ({
        ...b,
        open: b.open * scale,
        high: b.high * scale,
        low: b.low * scale,
        close: b.close * scale,
      }))
      expect(calculateBBChikou(bars, options).latest?.entry).toBe(104 * scale)
    }
  })
  it('places only confirmed closes on actual candles 26 bars back', () => {
    const r = calculateBBChikou(bull(), { ...options, asOf: start + 61 * 60 + 30 })
    expect(r.chikou.at(-1)).toEqual({ time: start + 34 * 60, value: 103 })
  })
  it('clears previous-day reference levels and preserves historical signals', () => {
    const bars = [...bull(), { ...make(102, 62), time: start + 86400 }]
    const r = calculateBBChikou(bars, { ...options, asOf: start + 86460 })
    expect(r.latest).toBeNull()
    expect(r.signals).toHaveLength(1)
  })
})

it.each([
  '2026-10-31T23:00:00Z',
  '2026-11-01T23:00:00Z',
])('confirms crypto signals 24/7 across UTC midnight with an exact 2R target: %s', (iso) => {
  const begin = Date.parse(iso) / 1000,
    source = bull().map((b, i) => ({ ...b, time: begin + i * 60 }))
  const r = calculateBBChikou(source, {
    seconds: 60,
    asOf: begin + 63 * 60,
    continuous: true,
    reward: 2,
  } as never)
  expect(r.latest?.side).toBe('BULL')
  expect(r.latest!.target - r.latest!.entry).toBeCloseTo(2 * (r.latest!.entry - r.latest!.stop), 8)
})

it.each([
  0, 13500,
])('supports confirmed Daily BB setups at date-stamp offset %s using the instrument session close', (offset) => {
  const days: number[] = []
  for (let d = 0; days.length < 62; d++) {
    const date = new Date(Date.UTC(2026, 6, 1 + d))
    if (![0, 6].includes(date.getUTCDay())) days.push(date.getTime() / 1000 + offset)
  }
  const source = bull().map((b, i) => ({ ...b, time: days[i] })),
    last = source.at(-1)!,
    session = { start: 555, end: 930, offset: 19800 },
    asOf = closeTime(last, 86400, true, session)
  expect(calculateBBChikou(source, { seconds: 86400, asOf: asOf - 1, session }).signals).toEqual([])
  const result = calculateBBChikou(source, {
    seconds: 86400,
    asOf,
    session,
    reward: 2,
    tickSize: 0.05,
  })
  expect(result.latest?.side).toBe('BULL')
  expect(result.latest!.target - result.latest!.entry).toBeCloseTo(
    2 * (result.latest!.entry - result.latest!.stop),
    8
  )
})
