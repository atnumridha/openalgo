import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { scalpingApi } from '@/api/scalping'
import { useAuthStore } from '@/stores/authStore'
import { DashboardIndicatorSignals } from './DashboardIndicatorSignals'
import { INDICATORS } from './nineIndicators'

const panel = vi.hoisted(() => vi.fn())
vi.mock('./NineIndicatorPanel', () => ({
  NineIndicatorPanel: (props: unknown) => {
    panel(props)
    return <div>All nine signal rows</div>
  },
}))
vi.mock('@/api/scalping', () => ({ scalpingApi: { getHistory: vi.fn() } }))
const now = Date.parse('2026-10-27T12:00:00+05:30') / 1000
const history = (symbol = 'NIFTY') => ({
  status: 'success',
  symbol,
  exchange: 'NSE_INDEX',
  interval: '15m',
  date: '2026-10-27',
  candles: Array.from({ length: 80 }, (_, i) => ({
    time: now - (79 - i) * 900 + 19800,
    open: 100 + i,
    high: 102 + i,
    low: 99 + i,
    close: 101 + i,
    volume: 0,
  })),
})
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <DashboardIndicatorSignals />
    </QueryClientProvider>
  )
  return client
}
beforeEach(() => {
  vi.spyOn(Date, 'now').mockReturnValue(now * 1000)
  useAuthStore.setState({ user: { username: 'test' } as never })
  vi.mocked(scalpingApi.getHistory).mockResolvedValue(history())
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.clearAllMocks()
})
it('shows all nine independent studies for Nifty using only completed candles', async () => {
  mount()
  await waitFor(() => expect(panel.mock.lastCall?.[0].ready).toBe(true))
  expect(panel.mock.lastCall?.[0]).toMatchObject({
    symbol: 'NIFTY',
    exchange: 'NSE_INDEX',
    interval: '15m',
    seconds: 900,
    embedded: true,
    enabled: INDICATORS.map((i) => i.id),
  })
  expect(panel.mock.lastCall?.[0].result.lastTime).toBe(now - 900)
  expect(screen.queryByText(/Nine independent indicators/)).not.toBeInTheDocument()
})
it('supports the shared dashboard index selection used by the top market summary', async () => {
  const change = vi.fn()
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <DashboardIndicatorSignals symbol="SENSEX" onSymbolChange={change} />
    </QueryClientProvider>
  )
  await waitFor(() => expect(panel.mock.lastCall?.[0].symbol).toBe('SENSEX'))
  fireEvent.change(screen.getByLabelText('Signal index'), { target: { value: 'NIFTY' } })
  expect(change).toHaveBeenCalledWith('NIFTY')
})
it('requires a post-close history observation before confirming a cached forming candle', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  vi.mocked(Date.now).mockReturnValue((now - 1) * 1000)
  const client = mount()
  await waitFor(() => expect(panel.mock.lastCall?.[0].ready).toBe(true))
  expect(panel.mock.lastCall?.[0].result.lastTime).toBe(now - 1800)
  vi.mocked(Date.now).mockReturnValue((now + 5) * 1000)
  await act(async () => {
    vi.advanceTimersByTime(6000)
  })
  expect(panel.mock.lastCall?.[0].result.lastTime).toBe(now - 1800)
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['dashboard-indicator-history'] })
  })
  await waitFor(() => expect(panel.mock.lastCall?.[0].result.lastTime).toBe(now - 900))
})
it('switches to Sensex without carrying Nifty signals into the new request', async () => {
  mount()
  await waitFor(() => expect(panel.mock.lastCall?.[0].ready).toBe(true))
  vi.mocked(scalpingApi.getHistory).mockImplementation(() => new Promise(() => {}))
  fireEvent.change(screen.getByLabelText('Signal index'), { target: { value: 'SENSEX' } })
  expect(panel.mock.lastCall?.[0]).toMatchObject({
    symbol: 'SENSEX',
    exchange: 'BSE_INDEX',
    ready: false,
    result: null,
  })
  await waitFor(() =>
    expect(scalpingApi.getHistory).toHaveBeenLastCalledWith(
      'SENSEX',
      'BSE_INDEX',
      '15m',
      undefined,
      expect.objectContaining({ timeoutMs: 60000 })
    )
  )
})
it('supports a separate dashboard timeframe and an explicit history error', async () => {
  mount()
  await waitFor(() => expect(panel.mock.lastCall?.[0].ready).toBe(true))
  vi.mocked(scalpingApi.getHistory).mockRejectedValue(new Error('Broker timeout'))
  fireEvent.change(screen.getByLabelText('Signal timeframe'), { target: { value: '5m' } })
  await waitFor(() => expect(screen.getByText(/Broker history unavailable/)).toBeInTheDocument())
  expect(panel.mock.lastCall?.[0]).toMatchObject({
    interval: '5m',
    seconds: 300,
    ready: false,
    result: null,
  })
  expect(screen.getByRole('button', { name: 'Retry signal history' })).toBeInTheDocument()
})
