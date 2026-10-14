import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, it, vi } from 'vitest'
import { NeoTradingViewWorkspace } from './NeoTradingViewWorkspace'
import { scalpingApi } from '@/api/scalping'
vi.mock('@/api/scalping', () => ({
  scalpingApi: {
    getHistory: vi.fn(async (symbol, exchange, interval) => ({
      status: 'success',
      symbol,
      exchange,
      interval,
      candles: [{ time: 1791863100 + 19800, open: 100, high: 101, low: 99, close: 100, volume: 0 }],
    })),
  },
}))
vi.mock('@/components/layout/Navbar', () => ({ Navbar: () => null }))
vi.mock('@/components/scalping/NeoStrategyControls', () => ({
  NeoStrategyControls: () => <div>Automation controls</div>,
}))
vi.mock('./NeoStrategyResearch', () => ({ NeoStrategyResearch: () => null }))
vi.mock('./NeoMarketChart', () => ({
  NeoMarketChart: (p: { symbol: string; interval: string }) => (
    <div data-testid="actual-chart">
      {p.symbol} {p.interval}
    </div>
  ),
}))
vi.mock('./NeoTradingTools', () => ({
  NeoTradingTools: (p: {
    target: () => { loadSymbol: (v: { symbol: string; exchange: string }) => Promise<void> }
  }) => (
    <button
      type="button"
      onClick={() => p.target().loadSymbol({ symbol: 'NIFTY_TEST_CE', exchange: 'NFO' })}
    >
      Select CE
    </button>
  ),
}))
it('loads selected timeframes and retains a manually selected option through timeframe changes', async () => {
  render(
    <MemoryRouter>
      <NeoTradingViewWorkspace />
    </MemoryRouter>
  )
  await waitFor(() =>
    expect(scalpingApi.getHistory).toHaveBeenCalledWith('NIFTY', 'NSE_INDEX', '15m')
  )
  await waitFor(() => expect(screen.getByLabelText('Timeframe')).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Select CE' }))
  await waitFor(() =>
    expect(screen.getByTestId('actual-chart')).toHaveTextContent('NIFTY_TEST_CE 15m')
  )
  fireEvent.change(screen.getByLabelText('Timeframe'), { target: { value: '5m' } })
  await waitFor(() =>
    expect(scalpingApi.getHistory).toHaveBeenCalledWith('NIFTY_TEST_CE', 'NFO', '5m')
  )
  expect(screen.getByTestId('actual-chart')).toHaveTextContent('NIFTY_TEST_CE 5m')
})
