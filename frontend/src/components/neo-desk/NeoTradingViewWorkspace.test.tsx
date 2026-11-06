import { useLiveQuote } from '@/hooks/useLiveQuote'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useNavigate, useLocation } from 'react-router'
import { beforeEach, expect, it, vi } from 'vitest'
import { NeoTradingViewWorkspace, searchChartSymbols } from './NeoTradingViewWorkspace'
import { scalpingApi } from '@/api/scalping'
import { readDeltaHistory } from '../chart-toolkit/deltaFeed'
import { readDeltaProducts } from '../chart-toolkit/deltaProducts'
import { webClient } from '@/api/client'
vi.mock('@/api/client', () => ({ webClient: { get: vi.fn(async () => ({ data: { data: [] } })) } }))
vi.mock('../chart-toolkit/deltaProducts', () => ({
  readDeltaProducts: vi.fn(async () => [
    { id: 1, symbol: 'SOLUSD', name: 'Solana perpetual', tick_size: 0.01 },
    { id: 2, symbol: 'JUPUSD', name: 'Jupiter perpetual', tick_size: 0.0001 },
  ]),
}))
vi.mock('@/hooks/useLiveQuote', () => ({
  useLiveQuote: vi.fn(() => ({
    data: { ltp: 23120, close: 23000 },
    isLive: true,
    dataSource: 'websocket',
  })),
}))
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
    historyPending?: boolean
    target: () => { loadSymbol: (v: { symbol: string; exchange: string }) => Promise<void> }
  }) => (
    <>
      <output aria-label="Background RSI state">{p.historyPending ? 'paused' : 'ready'}</output>
      <button
        type="button"
        onClick={() => p.target().loadSymbol({ symbol: 'NIFTY_TEST_CE', exchange: 'NFO' })}
      >
        Select CE
      </button>
    </>
  ),
}))
vi.mock('@/components/trading/SymbolSearchDialog', () => ({
  SymbolSearchDialog: (p: { onPick: (v: { symbol: string; exchange: string }) => void }) => (
    <div role="dialog" aria-label="Symbol search">
      <button type="button" onClick={() => p.onPick({ symbol: 'RELIANCE', exchange: 'NSE' })}>
        Choose RELIANCE
      </button>
      <button type="button" onClick={() => p.onPick({ symbol: 'SOLUSD', exchange: 'DELTA' })}>
        Choose SOLUSD
      </button>
    </div>
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
it('opens Options separately from the chart and closes it after choosing a contract', async () => {
  mountWorkspace()
  await waitFor(() => expect(screen.getByLabelText('Timeframe')).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Options' }))
  const drawer = await screen.findByRole('dialog', { name: 'Chart options' })
  expect(drawer).toBeVisible()
  expect(drawer).not.toContainElement(screen.getByTestId('actual-chart'))
  fireEvent.click(within(drawer).getByRole('button', { name: 'Select CE' }))
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: 'Chart options' })).not.toBeInTheDocument()
  )
  expect(screen.getByTestId('actual-chart')).toHaveTextContent('NIFTY_TEST_CE')
  expect(screen.getByRole('button', { name: 'Options' })).toHaveFocus()
  fireEvent.click(screen.getByRole('button', { name: 'Options' }))
  fireEvent.keyDown(screen.getByRole('dialog', { name: 'Chart options' }), { key: 'Escape' })
  expect(screen.queryByRole('dialog', { name: 'Chart options' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Options' })).toHaveFocus()
})
it('loads selected timeframes and retains a manually selected option through timeframe changes', async () => {
  mountWorkspace()
  await waitFor(() =>
    expect(scalpingApi.getHistory).toHaveBeenCalledWith(
      'NIFTY',
      'NSE_INDEX',
      '15m',
      undefined,
      expect.objectContaining({ timeoutMs: 30000 })
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
      expect.objectContaining({ timeoutMs: 30000 })
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
      expect.objectContaining({ timeoutMs: 30000 })
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
      expect.objectContaining({ timeoutMs: 30000 })
    )
  )
})

it.each([
  'BTCUSD',
  'XAUTUSD',
])('routes %s to the public Delta history adapter instead of the Kotak index feed', async (symbol) => {
  mountWorkspace()
  await waitFor(() => expect(screen.getByLabelText('Market')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Market'), { target: { value: symbol } })
  await waitFor(() =>
    expect(readDeltaHistory).toHaveBeenCalledWith(symbol, '15m', undefined, expect.any(AbortSignal))
  )
  expect(scalpingApi.getHistory).not.toHaveBeenCalledWith(symbol, 'NSE_INDEX', '15m')
  await waitFor(() => expect(screen.getByTestId('actual-chart')).toHaveTextContent(`${symbol} 15m`))
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

it('shows a clear error before its scheduled automatic retry', async () => {
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
    expect.objectContaining({ timeoutMs: 30000, signal: expect.any(AbortSignal) })
  )
})

it('recovers a transient history failure automatically for the same contract and timeframe', async () => {
  vi.useFakeTimers()
  vi.mocked(scalpingApi.getHistory).mockRejectedValueOnce(
    Object.assign(new Error('timeout'), { code: 'ECONNABORTED' })
  )
  const view = mountWorkspace()
  try {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10)
    })
    expect(screen.getByRole('alert')).toHaveTextContent('Broker candles are delayed')
    expect(screen.getByLabelText('Background RSI state')).toHaveTextContent('paused')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000)
    })
    expect(scalpingApi.getHistory).toHaveBeenCalledTimes(2)
    expect(scalpingApi.getHistory).toHaveBeenLastCalledWith(
      'NIFTY',
      'NSE_INDEX',
      '15m',
      undefined,
      expect.anything()
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Background RSI state')).toHaveTextContent('ready')
  } finally {
    view.unmount()
    vi.useRealTimers()
  }
})

it('continues automatic recovery with a capped delay instead of requiring a manual retry', async () => {
  vi.useFakeTimers()
  vi.mocked(scalpingApi.getHistory).mockRejectedValue(
    Object.assign(new Error('Server unavailable'), { response: { status: 503 } })
  )
  const view = mountWorkspace()
  try {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10)
    })
    for (const delay of [15000, 30000, 60000, 60000])
      await act(async () => {
        await vi.advanceTimersByTimeAsync(delay)
      })
    expect(scalpingApi.getHistory).toHaveBeenCalledTimes(5)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(59000)
    })
    expect(scalpingApi.getHistory).toHaveBeenCalledTimes(5)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(scalpingApi.getHistory).toHaveBeenCalledTimes(6)
    expect(screen.getByRole('button', { name: 'Retry chart' })).toBeEnabled()
  } finally {
    view.unmount()
    vi.useRealTimers()
  }
})

