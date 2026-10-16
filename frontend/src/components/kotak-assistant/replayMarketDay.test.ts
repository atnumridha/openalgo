import { describe, expect, it, vi } from 'vitest'
import { loadReplayCalendar, replayDefaultDate } from './replayMarketDay'

const readDay = async (date: string) => ({
  date,
  timings:
    [0, 6].includes(new Date(`${date}T00:00Z`).getUTCDay()) || date === '2026-10-20'
      ? []
      : [{ exchange: 'NFO', start_time: '09:15', end_time: '15:40' }],
})
describe('Dashboard replay market date', () => {
  it('uses today while open and the previous trading day when closed', async () => {
    const calendar = await loadReplayCalendar('2026-10-16', 'NFO', readDay)
    expect(replayDefaultDate(calendar, Date.UTC(2026, 9, 16, 5))).toBe('2026-10-16')
    expect(replayDefaultDate(calendar, Date.UTC(2026, 9, 15, 18, 40))).toBe('2026-10-15')
    expect(replayDefaultDate(calendar, Date.UTC(2026, 9, 16, 12))).toBe('2026-10-15')
  })
  it('skips weekends and exchange holidays when choosing the previous session', async () => {
    expect((await loadReplayCalendar('2026-10-19', 'NFO', readDay)).previousDate).toBe('2026-10-16')
    expect((await loadReplayCalendar('2026-10-21', 'NFO', readDay)).previousDate).toBe('2026-10-19')
  })
  it('honours special sessions on weekends and matches the selected exchange', async () => {
    const fetch = vi.fn(async (date: string) => ({
      date,
      timings:
        date === '2026-11-08'
          ? [{ exchange: 'BFO', start_time: '18:00', end_time: '19:15' }]
          : [0, 6].includes(new Date(`${date}T00:00Z`).getUTCDay())
            ? []
            : [{ exchange: 'BFO', start_time: '09:15', end_time: '15:40' }],
    }))
    const calendar = await loadReplayCalendar('2026-11-08', 'BFO', fetch)
    expect(replayDefaultDate(calendar, Date.UTC(2026, 10, 8, 13))).toBe('2026-11-08')
    expect(replayDefaultDate(calendar, Date.UTC(2026, 10, 8, 10))).toBe('2026-11-06')
  })
  it('fails explicitly if the exchange calendar cannot be loaded', async () => {
    await expect(
      loadReplayCalendar('2026-10-16', 'NFO', async () => {
        throw Error('Unavailable')
      })
    ).rejects.toThrow('Unavailable')
  })
})
