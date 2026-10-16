import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useThemeStore } from '@/stores/themeStore'
import { ScalpingCharts } from './ScalpingCharts'

// Canvas is the external boundary: keep the real terminal/chart components and
// observe whether account-only updates replace chart overlays or the viewport.
const chartIO = vi.hoisted(() => ({
  priceLine: vi.fn(() => ({})),
  removeLine: vi.fn(),
  markers: vi.fn(() => ({ detach: vi.fn() })),
  range: vi.fn(),
}))
vi.mock('lightweight-charts', async (load) => ({
  ...(await load<typeof import('lightweight-charts')>()),
  createSeriesMarkers: chartIO.markers,
  createChart: () => {
    const scale = { applyOptions: vi.fn() }
    const timeScale = {
      subscribeVisibleLogicalRangeChange: vi.fn(),
      getVisibleLogicalRange: () => ({ from: 0, to: 30 }),
      setVisibleLogicalRange: chartIO.range,
      scrollToPosition: vi.fn(),
    }
    return {
      addSeries: () => ({
        applyOptions: vi.fn(),
        priceScale: () => scale,
        createPriceLine: chartIO.priceLine,
        removePriceLine: chartIO.removeLine,
        priceToCoordinate: () => 50,
        setData: vi.fn(),
        update: vi.fn(),
      }),
      panes: () => [{ setHeight: vi.fn() }, { setHeight: vi.fn() }],
      timeScale: () => timeScale,
      priceScale: () => scale,
      applyOptions: vi.fn(),
      subscribeCrosshairMove: vi.fn(),
      remove: vi.fn(),
    }
  },
}))
vi.mock('@/api/admin', () => ({
  adminApi: {
    checkTimings: async (date: string) => ({
      date,
      timings: [0, 6].includes(new Date(`${date}T00:00Z`).getUTCDay())
        ? []
        : [
            { exchange: 'NFO', start_time: '09:15', end_time: '15:40' },
            { exchange: 'NSE', start_time: '09:15', end_time: '15:30' },
          ],
    }),
  },
}))
vi.mock('@/hooks/useMarketData', () => ({
  useMarketData: () => ({ data: new Map() }),
}))
vi.mock('@/api/scalping', () => ({
  scalpingApi: { getHistory: async () => ({ status: 'success', candles: [] }) },
}))

const ce = { symbol: 'NIFTY19OCT2622600CE', lotsize: 65, tick_size: 0.05, ltp: 144.2 }
const pe = { symbol: 'NIFTY19OCT2622600PE', lotsize: 65, tick_size: 0.05, ltp: 131.75 }
const props = {
  ce,
  pe,
  underlying: 'NIFTY',
  expiry: '19OCT26',
  strike: 22600,
  exchange: 'NFO',
  indexExchange: 'NSE_INDEX',
  interval: '1m',
  onIntervalChange: vi.fn(),
  selected: ce.symbol,
  select: vi.fn(),
  mode: 'live' as const,
  trades: [],
  indexLevels: [{ price: 22600, title: 'Support', color: 'blue' }],
  ceLevels: [{ price: 144.2, title: 'Entry', color: 'blue' }],
  fills: [{ symbol: ce.symbol, epoch: 1792036200, action: 'BUY', average_price: 144.2 }],
}

describe('Partial terminal refresh', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-16T10:00:30+05:30'))
    useThemeStore.setState({ appMode: 'live', mode: 'light' })
    vi.clearAllMocks()
  })
  afterEach(() => vi.useRealTimers())

  it('updates option prices without replacing unchanged chart lines, fills or viewport', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    const view = render(<ScalpingCharts {...props} />, {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    })
    await act(async () => vi.advanceTimersByTimeAsync(1))
    const lines = chartIO.priceLine.mock.calls.length
    const markers = chartIO.markers.mock.calls.length
    const chart = screen.getByRole('region', { name: `${ce.symbol} 1m indicator chart` })

    // A new account snapshot and a changed CE quote must not redraw the chart.
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    view.rerender(<ScalpingCharts {...props} ce={{ ...ce, ltp: 145.5 }} trades={[]} />)
    expect(screen.getByText('₹145.50')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: `${ce.symbol} 1m indicator chart` })).toBe(chart)
    expect(chartIO.priceLine).toHaveBeenCalledTimes(lines)
    expect(chartIO.markers).toHaveBeenCalledTimes(markers)
    expect(chartIO.range).not.toHaveBeenCalled()

    // An actual price-level edit still updates the overlay on the same chart.
    view.rerender(
      <ScalpingCharts {...props} ceLevels={[{ price: 146, title: 'Entry', color: 'blue' }]} />
    )
    expect(chartIO.priceLine).toHaveBeenCalledWith(expect.objectContaining({ price: 146 }))
    expect(screen.getByRole('region', { name: `${ce.symbol} 1m indicator chart` })).toBe(chart)
    fireEvent.click(screen.getByRole('button', { name: 'CE and PE charts' }))
    expect(screen.queryByRole('group', { name: 'Index chart panel' })).not.toBeInTheDocument()
  })
})
