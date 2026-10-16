import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { neoReportsApi } from '@/api/neoReports'
import { scalpingApi } from '@/api/scalping'
import { NeoMarketChart } from './NeoMarketChart'

const mocks = vi.hoisted(() => ({
  series: [] as Array<{ setData: ReturnType<typeof vi.fn> }>,
  remove: vi.fn(),
  createLine: vi.fn(() => ({})),
  range: vi.fn(),
  market: vi.fn(() => ({ data: new Map(), isConnected: true })),
}))
vi.mock('@/hooks/useMarketData', () => ({
  useMarketData: mocks.market,
}))
vi.mock('@/api/neoDesk', () => ({
  neoDeskApi: {
    chart: async () => ({ overlays: [{ label: 'SL / trail', price: '95', run_id: 1 }] }),
    state: async () => ({ profile: 'orb_trail' }),
  },
}))
vi.mock('@/api/neoReports', () => ({ neoReportsApi: { chart: vi.fn() } }))
vi.mock('@/api/scalping', () => ({ scalpingApi: { getHistory: vi.fn() } }))
vi.mock('lightweight-charts', () => ({
  CandlestickSeries: 'candles',
  LineSeries: 'line',
  CrosshairMode: { Normal: 0 },
  LineStyle: { Dashed: 2 },
  TickMarkType: { Time: 3, TimeWithSeconds: 4 },
  createChart: () => ({
    addSeries: () => {
      const s = {
        setData: vi.fn(),
        update: vi.fn(),
        applyOptions: vi.fn(),
        createPriceLine: mocks.createLine,
        removePriceLine: vi.fn(),
        attachPrimitive: vi.fn(),
        priceScale: () => ({ applyOptions: vi.fn() }),
      }
      mocks.series.push(s)
      return s
    },
    panes: () => [{ setStretchFactor: vi.fn() }, { setStretchFactor: vi.fn() }],
    timeScale: () => ({ setVisibleLogicalRange: mocks.range }),
    subscribeCrosshairMove: vi.fn(),
    remove: mocks.remove,
    removeSeries: vi.fn(),
  }),
}))
const history = {
  status: 'success',
  symbol: 'NIFTY',
  exchange: 'NSE_INDEX',
  interval: '15m',
  date: '2026-10-15',
  candles: Array.from({ length: 24 }, (_, i) => ({
    time: Date.UTC(2026, 9, 15, 9, 15) / 1000 + i * 900,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 0,
  })),
}
function mount() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" />
    </QueryClientProvider>
  )
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(Date, 'now').mockReturnValue(Date.UTC(2026, 9, 15, 9, 50))
  mocks.series.length = 0
  mocks.market.mockReturnValue({ data: new Map(), isConnected: true })
  localStorage.clear()
  vi.mocked(neoReportsApi.chart).mockResolvedValue({ ...history, candles: [] })
  vi.mocked(scalpingApi.getHistory).mockImplementation(
    async (_symbol, _exchange, _interval, date) =>
      date
        ? {
            ...history,
            date,
            candles:
              new Date(`${date}T00:00:00Z`).getUTCDay() === 0
                ? []
                : history.candles.map((b) => ({
                    ...b,
                    time: b.time + (Date.parse(date) - Date.parse('2026-10-15')) / 1000,
                  })),
          }
        : history
  )
})
it('renders real normalized broker candles, owned stops and studies through TradingView and cleans up', async () => {
  const view = mount()
  await waitFor(() => expect(mocks.series[0]?.setData.mock.calls.at(-1)?.[0]).toHaveLength(24))
  expect(mocks.series[0].setData.mock.calls.at(-1)?.[0][0].time).toBe(
    Date.UTC(2026, 9, 15, 3, 45) / 1000
  )
  expect(mocks.createLine).toHaveBeenCalledWith(
    expect.objectContaining({ price: 95, title: 'SL / trail' })
  )
  expect(screen.getByLabelText('RSI 14')).toBeChecked()
  expect(screen.getByLabelText('Candle prices')).toHaveTextContent('O 100.00')
  expect(screen.getByText(/24 candles/)).toBeVisible()
  view.unmount()
  expect(mocks.remove).toHaveBeenCalledOnce()
})
it('shows broker history failure immediately and offers a retry', async () => {
  vi.mocked(scalpingApi.getHistory).mockRejectedValue(Error('Kotak history unavailable'))
  mount()
  expect(await screen.findByRole('alert', {}, { timeout: 2500 })).toHaveTextContent(
    'Kotak history unavailable'
  )
  expect(screen.getByRole('button', { name: 'Retry history' })).toBeEnabled()
})

