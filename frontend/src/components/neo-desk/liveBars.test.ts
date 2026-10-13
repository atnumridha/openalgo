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
