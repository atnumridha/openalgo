import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { adminApi } from '@/api/admin'
import { useChartSession } from './useChartSession'

vi.mock('@/api/admin', () => ({ adminApi: { checkTimings: vi.fn() } }))
const at = (value: string) => Date.parse(value) / 1000
const now = at('2026-10-16T10:00:00+05:30')
function Panes({ time }: { time: number }) {
  const option = useChartSession('NFO', time)
  const index = useChartSession('NSE_INDEX', time)
  const other = useChartSession('BFO', time)
  return (
    <>
      <output aria-label="Option session">{option.state}</output>
      <output aria-label="Index session">{index.state}</output>
      <output aria-label="BFO session">{other.state}</output>
    </>
  )
}
const settle = () => act(async () => vi.advanceTimersByTimeAsync(1))

describe('Shared chart calendar', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(now * 1000)
    vi.mocked(adminApi.checkTimings).mockReset()
    vi.mocked(adminApi.checkTimings).mockImplementation(async (date) => ({
      date,
      timings:
        date === '2026-10-17'
          ? []
          : [
              { exchange: 'NFO', start_time: '09:15', end_time: '15:40' },
              { exchange: 'NSE', start_time: '09:15', end_time: '15:30' },
              { exchange: 'BFO', start_time: '18:00', end_time: '19:15' },
            ],
    }))
  })
  afterEach(() => vi.useRealTimers())

  it('shares one calendar read across index and option panes and follows each exchange window', async () => {
    const client = new QueryClient()
    render(
      <QueryClientProvider client={client}>
        <Panes time={now} />
      </QueryClientProvider>
    )
    expect(screen.getByLabelText('Option session')).toHaveTextContent('checking')
    await settle()
    expect(screen.getByLabelText('Option session')).toHaveTextContent('open')
    expect(screen.getByLabelText('Index session')).toHaveTextContent('open')
    expect(screen.getByLabelText('BFO session')).toHaveTextContent('closed')
    expect(adminApi.checkTimings).toHaveBeenCalledExactlyOnceWith('2026-10-16')
  })

  it('closes on the existing chart clock without polling and expires the old date after rollover', async () => {
    const client = new QueryClient()
    const view = render(
      <QueryClientProvider client={client}>
        <Panes time={now} />
      </QueryClientProvider>
    )
    await settle()
    await act(async () => vi.advanceTimersByTimeAsync(3600000))
    view.rerender(
      <QueryClientProvider client={client}>
        <Panes time={at('2026-10-16T15:35:00+05:30')} />
      </QueryClientProvider>
    )
    expect(screen.getByLabelText('Index session')).toHaveTextContent('closed')
    expect(screen.getByLabelText('Option session')).toHaveTextContent('open')
    expect(adminApi.checkTimings).toHaveBeenCalledTimes(1)
    view.rerender(
      <QueryClientProvider client={client}>
        <Panes time={at('2026-10-17T00:00:01+05:30')} />
      </QueryClientProvider>
    )
    expect(screen.getByLabelText('Option session')).toHaveTextContent('checking')
    await settle()
    expect(screen.getByLabelText('Option session')).toHaveTextContent('closed')
    expect(adminApi.checkTimings).toHaveBeenCalledTimes(2)
    expect(adminApi.checkTimings).toHaveBeenLastCalledWith('2026-10-17')
    await act(async () => vi.advanceTimersByTimeAsync(5 * 60000 + 1))
    expect(client.getQueryCache().getAll()).toHaveLength(1)
  })

  it('inhibits live formation when unavailable without creating endless retry requests', async () => {
    vi.mocked(adminApi.checkTimings).mockRejectedValue(Error('Offline'))
    render(
      <QueryClientProvider client={new QueryClient()}>
        <Panes time={now} />
      </QueryClientProvider>
    )
    await settle()
    expect(screen.getByLabelText('Option session')).toHaveTextContent('unavailable')
    await act(async () => vi.advanceTimersByTimeAsync(3600000))
    expect(adminApi.checkTimings).toHaveBeenCalledTimes(1)
  })

  it('reports malformed calendar responses as unavailable without assuming weekday hours', async () => {
    vi.mocked(adminApi.checkTimings).mockResolvedValue({ date: '2026-10-15', timings: [] })
    render(
      <QueryClientProvider client={new QueryClient()}>
        <Panes time={now} />
      </QueryClientProvider>
    )
    await settle()
    expect(screen.getByLabelText('Option session')).toHaveTextContent('unavailable')
    expect(screen.getByLabelText('Index session')).toHaveTextContent('unavailable')
  })
})
