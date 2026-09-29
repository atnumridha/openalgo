import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { StrategyLiveChart } from './StrategyLiveChart'

vi.mock('@/hooks/useMarketData', () => ({
  useMarketData: () => ({ data: new Map() }),
}))
vi.mock('@/api/scalping', () => ({
  scalpingApi: { getHistory: vi.fn(() => Promise.resolve({ status: 'success', candles: [] })) },
}))
vi.mock('@/api/strategy_module', () => ({
  listEvents: vi.fn(() => Promise.resolve([])),
}))
vi.mock('lightweight-charts', () => ({
  ColorType: { Solid: 'solid' },
  CrosshairMode: { Normal: 0 },
  LineStyle: { Solid: 0, Dashed: 1 },
  CandlestickSeries: 'candles',
  HistogramSeries: 'hist',
  LineSeries: 'line',
  createChart: () => ({
    addSeries: () => ({
      setData: vi.fn(),
      update: vi.fn(),
      priceScale: () => ({ applyOptions: vi.fn() }),
      createPriceLine: vi.fn(() => ({})),
      removePriceLine: vi.fn(),
    }),
    timeScale: () => ({
      fitContent: vi.fn(),
      getVisibleLogicalRange: vi.fn(),
      setVisibleLogicalRange: vi.fn(),
    }),
    priceScale: () => ({ applyOptions: vi.fn() }),
    applyOptions: vi.fn(),
    subscribeCrosshairMove: vi.fn(),
    removeSeries: vi.fn(),
    remove: vi.fn(),
  }),
  createSeriesMarkers: vi.fn(() => ({ setMarkers: vi.fn() })),
}))

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('StrategyLiveChart', () => {
  it('renders for a strategy with an underlying', () => {
    wrap(
      <StrategyLiveChart
        strategyId={13}
        underlying="NIFTY"
        underlyingExchange="NSE_INDEX"
        scalpProfile="ema915"
      />
    )
    expect(screen.getByTestId('strategy-live-chart')).toBeInTheDocument()
  })

  it('does not invent a chart when the underlying is missing', () => {
    wrap(<StrategyLiveChart strategyId={13} underlying="" underlyingExchange="NSE_INDEX" />)
    expect(screen.getByText(/no chartable underlying/i)).toBeInTheDocument()
  })
})
