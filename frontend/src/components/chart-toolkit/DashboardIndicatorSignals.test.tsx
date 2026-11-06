import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { scalpingApi } from '@/api/scalping'
import { useAuthStore } from '@/stores/authStore'
import { useMarketData } from '@/hooks/useMarketData'
import { DashboardIndicatorSignals } from './DashboardIndicatorSignals'
import { INDICATORS } from './nineIndicators'
import * as candleSeeds from './candleProbabilitySeeds'

const panel = vi.hoisted(() => vi.fn())
vi.mock('./NineIndicatorPanel', () => ({
  NineIndicatorPanel: (props: unknown) => {
    panel(props)
    return <div>All nine signal rows</div>
  },
}))
vi.mock('@/api/scalping', () => ({ scalpingApi: { getHistory: vi.fn() } }))
vi.mock('@/hooks/useMarketData', () => ({ useMarketData: vi.fn() }))
const stream = () => ({
  data: new Map(),
  isConnected: true,
  isAuthenticated: true,
  isConnecting: false,
  isPaused: false,
  isFallbackMode: false,
  connectionEpoch: 1,
  error: null,
  connect: vi.fn(),
  disconnect: vi.fn(),
})
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
  vi.mocked(useMarketData).mockReturnValue(stream())
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
it('shows a separate candle-pattern study without adding it to the nine-indicator vote', async () => {
  mount()
  await waitFor(() => expect(panel.mock.lastCall?.[0].ready).toBe(true))
  expect(screen.getByRole('region', { name: 'Candlestick probability' })).toBeInTheDocument()
  expect(panel.mock.lastCall?.[0].enabled).toEqual(INDICATORS.map((i) => i.id))
})
it.each([
  'invalid final candle',
  'conflicting duplicate',
])('rejects %s before producing a candle decision', async (failure) => {
  vi.spyOn(candleSeeds, 'getCandleSeed').mockImplementation((scope) => ({
    version: 1,
    ...scope,
    trainedThrough: now - 86400,
    source: 'Regression fixture',
    counts: { 'engulfing:CALL:flat': { targets: 90, stops: 10, timeouts: 0, ambiguous: 0 } },
  }))
  const base = now - 13 * 60 + 19800
  const candles = Array.from({ length: 10 }, (_, i) => ({
    time: base + i * 60,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 0,
  }))
  candles.push({ time: base + 10 * 60, open: 100.5, high: 100.8, low: 99.8, close: 100, volume: 0 })
  candles.push({ time: base + 11 * 60, open: 99.9, high: 101, low: 99.5, close: 100.8, volume: 0 })
  vi.mocked(scalpingApi.getHistory).mockResolvedValue({ ...history(), interval: '1m', candles })
  const client = mount()
  fireEvent.change(screen.getByLabelText('Signal timeframe'), { target: { value: '1m' } })
  await waitFor(() =>
    expect(screen.getByRole('status', { name: 'Candlestick decision' })).toHaveTextContent(
      'BUY CALL'
    )
  )
  const bad =
    failure === 'invalid final candle'
      ? { ...candles.at(-1)!, time: base + 12 * 60, high: 99 }
      : { ...candles.at(-1)!, close: 100.9 }
  vi.mocked(scalpingApi.getHistory).mockResolvedValue({
    ...history(),
    interval: '1m',
    candles: [...candles, bad],
  })
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['dashboard-indicator-history'] })
  })
  await waitFor(() =>
    expect(screen.getByRole('status', { name: 'Candlestick decision' })).toHaveTextContent('WAIT')
  )
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
  let finish!: (value: ReturnType<typeof history>) => void
  vi.mocked(scalpingApi.getHistory).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  vi.mocked(Date.now).mockReturnValue((now + 5) * 1000)
  await act(async () => {
    vi.advanceTimersByTime(6000)
  })
  expect(panel.mock.lastCall?.[0].result.lastTime).toBe(now - 1800)
  await act(async () => {
    if (!finish) void client.invalidateQueries({ queryKey: ['dashboard-indicator-history'] })
    await Promise.resolve()
    finish(history())
  })
  await waitFor(() => expect(panel.mock.lastCall?.[0].result.lastTime).toBe(now - 900))
})
it('updates live numeric values on a tick while leaving confirmed events unchanged', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree = () => (
    <QueryClientProvider client={client}>
      <DashboardIndicatorSignals />
    </QueryClientProvider>
  )
  const view = render(tree())
  await waitFor(() => expect(panel.mock.lastCall?.[0].ready).toBe(true))
  const confirmed = panel.mock.lastCall?.[0].result
  const tickAt = now * 1000 + 2000
  vi.mocked(Date.now).mockReturnValue(tickAt)
  vi.mocked(useMarketData).mockReturnValue({
    ...stream(),
    data: new Map([
      [
        'NSE_INDEX:NIFTY',
        {
          symbol: 'NIFTY',
          exchange: 'NSE_INDEX',
          updateSource: 'websocket',
          connectionEpoch: 1,
          lastUpdate: tickAt,
          data: { ltp: 250, timestamp: new Date(tickAt).toISOString() },
        },
      ],
    ]),
  })
  view.rerender(tree())
  await waitFor(() => expect(panel.mock.lastCall?.[0].liveValues?.ma).toBeGreaterThan(50))
  expect(panel.mock.lastCall?.[0].result).toEqual(confirmed)
  expect(panel.mock.lastCall?.[0].liveValueTime).toBe(now + 2)
  expect(
    within(screen.getByRole('region', { name: 'Dashboard indicator signals' })).getByRole('status')
  ).toHaveTextContent(/tick/i)
  expect(scalpingApi.getHistory).toHaveBeenCalledTimes(1)
  vi.mocked(useMarketData).mockReturnValue({ ...stream(), isAuthenticated: false })
  view.rerender(tree())
  expect(panel.mock.lastCall?.[0].liveValues).toBeUndefined()
})
it('requests new broker history after the candle closes without waiting for the old30s poll', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  vi.mocked(Date.now).mockReturnValue((now - 1) * 1000)
  mount()
  await waitFor(() => expect(panel.mock.lastCall?.[0].ready).toBe(true))
  vi.mocked(Date.now).mockReturnValue((now + 2) * 1000)
  await act(async () => {
    vi.advanceTimersByTime(3000)
  })
  await waitFor(() => expect(panel.mock.lastCall?.[0].result.lastTime).toBe(now - 900))
  expect(scalpingApi.getHistory).toHaveBeenCalledTimes(2)
})
it('waits for a new tick when the account changes even if its history is cached', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree = () => (
    <QueryClientProvider client={client}>
      <DashboardIndicatorSignals />
    </QueryClientProvider>
  )
  const view = render(tree())
  await waitFor(() => expect(panel.mock.lastCall?.[0].ready).toBe(true))
  const oldQuery = client.getQueryCache().findAll()[0]
  client.setQueryData(
    [oldQuery.queryKey[0], 'second-account', ...oldQuery.queryKey.slice(2)],
    oldQuery.state.data
  )
  const tickAt = now * 1000 + 2000
  vi.mocked(Date.now).mockReturnValue(tickAt)
  vi.mocked(useMarketData).mockReturnValue({
    ...stream(),
    data: new Map([
      [
        'NSE_INDEX:NIFTY',
        {
          symbol: 'NIFTY',
          exchange: 'NSE_INDEX',
          updateSource: 'websocket',
          connectionEpoch: 1,
          lastUpdate: tickAt,
          data: { ltp: 250, timestamp: new Date(tickAt).toISOString() },
        },
      ],
    ]),
  })
  view.rerender(tree())
  expect(panel.mock.lastCall?.[0].liveValues?.ma).toBeGreaterThan(50)
  vi.mocked(Date.now).mockReturnValue(tickAt + 1)
  act(() => useAuthStore.setState({ user: { username: 'second-account' } as never }))
  expect(panel.mock.lastCall?.[0].liveValues).toBeUndefined()
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