it('waits for a listed instrument without sending an empty history request', async () => {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart symbol="" exchange="" interval="15m" title="Call (CE)" />
    </QueryClientProvider>
  )
  expect(await screen.findByText('Choose an expiry and strike to load prices.')).toBeVisible()
  expect(scalpingApi.getHistory).not.toHaveBeenCalled()
})

it('reopens SQL candles without live subscriptions, quotes or current-position lines', async () => {
  vi.mocked(neoReportsApi.chart).mockResolvedValue(history)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['neo-chart', 'NSE_INDEX', 'NIFTY', '15m'], {
    overlays: [{ label: 'SL / trail', price: '95', run_id: 1 }],
  })
  render(
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="15m"
        savedRange={{ start: '2025-11-03', end: '2025-11-03' }}
      />
    </QueryClientProvider>
  )
  await waitFor(() => expect(mocks.series[0]?.setData.mock.calls.at(-1)?.[0]).toHaveLength(24))
  expect(mocks.market).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }))
  expect(scalpingApi.getHistory).not.toHaveBeenCalled()
  expect(mocks.createLine).not.toHaveBeenCalledWith(
    expect.objectContaining({ title: 'SL / trail' })
  )
  expect(screen.queryByLabelText('From date IST')).not.toBeInTheDocument()
  expect(screen.getByText('Saved close')).toBeVisible()
  expect(screen.getByText(/SQL saved history/)).toBeVisible()
})

it('replays only revealed candles, buffers live ticks and restores the latest chart', async () => {
  vi.mocked(Date.now).mockReturnValue(Date.UTC(2026, 9, 15, 9, 51))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = (title = 'NIFTY') => (
    <QueryClientProvider client={client}>
      <NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" title={title} />
    </QueryClientProvider>
  )
  const view = render(content())
  await waitFor(() => expect(mocks.series[0]?.setData.mock.calls.at(-1)?.[0]).toHaveLength(24))
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(mocks.series[0].setData.mock.calls.at(-1)?.[0]).toHaveLength(1)
  expect(screen.getByLabelText('Replay time')).toHaveTextContent('1/24')
  fireEvent.click(screen.getByRole('button', { name: 'Next replay candle' }))
  expect(mocks.series[0].setData.mock.calls.at(-1)?.[0]).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: 'Latest candles' }))
  expect(mocks.range).toHaveBeenLastCalledWith({ from: -98, to: 10 })
  const writes = mocks.series[0].setData.mock.calls.length
  mocks.market.mockReturnValue({
    data: new Map([['NSE_INDEX:NIFTY', { data: { ltp: 107, timestamp: Date.now() } }]]),
    isConnected: true,
  })
  view.rerender(content('NIFTY live tick'))
  expect(mocks.series[0].setData).toHaveBeenCalledTimes(writes)
  expect(screen.getByLabelText('Replay time')).toHaveTextContent('2/24')
  fireEvent.click(screen.getByRole('button', { name: 'Return to live' }))
  expect(mocks.series[0].setData.mock.calls.at(-1)?.[0]).toHaveLength(25)
  expect(mocks.series[0].setData.mock.calls.at(-1)?.[0].at(-1).close).toBe(107)
  expect(screen.getByRole('button', { name: 'Replay charts' })).toBeVisible()
  view.unmount()
})

afterEach(() => vi.restoreAllMocks())