it('cancels pending recovery when the selected market changes', async () => {
  vi.useFakeTimers()
  vi.mocked(scalpingApi.getHistory).mockRejectedValueOnce(
    Object.assign(new Error('timeout'), { code: 'ECONNABORTED' })
  )
  const view = mountWorkspace()
  try {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10)
    })
    fireEvent.change(screen.getByLabelText('Market'), { target: { value: 'SENSEX' } })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000)
    })
    expect(scalpingApi.getHistory).toHaveBeenCalledTimes(2)
    expect(scalpingApi.getHistory).toHaveBeenLastCalledWith(
      'SENSEX',
      'BSE_INDEX',
      '15m',
      undefined,
      expect.anything()
    )
  } finally {
    view.unmount()
    vi.useRealTimers()
  }
})

it('does not retry authentication or invalid-contract failures automatically', async () => {
  vi.useFakeTimers()
  vi.mocked(scalpingApi.getHistory).mockRejectedValue(
    Object.assign(new Error('Unauthorized'), { response: { status: 401 } })
  )
  const view = mountWorkspace()
  try {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000)
    })
    expect(scalpingApi.getHistory).toHaveBeenCalledTimes(1)
  } finally {
    view.unmount()
    vi.useRealTimers()
  }
})

it('keeps the selected timeframe intact while the loading timer advances', async () => {
  vi.useFakeTimers()
  vi.mocked(scalpingApi.getHistory).mockImplementationOnce(() => new Promise<never>(() => {}))
  const view = mountWorkspace()
  try {
    expect(screen.getByLabelText('Timeframe')).toHaveValue('15m')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(screen.getByText('Loading candles · 1s')).toBeVisible()
    expect(screen.getByLabelText('Timeframe')).toHaveValue('15m')
    expect(screen.getByTestId('actual-chart')).toHaveTextContent('NIFTY 15m')
    expect(scalpingApi.getHistory).toHaveBeenCalledTimes(1)
  } finally {
    view.unmount()
    vi.useRealTimers()
  }
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
  const ids = ['rsi', 'bb', 'iv', 'imi', 'mfi', 'pcr', 'oi', 'macd', 'ma'].map((k) => `nine-${k}`)
  localStorage.setItem('neo.native.chart.indicators', JSON.stringify([...ids, 'bb-chikou']))
  mountWorkspace()
  await waitFor(() => expect(screen.getByTestId('active-studies')).toHaveTextContent('nine-ma'))
  for (const id of [...ids, 'bb-chikou'])
    expect(screen.getByTestId('active-studies')).toHaveTextContent(id)
})

