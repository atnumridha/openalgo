import { describe, expect, it, vi } from 'vitest'
import { loadChartRangeHistory } from './chartRangeHistory'

const dayBars = (date: string) => [
  {
    time: Date.parse(`${date}T09:15:00Z`) / 1000,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 10,
  },
]
describe('Date range history', () => {
  it('loads both selected dates, skips weekends, sorts and keeps warmup outside the visible range', async () => {
    const fetchDay = vi.fn(async (date: string) => ({ status: 'success', candles: dayBars(date) }))
    const result = await loadChartRangeHistory(
      { start: '2026-10-09', end: '2026-10-12' },
      fetchDay,
      dayBars('2026-10-08')
    )
    expect(fetchDay.mock.calls.map((c) => c[0])).toEqual(['2026-10-09', '2026-10-12'])
    expect(result.candles.map((b) => b.time)).toEqual(
      ['2026-10-08', '2026-10-09', '2026-10-12'].map((d) => dayBars(d)[0].time)
    )
    expect(result.emptyDates).toEqual([])
  })
  it('reports days without candles without substituting nearby sessions', async () => {
    const result = await loadChartRangeHistory(
      { start: '2026-10-14', end: '2026-10-15' },
      async (date) => ({ status: 'success', candles: date.endsWith('14') ? [] : dayBars(date) })
    )
    expect(result.emptyDates).toEqual(['2026-10-14'])
    expect(result.candles).toEqual(dayBars('2026-10-15'))
  })
  it('rejects an invalid range and identifies broker failures instead of returning partial history', async () => {
    const fetchDay = vi.fn(async () => ({ status: 'error', message: 'Unavailable', candles: [] }))
    await expect(
      loadChartRangeHistory({ start: '2026-10-15', end: '2026-10-14' }, fetchDay)
    ).rejects.toThrow('From date')
    expect(fetchDay).not.toHaveBeenCalled()
    await expect(
      loadChartRangeHistory({ start: '2026-10-14', end: '2026-10-15' }, fetchDay)
    ).rejects.toThrow('2026-10-14')
  })
  it('stops requesting more dates when the user changes the range', async () => {
    const controller = new AbortController()
    const fetchDay = vi.fn(async (date: string) => {
      controller.abort()
      return { status: 'success', candles: dayBars(date) }
    })
    await expect(
      loadChartRangeHistory(
        { start: '2026-10-05', end: '2026-10-15' },
        fetchDay,
        [],
        controller.signal
      )
    ).rejects.toThrow()
    expect(fetchDay.mock.calls.length).toBeLessThanOrEqual(2)
  })
})

it('does not count a fallback response for another date as coverage', async () => {
  const result = await loadChartRangeHistory(
    { start: '2026-10-14', end: '2026-10-15' },
    async () => ({ status: 'success', candles: dayBars('2026-10-14') })
  )
  expect(result.emptyDates).toEqual(['2026-10-15'])
  expect(result.candles).toEqual(dayBars('2026-10-14'))
})
