import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { it, expect, vi } from 'vitest'
import { NeoMarketChart } from './NeoMarketChart'
vi.mock('@/hooks/useMarketData', () => ({
  useMarketData: () => ({ data: new Map(), isConnected: true }),
}))
vi.mock('@/api/neoDesk', () => ({ neoDeskApi: { chart: async () => ({ overlays: [] }) } }))
vi.mock('@/api/scalping', () => ({
  scalpingApi: { getHistory: async () => ({ status: 'success', candles: [] }) },
}))
vi.mock('@/lib/trading/customIndicators', () => ({ loadCustomIndicators: async () => {} }))
vi.mock('@/lib/trading/chartTheme', () => ({ buildChartTheme: () => ({}) }))
vi.mock('openalgo-charts/indicators', () => ({}))
vi.mock('openalgo-charts', () => ({
  createChart: () => ({
    setDataContext: () => {},
    addSeries: () => ({ setData: () => {}, priceScale: () => ({ setOptions: () => {} }) }),
    fitContent: () => {},
    destroy: () => {},
    addIndicator: (id: string) => {
      if (id === 'neo-donchian') throw Error('descriptor missing')
      return { id }
    },
    removeIndicator: () => {},
  }),
}))
it('keeps the chart and controls usable when a custom indicator is unavailable', async () => {
  localStorage.removeItem('neo.chart.indicators')
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" />
    </QueryClientProvider>
  )
  expect(await screen.findByRole('alert')).toHaveTextContent('neo-donchian')
  expect(screen.getByText(/actual contract prices/)).toBeVisible()
  expect(screen.getByLabelText('RSI 14')).toBeEnabled()
})