it('restores candlestick probability independently of the nine-indicator choices', async () => {
  localStorage.setItem('neo.chart.toolkit.version', '2')
  localStorage.setItem('neo.native.chart.indicators', JSON.stringify(['candle-probability']))
  mountWorkspace()
  await waitFor(() =>
    expect(screen.getByTestId('active-studies')).toHaveTextContent('candle-probability')
  )
  expect(screen.getByTestId('active-studies')).not.toHaveTextContent('nine-')
})

it('keeps the underlying index quote visible while charting premiums and follows market changes', async () => {
  mountWorkspace()
  expect(screen.getByLabelText('Selected index quote')).toHaveTextContent('NIFTY')
  expect(screen.getByLabelText('Index day change')).toHaveTextContent('+120.00 (+0.52%)')
  fireEvent.click(screen.getByRole('button', { name: 'Options' }))
  fireEvent.click(screen.getByRole('button', { name: 'Select CE' }))
  await waitFor(() => expect(screen.getByTestId('actual-chart')).toHaveTextContent('NIFTY_TEST_CE'))
  expect(screen.getByLabelText('Selected index quote')).toHaveTextContent('NIFTY')
  fireEvent.change(screen.getByLabelText('Market'), { target: { value: 'SENSEX' } })
  await waitFor(() =>
    expect(screen.getByLabelText('Selected index quote')).toHaveTextContent('SENSEX')
  )
  expect(useLiveQuote).toHaveBeenLastCalledWith('SENSEX', 'BSE_INDEX', expect.anything())
  fireEvent.change(screen.getByLabelText('Market'), { target: { value: 'BTCUSD' } })
  expect(screen.queryByLabelText('Selected index quote')).not.toBeInTheDocument()
})

