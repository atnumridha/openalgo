import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { scalpingApi } from '@/api/scalping'
import { NeoMarketChart } from './NeoMarketChart'

const mocks = vi.hoisted(() => ({
  series: [] as Array<{ setData: ReturnType<typeof vi.fn> }>,
  remove: vi.fn(),
  createLine: vi.fn(() => ({})),
  range: vi.fn(),
}))
vi.mock('@/hooks/useMarketData', () => ({
  useMarketData: () => ({ data: new Map(), isConnected: true }),
}))
vi.mock('@/api/neoDesk', () => ({
  neoDeskApi: {
    chart: async () => ({ overlays: [{ label: 'SL / trail', price: '95', run_id: 1 }] }),
    state: async () => ({ profile: 'orb_trail' }),
  },
}))
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
  date: '2026-10-13',
  candles: Array.from({ length: 30 }, (_, i) => ({
    time: 1791863100 + 19800 + i * 900,
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
  mocks.series.length = 0
  localStorage.clear()
  vi.mocked(scalpingApi.getHistory).mockResolvedValue(history)
})
it('renders real normalized broker candles, owned stops and studies through TradingView and cleans up', async () => {
  const view = mount()
  await waitFor(() => expect(mocks.series[0]?.setData).toHaveBeenCalled())
  expect(mocks.series[0].setData.mock.calls.at(-1)?.[0][0].time).toBe(1791863100)
  expect(mocks.createLine).toHaveBeenCalledWith(
    expect.objectContaining({ price: 95, title: 'SL / trail' })
  )
  expect(screen.getByLabelText('RSI 14')).toBeChecked()
  expect(screen.getByLabelText('Candle prices')).toHaveTextContent('O 100.00')
  expect(screen.getByText(/30 candles/)).toBeVisible()
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
