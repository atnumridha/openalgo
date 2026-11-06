import { it, expect } from 'vitest'
import { feedTimeMs, nextLiveBar } from './liveBars'
it('accepts actual Kotak numeric millisecond timestamps and ISO timestamps', () => {
  const ms = Date.parse('2026-10-13T10:00:03+05:30')
  expect(feedTimeMs(ms)).toBe(ms)
  expect(feedTimeMs('2026-10-13T10:00:03+05:30')).toBe(ms)
  const previous = { time: ms / 1000 - 3, open: 50, high: 51, low: 49, close: 50, volume: 65 }
  expect(nextLiveBar(previous, 55, ms, '5m', ms + 200)?.close).toBe(55)
})
it('never invents a current candle for missing/stale time or an after-hours snapshot', () => {
  const now = Date.parse('2026-10-13T20:55:00+05:30')
  expect(nextLiveBar(undefined, 55, now, '5m', now)).toBeNull()
  expect(nextLiveBar(undefined, 55, undefined, '5m', now)).toBeNull()
  const open = Date.parse('2026-10-13T10:00:00+05:30')
  expect(nextLiveBar(undefined, 55, open, '5m', open + 16000)).toBeNull()
})

it('updates a daily broker candle on each fresh quote while preserving its timestamp and open', () => {
  const now = Date.parse('2026-10-26T10:00:00+05:30')
  const previous = {
    time: Date.parse('2026-10-26T00:00:00+05:30') / 1000,
    open: 100,
    high: 103,
    low: 98,
    close: 102,
    volume: 100,
  }
  expect(nextLiveBar(previous, 105, now, '1d', now)).toEqual({ ...previous, high: 105, close: 105 })
})

it('requires genuine session OHLC to create a missing daily candle', () => {
  const now = Date.parse('2026-10-26T10:00:00+05:30')
  const prior = {
    time: Date.parse('2026-10-23T00:00:00+05:30') / 1000,
    open: 90,
    high: 95,
    low: 89,
    close: 94,
    volume: 100,
  }
  expect(nextLiveBar(prior, 105, now, '1d', now)).toBeNull()
  expect(
    nextLiveBar(prior, 105, now, '1d', now, { open: 100, high: 106, low: 98, volume: 500 })
  ).toEqual({
    time: Date.parse('2026-10-26T00:00:00+05:30') / 1000,
    open: 100,
    high: 106,
    low: 98,
    close: 105,
    volume: 500,
  })
})

it.each([
  ['30m', '2026-10-14T09:29:00+05:30', '2026-10-14T09:15:00+05:30'],
  ['30m', '2026-10-14T09:44:00+05:30', '2026-10-14T09:15:00+05:30'],
  ['30m', '2026-10-14T09:45:00+05:30', '2026-10-14T09:45:00+05:30'],
  ['1h', '2026-10-14T10:14:00+05:30', '2026-10-14T09:15:00+05:30'],
  ['1h', '2026-10-14T10:15:00+05:30', '2026-10-14T10:15:00+05:30'],
])('anchors %s live candles to the 09:15 market open at %s', (interval, stamp, expected) => {
  const now = Date.parse(stamp)
  expect(nextLiveBar(undefined, 100, now, interval, now)?.time).toBe(Date.parse(expected) / 1000)
})

it('uses the configured exchange session for evening commodity and late currency quotes', () => {
  for (const [time, start, end] of [
    ['2026-10-30T20:00:03+05:30', 540, 1435],
    ['2026-10-30T16:00:03+05:30', 540, 1020],
  ] as const) {
    const now = Date.parse(time),
      bar = nextLiveBar(undefined, 100, now, '5m', now, undefined, { start, end, offset: 19800 })
    expect(bar?.close).toBe(100)
    expect(bar?.time).toBe(Math.floor(now / 1000 / 300) * 300)
  }
  const now = Date.parse('2026-10-30T17:00:00+05:30')
  expect(
    nextLiveBar(undefined, 100, now, '5m', now, undefined, { start: 540, end: 1020, offset: 19800 })
  ).toBeNull()
})