it('searches a listed cash symbol and keeps it selected across timeframe changes', async () => {
  mountWorkspace()
  fireEvent.click(screen.getByRole('button', { name: 'Search any symbol' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Choose RELIANCE' }))
  await waitFor(() => expect(screen.getByTestId('actual-chart')).toHaveTextContent('RELIANCE 15m'))
  expect(screen.getByLabelText('Market')).toHaveValue('RELIANCE')
  expect(screen.queryByRole('button', { name: 'Options' })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Timeframe'), { target: { value: '5m' } })
  await waitFor(() =>
    expect(scalpingApi.getHistory).toHaveBeenCalledWith(
      'RELIANCE',
      'NSE',
      '5m',
      undefined,
      expect.anything()
    )
  )
  expect(screen.getByTestId('actual-chart')).toHaveTextContent('RELIANCE 5m')
  fireEvent.click(screen.getByRole('button', { name: 'Indicators' }))
  const toggle = await screen.findByRole('checkbox', { name: 'RSI 14' })
  fireEvent.click(toggle)
  expect(screen.getByTestId('active-studies')).toHaveTextContent('rsi')
})

it('opens a screener-selected premium directly without loading the default index first', async () => {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter
        initialEntries={[
          '/trading?symbol=NIFTY03NOV2623000PE&exchange=NFO&interval=5m&study=candle-probability&pattern=engulfing',
        ]}
      >
        <NeoTradingViewWorkspace />
      </MemoryRouter>
    </QueryClientProvider>
  )
  await waitFor(() =>
    expect(screen.getByTestId('actual-chart')).toHaveTextContent('NIFTY03NOV2623000PE 5m')
  )
  expect(screen.getByTestId('active-studies')).toHaveTextContent('candle-probability')
  expect(vi.mocked(scalpingApi.getHistory).mock.calls.some(([symbol]) => symbol === 'NIFTY')).toBe(
    false
  )
})

it('restores the exact previous chart target when navigating back from a screener-linked chart', async () => {
  function Back() {
    const navigate = useNavigate()
    return (
      <button type="button" onClick={() => navigate(-1)}>
        Previous chart
      </button>
    )
  }
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter
        initialEntries={[
          '/trading?symbol=BTCUSD&exchange=DELTA&interval=1m',
          '/trading?symbol=ETHUSD&exchange=DELTA&interval=5m',
        ]}
        initialIndex={1}
      >
        <Back />
        <NeoTradingViewWorkspace />
      </MemoryRouter>
    </QueryClientProvider>
  )
  await waitFor(() => expect(screen.getByTestId('actual-chart')).toHaveTextContent('ETHUSD 5m'))
  fireEvent.click(screen.getByText('Previous chart'))
  await waitFor(() => expect(screen.getByTestId('actual-chart')).toHaveTextContent('BTCUSD 1m'))
  expect(screen.getByLabelText('Timeframe')).toHaveValue('1m')
})

it('keeps the URL in sync with market and timeframe changes without remounting the chart', async () => {
  function Address() {
    return <output aria-label="Chart address">{useLocation().search}</output>
  }
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter
        initialEntries={['/trading?symbol=ETHUSD&exchange=DELTA&interval=5m&source=reference']}
      >
        <Address />
        <NeoTradingViewWorkspace />
      </MemoryRouter>
    </QueryClientProvider>
  )
  await waitFor(() => expect(screen.getByTestId('actual-chart')).toHaveTextContent('ETHUSD 5m'))
  const chart = screen.getByTestId('actual-chart')
  fireEvent.change(screen.getByLabelText('Market'), { target: { value: 'BTCUSD' } })
  await waitFor(() =>
    expect(screen.getByLabelText('Chart address')).toHaveTextContent('symbol=BTCUSD')
  )
  fireEvent.change(screen.getByLabelText('Timeframe'), { target: { value: '1m' } })
  await waitFor(() =>
    expect(screen.getByLabelText('Chart address')).toHaveTextContent('interval=1m')
  )
  expect(screen.getByLabelText('Chart address')).toHaveTextContent('source=reference')
  expect(screen.getByTestId('actual-chart')).toHaveTextContent('BTCUSD 1m')
  expect(screen.getByTestId('actual-chart')).toBe(chart)
})

it('searches arbitrary live Delta products and preserves broker exchange filtering', async () => {
  expect(await searchChartSymbols('sol', 'DELTA')).toEqual([
    expect.objectContaining({ symbol: 'SOLUSD', exchange: 'DELTA', name: 'Solana perpetual' }),
  ])
  expect(await searchChartSymbols('jup')).toContainEqual(
    expect.objectContaining({ symbol: 'JUPUSD', exchange: 'DELTA' })
  )
  expect(await searchChartSymbols('sol', 'NSE')).toEqual([])
  expect(webClient.get).toHaveBeenLastCalledWith(
    '/neodesk/api/chart/search',
    expect.objectContaining({ params: { query: 'sol', exchange: 'NSE' } })
  )
  expect(readDeltaProducts).toHaveBeenCalled()
})

it('selects SOL through existing search and keeps DELTA through timeframe and URL updates', async () => {
  function Address() {
    return <output aria-label="Chart address">{useLocation().search}</output>
  }
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={['/trading']}>
        <Address />
        <NeoTradingViewWorkspace />
      </MemoryRouter>
    </QueryClientProvider>
  )
  fireEvent.click(screen.getByRole('button', { name: 'Search any symbol' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Choose SOLUSD' }))
  await waitFor(() => expect(screen.getByTestId('actual-chart')).toHaveTextContent('SOLUSD 15m'))
  expect(screen.getByLabelText('Market')).toHaveValue('SOLUSD')
  expect(screen.getByLabelText('Chart address')).toHaveTextContent('exchange=DELTA')
  fireEvent.change(screen.getByLabelText('Timeframe'), { target: { value: '5m' } })
  await waitFor(() =>
    expect(readDeltaHistory).toHaveBeenCalledWith(
      'SOLUSD',
      '5m',
      undefined,
      expect.any(AbortSignal)
    )
  )
  fireEvent.click(screen.getByText('More'))
  fireEvent.click(screen.getByRole('button', { name: 'Workspace' }))
  expect(screen.getByText(/Crypto perpetuals/)).toBeInTheDocument()
})

it('restores JUP DELTA from a direct URL and preserves its venue when reselected in Market', async () => {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={['/trading?symbol=JUPUSD&exchange=DELTA&interval=1m']}>
        <NeoTradingViewWorkspace />
      </MemoryRouter>
    </QueryClientProvider>
  )
  await waitFor(() =>
    expect(readDeltaHistory).toHaveBeenCalledWith(
      'JUPUSD',
      '1m',
      undefined,
      expect.any(AbortSignal)
    )
  )
  fireEvent.change(screen.getByLabelText('Market'), { target: { value: 'JUPUSD' } })
  expect(scalpingApi.getHistory).not.toHaveBeenCalledWith(
    'JUPUSD',
    expect.anything(),
    expect.anything(),
    expect.anything(),
    expect.anything()
  )
  fireEvent.click(screen.getByText('More'))
  fireEvent.click(screen.getByRole('button', { name: 'Workspace' }))
  expect(screen.getByText(/Crypto perpetuals/)).toBeInTheDocument()
})

it('keeps broker search usable when public product discovery is unavailable', async () => {
  vi.mocked(readDeltaProducts).mockRejectedValueOnce(new Error('Public feed unavailable'))
  vi.mocked(webClient.get).mockResolvedValueOnce({
    data: { data: [{ symbol: 'RELIANCE', exchange: 'NSE' }] },
  })
  expect(await searchChartSymbols('RELIANCE')).toEqual([{ symbol: 'RELIANCE', exchange: 'NSE' }])
})

it('migrates Delta volume and RSI defaults once, preserves manual off, without adding Delta-only defaults to Nifty', async () => {
  localStorage.setItem('neo.chart.toolkit.version', '2')
  localStorage.setItem('neo.native.chart.indicators', '[]')
  const view = mountWorkspace()
  expect(screen.getByTestId('active-studies')).toHaveTextContent('ema-9-15')
  fireEvent.click(screen.getByRole('button', { name: 'Search any symbol' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Choose SOLUSD' }))
  await waitFor(() => expect(screen.getByTestId('active-studies')).toHaveTextContent('volume'))
  expect(screen.getByTestId('active-studies')).toHaveTextContent('rsi')
  fireEvent.click(screen.getByRole('button', { name: 'Indicators' }))
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Volume' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'RSI 14' }))
  expect(screen.getByTestId('active-studies')).not.toHaveTextContent('volume')
  expect(screen.getByTestId('active-studies')).not.toHaveTextContent('rsi')
  expect(JSON.parse(localStorage.getItem('neo.native.chart.indicators')!)).toEqual(['ema-9-15','video-strategy-guide'])
  view.unmount()
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={['/trading?symbol=BTCUSD&exchange=DELTA&interval=1m']}>
        <NeoTradingViewWorkspace />
      </MemoryRouter>
    </QueryClientProvider>
  )
  await waitFor(() => expect(screen.getByTestId('actual-chart')).toHaveTextContent('BTCUSD'))
  expect(screen.getByTestId('active-studies')).not.toHaveTextContent('volume')
  expect(screen.getByTestId('active-studies')).not.toHaveTextContent('rsi')
})

it.each([
  '/trading?symbol=NIFTY&exchange=NSE_INDEX&interval=15m',
  '/trading?symbol=BTCUSD&exchange=DELTA&interval=15m',
])('starts with the candle-pattern indicator on and remembers a later manual off: %s', async (url) => {
  const open = () =>
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <MemoryRouter initialEntries={[url]}>
          <NeoTradingViewWorkspace />
        </MemoryRouter>
      </QueryClientProvider>
    )
  const view = open()
  fireEvent.click(screen.getByRole('button', { name: 'Indicators' }))
  const checkbox = await screen.findByRole('checkbox', { name: /Candle patterns/ })
  expect(checkbox).toBeChecked()
  expect(
    screen
      .getByTestId('active-studies')
      .textContent!.split(',')
      .filter((id) => id === 'candle-patterns')
  ).toHaveLength(1)
  fireEvent.click(checkbox)
  expect(checkbox).not.toBeChecked()
  expect(screen.getByTestId('active-studies')).not.toHaveTextContent('candle-patterns')
  view.unmount()
  const restored = open()
  fireEvent.click(screen.getByRole('button', { name: 'Indicators' }))
  expect(await screen.findByRole('checkbox', { name: /Candle patterns/ })).not.toBeChecked()
  restored.unmount()
})

it.each([
  ['NIFTY', 'NSE_INDEX'], ['SENSEX', 'BSE_INDEX'], ['RELIANCE', 'NSE'],
  ['ETHUSD', 'DELTA'], ['XAUTUSD', 'DELTA'], ['SOLUSD', 'DELTA'],
])('enables the three-EMA study on %s charts by default', async (symbol, exchange) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(<QueryClientProvider client={client}>
    <MemoryRouter initialEntries={[`/trading?symbol=${symbol}&exchange=${exchange}&interval=1m`]}>
      <NeoTradingViewWorkspace />
    </MemoryRouter>
  </QueryClientProvider>)
  await waitFor(() => expect(screen.getByTestId('active-studies')).toHaveTextContent('ema-9-15'))
  view.unmount(); client.clear()
})

it('adds three-EMA once to saved standard choices and remembers a later manual off', async () => {
  localStorage.setItem('neo.chart.toolkit.version','2')
  localStorage.setItem('neo.native.chart.indicators','["bb-chikou"]')
  const first=mountWorkspace()
  await waitFor(() => expect(screen.getByTestId('active-studies')).toHaveTextContent('ema-9-15'))
  expect(screen.getByTestId('active-studies')).toHaveTextContent('bb-chikou')
  fireEvent.click(screen.getByRole('button',{name:'Indicators'}))
  fireEvent.click(await screen.findByRole('checkbox',{name:'EMA 9 + EMA 15 + EMA 21'}))
  expect(screen.getByTestId('active-studies')).not.toHaveTextContent('ema-9-15')
  first.unmount()
  const second=mountWorkspace()
  expect(screen.getByTestId('active-studies')).not.toHaveTextContent('ema-9-15')
  expect(screen.getByTestId('active-studies')).toHaveTextContent('bb-chikou')
  second.unmount()
})

it('restores the selected book guide without dropping old controlled studies',async()=>{
 localStorage.setItem('neo.chart.toolkit.version','2')
 localStorage.setItem('neo.native.chart.ema-9-15-21.version','1')
 localStorage.setItem('neo.native.chart.video-guide.version','1')
 localStorage.setItem('neo.native.chart.indicators','["rsi","bb-chikou","book-pattern-risk-guide"]')
 mountWorkspace()
 await waitFor(()=>expect(screen.getByTestId('active-studies')).toHaveTextContent('rsi,bb-chikou,book-pattern-risk-guide'))
 expect(JSON.parse(localStorage.getItem('neo.native.chart.indicators')!)).toEqual(['rsi','bb-chikou','book-pattern-risk-guide'])
})
