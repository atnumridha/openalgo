import { expect, it } from 'vitest'
import { archivePatternEvents } from './archivePatternEngine'
import { latestArchiveReading } from './archiveConfirmations'
import type { Bar } from './model'
const bars: Bar[] = [
  [130, 132, 128, 130],
  [120, 122, 118, 120],
  [110, 112, 108, 110],
  [100, 102, 98, 100],
  [90, 101, 90, 100],
  [100, 104, 99, 103],
].map(([open, high, low, close], i) => ({
  time: 1000 + i * 60,
  open,
  high,
  low,
  close,
  volume: 10,
}))
it('wires real added shapes to next-candle confirmation and the current reading', () => {
  const prefix = bars.slice(0, -1),
    events = archivePatternEvents(prefix, 'all', 60)
  expect(events).toContainEqual(
    expect.objectContaining({ name: 'Bullish Belt Hold', confirmed: false, time: 1240 })
  )
  expect(latestArchiveReading(events, prefix).side).toBe('WAIT')
  const all = archivePatternEvents(bars, 'all', 60)
  expect(all).toContainEqual(
    expect.objectContaining({
      name: 'Belt Hold confirmed',
      confirmed: true,
      time: 1300,
      side: 'CALL',
    })
  )
  expect(latestArchiveReading(all, bars)).toMatchObject({ side: 'BULL', time: 1300 })
  expect(all.filter((m) => m.time <= 1240)).toEqual(events)
})
it('resets confirmation after missing candles and separates setup/raw views', () => {
  const gap = bars.map((b) => ({ ...b }))
  gap.at(-1)!.time += 600
  expect(
    archivePatternEvents(gap, 'all', 60).some(
      (m) => m.time === gap.at(-1)!.time && m.name === 'Belt Hold confirmed'
    )
  ).toBe(false)
  expect(archivePatternEvents(bars, 'setups', 60).every((m) => m.confirmed)).toBe(true)
  expect(archivePatternEvents(bars, 'off', 60)).toEqual([])
})
it('keeps structure across scheduled NSE closures but not missing in-session candles', () => {
  const session = { start: 555, end: 930, offset: 19800 }
  const day = Date.UTC(2026, 9, 28) / 1000
  const end = day + session.end * 60 - session.offset
  const nextStart = day + 86400 + session.start * 60 - session.offset
  const source = bars.map((b, i) => ({ ...b, time: i < 5 ? end - (5 - i) * 60 : nextStart }))
  expect(
    archivePatternEvents(source, 'all', 60, -Infinity, Infinity, session, true)
  ).toContainEqual(expect.objectContaining({ name: 'Belt Hold confirmed', time: nextStart }))
  const missing = source.map((b) => ({ ...b }))
  missing.at(-1)!.time += 60
  expect(
    archivePatternEvents(missing, 'all', 60, -Infinity, Infinity, session, true).some(
      (m) => m.name === 'Belt Hold confirmed'
    )
  ).toBe(false)
})
