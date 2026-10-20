import { describe, expect, it } from 'vitest'
import { chartSessionOpen, chartSessionWindow, chartTickEpoch } from './chartSession'

const date = '2026-10-16'
const start = Date.parse('2026-10-16T09:15:00+05:30') / 1000
const end = Date.parse('2026-10-16T15:40:00+05:30') / 1000
const day = {
  date,
  timings: [
    { exchange: 'NSE', start_time: '09:15', end_time: '15:30' },
    { exchange: 'NFO', start_time: '09:15', end_time: '15:40' },
    { exchange: 'BSE', start_time: '09:15', end_time: '15:30' },
    { exchange: 'BFO', start_time: '09:15', end_time: '15:40' },
  ],
}

describe('Chart exchange sessions', () => {
  it('maps index aliases to their cash exchange while preserving derivative sessions', () => {
    expect(chartSessionWindow(day, date, 'NSE_INDEX')).toEqual({
      date,
      exchange: 'NSE',
      start,
      end: end - 600,
    })
    expect(chartSessionWindow(day, date, 'BSE_INDEX')?.exchange).toBe('BSE')
    expect(chartSessionWindow(day, date, 'NFO')).toEqual({ date, exchange: 'NFO', start, end })
    expect(chartSessionWindow(day, date, 'BFO')?.end).toBe(end)
  })
  it('uses the calendar for holidays and special weekend sessions', () => {
    const holiday = chartSessionWindow({ date, timings: [] }, date, 'NFO')
    expect(holiday).toEqual({ date, exchange: 'NFO', start: null, end: null })
    expect(chartTickEpoch(holiday, start + 1, start + 1, 'websocket')).toBeNull()
    const special = chartSessionWindow(
      {
        date: '2026-11-08',
        timings: [{ exchange: 'BFO', start_time: '18:00', end_time: '19:15' }],
      },
      '2026-11-08',
      'BFO'
    )
    const during = Date.parse('2026-11-08T18:30:00+05:30') / 1000
    expect(chartTickEpoch(special, during, during, 'websocket')).toBe(during)
    expect(chartSessionOpen(special, during - 3600)).toBe(false)
  })
  it('requires both receipt time and the actual exchange tick inside the verified window', () => {
    const window = chartSessionWindow(day, date, 'NFO')
    expect(chartTickEpoch(window, start, start, 'websocket')).toBe(start)
    expect(chartTickEpoch(window, start - 1, start + 1, 'websocket')).toBeNull()
    expect(chartTickEpoch(window, end, end - 1, 'websocket')).toBeNull()
    expect(chartTickEpoch(window, end - 1, end, 'websocket')).toBeNull()
    expect(chartTickEpoch(window, start + 1, start - 1, 'websocket')).toBeNull()
  })
  it('rejects stale timestamps, fresh receipt times without an exchange tick, and REST copies', () => {
    const window = chartSessionWindow(day, date, 'NFO')
    const now = start + 60
    expect(chartTickEpoch(window, now * 1000, now, 'websocket')).toBe(now)
    expect(chartTickEpoch(window, now - 11, now, 'websocket')).toBeNull()
    expect(chartTickEpoch(window, undefined, now, 'websocket')).toBeNull()
    expect(chartTickEpoch(window, 'bad', now, 'websocket')).toBeNull()
    expect(chartTickEpoch(window, now, now, 'rest')).toBeNull()
    expect(chartTickEpoch(window, now, now, undefined)).toBeNull()
  })
  it('fails closed for invalid or mismatched calendar data', () => {
    expect(chartSessionWindow(day, '2026-10-17', 'NFO')).toBeNull()
    for (const start_time of ['bad', '25:00', '09:60', '']) {
      expect(
        chartSessionWindow(
          { date, timings: [{ exchange: 'NFO', start_time, end_time: '15:40' }] },
          date,
          'NFO'
        )
      ).toBeNull()
    }
    expect(chartTickEpoch(null, start, start, 'websocket')).toBeNull()
  })
})