it('defaults to today, filters every plotted series, and keeps historical selection isolated from live ticks', async () => {
  const previous = history.candles.map((b) => ({ ...b, time: b.time - 86400, close: 99.5 }))
  vi.mocked(scalpingApi.getHistory).mockImplementation(
    async (_symbol, _exchange, _interval, date) =>
      date
        ? { ...history, candles: date === '2026-10-14' ? previous : [] }
        : { ...history, candles: [...previous, ...history.candles] }
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = (title = 'NIFTY') => (
    <QueryClientProvider client={client}>
      <NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" title={title} />
    </QueryClientProvider>
  )
  const view = render(content())
  await waitFor(() => expect(mocks.series[0]?.setData.mock.calls.at(-1)?.[0]).toHaveLength(24))
  expect(screen.getByLabelText('From date IST')).toHaveValue('2026-10-15')
  const todayStart = Date.UTC(2026, 9, 14, 18, 30) / 1000
  for (const series of mocks.series) {
    const values = series.setData.mock.calls.at(-1)?.[0] ?? []
    expect(
      values.every((b: { time: number }) => b.time >= todayStart && b.time < todayStart + 86400)
    ).toBe(true)
  }
  // Previous session warms RSI/Donchian so they are available on today's first candle.
  expect(mocks.series[1].setData.mock.calls.at(-1)?.[0]).toHaveLength(24)
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-14' } })
  fireEvent.input(screen.getByLabelText('To date IST'), { target: { value: '2026-10-14' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  await waitFor(() => expect(mocks.series[0].setData.mock.calls.at(-1)?.[0]).toHaveLength(24))
  expect(mocks.series[0].setData.mock.calls.at(-1)?.[0].at(-1).time).toBe(
    history.candles.at(-1)!.time - 19800 - 86400
  )
  const writes = mocks.series[0].setData.mock.calls.length
  mocks.market.mockReturnValue({
    data: new Map([['NSE_INDEX:NIFTY', { data: { ltp: 107, timestamp: Date.now() } }]]),
    isConnected: true,
  })
  view.rerender(content('NIFTY quote'))
  expect(mocks.series[0].setData).toHaveBeenCalledTimes(writes)
  fireEvent.click(screen.getByRole('button', { name: 'Today' }))
  expect(mocks.series[0].setData.mock.calls.at(-1)?.[0].at(-1).close).toBe(107)
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-11' } })
  fireEvent.input(screen.getByLabelText('To date IST'), { target: { value: '2026-10-11' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Replay charts' })).toBeEnabled())
  expect(mocks.series[0].setData.mock.calls.at(-1)?.[0]).toHaveLength(0)
  expect(screen.getByLabelText('Candle prices')).toHaveTextContent('No candles for 2026-10-11')
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(screen.getByLabelText('Replay message')).toHaveTextContent(
    'No replay available for 2026-10-11'
  )
  view.unmount()
})

it('follows the IST date rollover unless a historical date was explicitly selected', async () => {
  vi.mocked(scalpingApi.getHistory).mockImplementation(
    async (_symbol, _exchange, _interval, date) => ({
      ...history,
      candles: date
        ? history.candles.map((b) => ({
            ...b,
            time: b.time + (Date.parse(date) - Date.parse('2026-10-15')) / 1000,
          }))
        : [
            ...history.candles.map((b) => ({ ...b, time: b.time - 86400 })),
            ...history.candles,
            ...history.candles.map((b) => ({ ...b, time: b.time + 86400 })),
          ],
    })
  )
  const view = mount()
  await waitFor(() => expect(screen.getByText(/24 candles/)).toBeVisible())
  vi.mocked(Date.now).mockReturnValue(Date.UTC(2026, 9, 15, 18, 31))
  await waitFor(() => expect(screen.getByLabelText('From date IST')).toHaveValue('2026-10-16'), {
    timeout: 2000,
  })
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-14' } })
  fireEvent.input(screen.getByLabelText('To date IST'), { target: { value: '2026-10-14' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Replay charts' })).toBeEnabled())
  vi.mocked(Date.now).mockReturnValue(Date.UTC(2026, 9, 16, 18, 31))
  await waitFor(
    () => expect(screen.getByLabelText('From date IST')).toHaveAttribute('max', '2026-10-17'),
    { timeout: 2000 }
  )
  expect(screen.getByLabelText('From date IST')).toHaveValue('2026-10-14')
  expect(mocks.series[0].setData.mock.calls.at(-1)?.[0]).toHaveLength(24)
  view.unmount()
})

it('loads both dates beyond the default lookback and replays only the applied range', async () => {
  vi.mocked(neoReportsApi.chart).mockResolvedValue({ ...history, candles: [] })
  vi.mocked(scalpingApi.getHistory).mockImplementation(
    async (_symbol, _exchange, _interval, date) =>
      date
        ? {
            ...history,
            date,
            candles: history.candles.map((b) => ({
              ...b,
              time: b.time + (Date.parse(date) - Date.parse('2026-10-15')) / 1000,
            })),
          }
        : history
  )
  const view = mount()
  await waitFor(() => expect(screen.getByText(/24 candles/)).toBeVisible())
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-12' } })
  fireEvent.input(screen.getByLabelText('To date IST'), { target: { value: '2026-10-13' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  await waitFor(() => expect(screen.getByText(/48 candles/)).toBeVisible())
  expect(scalpingApi.getHistory).toHaveBeenCalledWith('NIFTY', 'NSE_INDEX', '15m', '2026-10-12')
  expect(scalpingApi.getHistory).toHaveBeenCalledWith('NIFTY', 'NSE_INDEX', '15m', '2026-10-13')
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(screen.getByLabelText('Replay time')).toHaveTextContent('12 Oct, 09:30 IST · 1/48')
  expect(screen.getByLabelText('Replay start time IST')).toHaveAttribute('max', '2026-10-13T15:15')
  const values = mocks.series[0].setData.mock.calls.at(-1)?.[0]
  expect(values).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: 'Today' }))
  expect(screen.getByLabelText('From date IST')).toHaveValue('2026-10-15')
  expect(screen.getByLabelText('To date IST')).toHaveValue('2026-10-15')
  expect(screen.getByText(/24 candles/)).toBeVisible()
  view.unmount()
})

it('shows a valid custom range even if the default recent-history request fails', async () => {
  vi.mocked(scalpingApi.getHistory).mockImplementation(
    async (_symbol, _exchange, _interval, date) => {
      if (!date) throw Error('Recent history unavailable')
      return {
        ...history,
        date,
        candles: history.candles.map((b) => ({
          ...b,
          time: b.time + (Date.parse(date) - Date.parse('2026-10-15')) / 1000,
        })),
      }
    }
  )
  const view = mount()
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-12' } })
  fireEvent.input(screen.getByLabelText('To date IST'), { target: { value: '2026-10-13' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  await waitFor(() => expect(screen.getByText(/48 candles/)).toBeVisible())
  expect(screen.getByRole('button', { name: 'Replay charts' })).toBeEnabled()
  view.unmount()
})

it('reuses already loaded session candles without repeating a failing broker day request', async () => {
  const previous = history.candles.map((b) => ({ ...b, time: b.time - 86400 }))
  vi.mocked(scalpingApi.getHistory).mockImplementation(
    async (_symbol, _exchange, _interval, date) => {
      if (date) throw Error('Invalid observed OHLC cannot be archived')
      return { ...history, candles: [...previous, ...history.candles] }
    }
  )
  const view = mount()
  await waitFor(() => expect(screen.getByText(/24 candles/)).toBeVisible())
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-14' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  await waitFor(() => expect(screen.getByText(/48 candles/)).toBeVisible())
  expect(vi.mocked(scalpingApi.getHistory).mock.calls.every((call) => !call[3])).toBe(true)
  expect(screen.getByRole('button', { name: 'Replay charts' })).toBeEnabled()
  view.unmount()
})
