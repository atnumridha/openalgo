import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, it, vi } from 'vitest'
import { NeoTradingViewWorkspace } from './NeoTradingViewWorkspace'
import { scalpingApi } from '@/api/scalping'
import { readDeltaHistory } from '../chart-toolkit/deltaFeed'
vi.mock('../chart-toolkit/deltaFeed', () => ({
  readDeltaHistory: vi.fn(async (symbol, interval) => ({
    status: 'success',
    symbol,
    exchange: 'DELTA',
    interval,
    candles: [{ time: 1791863100 + 19800, open: 100, high: 101, low: 99, close: 100, volume: 100 }],
  })),
}))
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
vi.mock('@/components/layout/Navbar', () => ({
  Navbar: () => <nav aria-label="OpenAlgo navigation">OpenAlgo navigation</nav>,
}))
vi.mock('@/components/scalping/NeoStrategyControls', () => ({
  NeoStrategyControls: () => <div>Automation controls</div>,
}))
vi.mock('./NeoStrategyResearch', () => ({ NeoStrategyResearch: () => null }))
vi.mock('./NeoMarketChart', () => ({
  NeoMarketChart: (p: { symbol: string; interval: string; studies: string[] }) => (
    <div data-testid="actual-chart">
      {p.symbol} {p.interval} <span data-testid="active-studies">{p.studies.join(',')}</span>
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
function mountWorkspace() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <NeoTradingViewWorkspace />
      </MemoryRouter>
    </QueryClientProvider>
  )
}
it('loads selected timeframes and retains a manually selected option through timeframe changes', async () => {
  mountWorkspace()
  await waitFor(() =>
    expect(scalpingApi.getHistory).toHaveBeenCalledWith(
      'NIFTY',
      'NSE_INDEX',
      '15m',
      undefined,
      expect.objectContaining({ timeoutMs: 12000 })
    )
  )
  await waitFor(() => expect(screen.getByLabelText('Timeframe')).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Options' }))
  fireEvent.click(screen.getByRole('button', { name: 'Select CE' }))
  await waitFor(() =>
    expect(screen.getByTestId('actual-chart')).toHaveTextContent('NIFTY_TEST_CE 15m')
  )
  fireEvent.change(screen.getByLabelText('Timeframe'), { target: { value: '5m' } })
  await waitFor(() =>
    expect(scalpingApi.getHistory).toHaveBeenCalledWith(
      'NIFTY_TEST_CE',
      'NFO',
      '5m',
      undefined,
      expect.objectContaining({ timeoutMs: 12000 })
    )
  )
  expect(screen.getByTestId('actual-chart')).toHaveTextContent('NIFTY_TEST_CE 5m')
})

it('switches index data to the BSE exchange for SENSEX while retaining the selected chart timeframe', async () => {
  mountWorkspace()
  await waitFor(() => expect(screen.getByLabelText('Market')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Market'), { target: { value: 'SENSEX' } })
  await waitFor(() =>
    expect(scalpingApi.getHistory).toHaveBeenCalledWith(
      'SENSEX',
      'BSE_INDEX',
      '15m',
      undefined,
      expect.objectContaining({ timeoutMs: 12000 })
    )
  )
  await waitFor(() => expect(screen.getByLabelText('Market')).toHaveValue('SENSEX'))
  fireEvent.change(screen.getByLabelText('Timeframe'), { target: { value: '1h' } })
  await waitFor(() =>
    expect(scalpingApi.getHistory).toHaveBeenCalledWith(
      'SENSEX',
      'BSE_INDEX',
      '1h',
      undefined,
      expect.objectContaining({ timeoutMs: 12000 })
    )
  )
})

it('routes BTC to the public Delta history adapter instead of the Kotak index feed', async () => {
  mountWorkspace()
  await waitFor(() => expect(screen.getByLabelText('Market')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Market'), { target: { value: 'BTCUSD' } })
  await waitFor(() =>
    expect(readDeltaHistory).toHaveBeenCalledWith(
      'BTCUSD',
      '15m',
      undefined,
      expect.any(AbortSignal)
    )
  )
  expect(scalpingApi.getHistory).not.toHaveBeenCalledWith('BTCUSD', 'NSE_INDEX', '15m')
  await waitFor(() => expect(screen.getByTestId('actual-chart')).toHaveTextContent('BTCUSD 15m'))
})

it('fits the chart within OpenAlgo and keeps trading controls behind the workspace view', async () => {
  mountWorkspace()
  await waitFor(() => expect(screen.getByLabelText('Timeframe')).toBeEnabled())
  expect(screen.getByRole('main', { name: 'OpenAlgo chart workspace' })).toBeInTheDocument()
  expect(screen.getByRole('navigation', { name: 'OpenAlgo navigation' })).toBeVisible()
  expect(screen.queryByLabelText('Strategy workspace')).not.toBeInTheDocument()
  fireEvent.click(screen.getByText('More'))
  fireEvent.click(screen.getByRole('button', { name: 'Workspace' }))
  expect(screen.getByLabelText('Strategy workspace')).toBeInTheDocument()
})

beforeEach(() => {
  localStorage.clear()
  vi.mocked(scalpingApi.getHistory)
    .mockReset()
    .mockImplementation(async (symbol, exchange, interval) => ({
      status: 'success',
      symbol,
      exchange,
      interval,
      candles: [{ time: 1791863100 + 19800, open: 100, high: 101, low: 99, close: 100, volume: 0 }],
    }))
  vi.mocked(readDeltaHistory)
    .mockReset()
    .mockImplementation(async (symbol, interval) => ({
      status: 'success',
      symbol,
      exchange: 'DELTA',
      interval,
      candles: [
        { time: 1791863100 + 19800, open: 100, high: 101, low: 99, close: 100, volume: 100 },
      ],
    }))
})
it('does not restore the older unlabeled overlays into the EMA 9/15 toolkit view', async () => {
  localStorage.setItem('neo.chart.toolkit.version', '1')
  localStorage.setItem(
    'neo.native.chart.indicators',
    JSON.stringify(['neo-toolkit', 'neo-donchian', 'rsi'])
  )
  mountWorkspace()
  await waitFor(() => expect(screen.getByTestId('active-studies')).toHaveTextContent('neo-toolkit'))
  expect(screen.getByTestId('active-studies')).not.toHaveTextContent('neo-donchian')
  expect(screen.getByTestId('active-studies')).not.toHaveTextContent('rsi')
})
it('shows a newly chosen market immediately while its candle request is still pending', async () => {
  mountWorkspace()
  await waitFor(() => expect(screen.getByLabelText('Market')).toHaveValue('NIFTY'))
  const pending = new Promise<never>(() => {})
  vi.mocked(scalpingApi.getHistory).mockImplementationOnce(() => pending)
  fireEvent.change(screen.getByLabelText('Market'), { target: { value: 'SENSEX' } })
  expect(screen.getByLabelText('Market')).toHaveValue('SENSEX')
  expect(screen.getByTestId('actual-chart')).toHaveTextContent('SENSEX 15m')
})

it('hides navigation only during explicitly requested browser fullscreen and restores it on exit', async () => {
  mountWorkspace()
  await waitFor(() => expect(screen.queryByText('Loading candles…')).not.toBeInTheDocument())
  const main = screen.getByRole('main', { name: 'OpenAlgo chart workspace' })
  const request = vi.fn(async () => {})
  Object.defineProperty(main, 'requestFullscreen', { configurable: true, value: request })
  fireEvent.click(screen.getByRole('button', { name: 'Full screen' }))
  expect(request).toHaveBeenCalledOnce()
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: main })
  act(() => {
    document.dispatchEvent(new Event('fullscreenchange'))
  })
  expect(screen.queryByRole('navigation', { name: 'OpenAlgo navigation' })).not.toBeInTheDocument()
  expect(screen.getByRole('main', { name: 'Full-screen chart workspace' })).toBeInTheDocument()
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null })
  act(() => {
    document.dispatchEvent(new Event('fullscreenchange'))
  })
  expect(screen.getByRole('navigation', { name: 'OpenAlgo navigation' })).toBeVisible()
})

it('ends a slow history request with a clear retry message and does not automatically repeat it', async () => {
  vi.mocked(scalpingApi.getHistory).mockRejectedValueOnce(
    Object.assign(new Error('timeout'), { code: 'ECONNABORTED' })
  )
  mountWorkspace()
  expect(await screen.findByRole('alert')).toHaveTextContent('Broker candles are delayed')
  expect(screen.getByRole('button', { name: 'Retry chart' })).toBeEnabled()
  expect(scalpingApi.getHistory).toHaveBeenCalledTimes(1)
  expect(scalpingApi.getHistory).toHaveBeenCalledWith(
    'NIFTY',
    'NSE_INDEX',
    '15m',
    undefined,
    expect.objectContaining({ timeoutMs: 12000, signal: expect.any(AbortSignal) })
  )
})

it('keeps the selected timeframe intact while the loading timer advances', async () => {
  vi.mocked(scalpingApi.getHistory).mockImplementationOnce(() => new Promise<never>(() => {}))
  mountWorkspace()
  expect(screen.getByLabelText('Timeframe')).toHaveValue('15m')
  await waitFor(() => expect(screen.getByText('Loading candles · 1s')).toBeVisible(), {
    timeout: 2000,
  })
  expect(screen.getByLabelText('Timeframe')).toHaveValue('15m')
  expect(screen.getByTestId('actual-chart')).toHaveTextContent('NIFTY 15m')
  expect(scalpingApi.getHistory).toHaveBeenCalledTimes(1)
})

it('restores the optional BB + Chikou study alongside the existing toolkit', async () => {
  localStorage.setItem('neo.chart.toolkit.version', '2')
  localStorage.setItem('neo.native.chart.indicators', JSON.stringify(['neo-toolkit', 'bb-chikou']))
  mountWorkspace()
  await waitFor(() => expect(screen.getByTestId('active-studies')).toHaveTextContent('bb-chikou'))
  expect(JSON.parse(localStorage.getItem('neo.native.chart.indicators')!)).toContain('bb-chikou')
})


it('restores all nine independent choices alongside the separate BB + Chikou choice', async () => {
  localStorage.setItem('neo.chart.toolkit.version', '2')
  const ids = ['rsi','bb','iv','imi','mfi','pcr','oi','macd','ma'].map(k => `nine-${k}`)
  localStorage.setItem('neo.native.chart.indicators', JSON.stringify([...ids,'bb-chikou']))
  mountWorkspace()
  await waitFor(() => expect(screen.getByTestId('active-studies')).toHaveTextContent('nine-ma'))
  for (const id of [...ids,'bb-chikou']) expect(screen.getByTestId('active-studies')).toHaveTextContent(id)
})
