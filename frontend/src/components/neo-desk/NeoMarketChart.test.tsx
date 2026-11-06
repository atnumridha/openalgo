import { loadEmaBackfill } from '../chart-toolkit/emaBackfill'
vi.mock('../chart-toolkit/emaBackfill', () => ({ loadEmaBackfill: vi.fn(async (candles) => serverEmaFixture(candles)) }))
import { serverEmaFixture } from '../../test/fixtures/serverEma'
vi.mock('../chart-toolkit/emaBackfill', async () => {
  const { emaPoints } = await import('../chart-toolkit/emaFibonacci')
  return {
    loadEmaBackfill: vi.fn(async (bars: { time: number; close: number }[]) =>
      Object.fromEntries(
        [9, 15, 21].map((period) => {
          const points = emaPoints(
            bars.map((b) => ({ ...b, open: b.close, high: b.close, low: b.close, volume: 0 })),
            period
          )
          return [
            String(period),
            {
              points,
              count: bars.length,
              sum: bars.slice(0, period).reduce((s, b) => s + b.close, 0),
              value: points.at(-1)?.value ?? null,
            },
          ]
        })
      )
    ),
  }
})
import { CandleProbabilityLayer } from '../chart-toolkit/CandleProbabilityLayer'
import * as toolkitModel from '../chart-toolkit/model'
import { readDeltaHistory, useDeltaCandle } from '../chart-toolkit/deltaFeed'
import { NineIndicatorEngine } from '../chart-toolkit/nineIndicators'
import { calculateBBChikou } from '../chart-toolkit/bbChikou'
import { ToolkitEngine } from '../chart-toolkit/model'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { neoReportsApi } from '@/api/neoReports'
import { scalpingApi } from '@/api/scalping'
import { NeoMarketChart } from './NeoMarketChart'
vi.mock('./DeltaTradePanel', () => ({
  DeltaTradePanel: ({
    symbol,
    enabled,
    riskContext,
    executionMode,
  }: {
    symbol: string
    enabled: boolean
    riskContext?: { intervalSeconds: number; entryAligned?: boolean } | null
    executionMode?: string
  }) => (
    <aside
      aria-label="Delta trading integration"
      data-enabled={String(enabled)}
      data-risk-seconds={riskContext?.intervalSeconds}
      data-risk-aligned={String(riskContext?.entryAligned)}
      data-execution-mode={executionMode}
    >
      {symbol}
    </aside>
  ),
}))
vi.mock('../chart-toolkit/DeltaOrderLayer', () => ({
  DeltaOrderLayer: class {
    update = vi.fn()
    destroy = vi.fn()
  },
}))
import { computeStudies } from './tradingViewStudies'
import { saveHistorySnapshot } from '../chart-toolkit/historySnapshot'
import { optionRiskApi } from './optionRiskApi'
import { PiyushResearchLayer, PIYUSH_MODES } from './PiyushResearchLayer'
vi.mock('../chart-toolkit/deltaFeed', () => ({
  readDeltaHistory: vi.fn(),
  useDeltaCandle: vi.fn(() => ({ connected: false })),
}))
vi.mock('./optionRiskApi', () => ({
  optionRiskApi: {
    preview: vi.fn(async (b) => ({
      ...b,
      target: String(Number(b.entry) + 2 * (Number(b.entry) - Number(b.stop))),
      lot_size: 65,
      quantity: b.lots * 65,
      net_profit: '1200.00',
      net_loss: '700.00',
      net_reward_risk: '1.71',
      profit_fees: '50.00',
      loss_fees: '50.00',
      brokerage_per_order: '10.00',
      fee_date: '2026-10-15',
      profit_fee_breakdown: { brokerage: '20' },
      loss_fee_breakdown: { brokerage: '20' },
    })),
  },
}))
vi.mock('../chart-toolkit/bbChikou', async (original) => {
  const actual = await original<typeof import('../chart-toolkit/bbChikou')>()
  return { ...actual, calculateBBChikou: vi.fn(actual.calculateBBChikou) }
})
vi.mock('./tradingViewStudies', async (original) => {
  const actual = await original<typeof import('./tradingViewStudies')>()
  return { ...actual, computeStudies: vi.fn(actual.computeStudies) }
})

const mocks = vi.hoisted(() => ({
  series: [] as Array<{
    setData: ReturnType<typeof vi.fn>
    kind?: string
    pane?: number
    options?: Record<string, unknown>
  }>,
  remove: vi.fn(),
  createLine: vi.fn((config: { title?: string; price?: number }) => ({ ...config })),
  removeLine: vi.fn(),
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
vi.mock('@/api/scalping', () => ({
  scalpingApi: {
    getHistory: vi.fn(),
    getExpiry: vi.fn(async () => ({ status: 'success', data: [] })),
    getStrikes: vi.fn(async () => ({ status: 'success', chain: [] })),
  },
}))
vi.mock('lightweight-charts', () => ({
  createSeriesMarkers: () => ({ setMarkers: vi.fn() }),
  CandlestickSeries: 'candles',
  LineSeries: 'line',
  HistogramSeries: 'histogram',
  CrosshairMode: { Normal: 0 },
  LineStyle: { Dashed: 2 },
  TickMarkType: { Time: 3, TimeWithSeconds: 4 },
  createChart: () => ({
    addSeries: (kind: string, options: Record<string, unknown> = {}, pane = 0) => {
      const s = {
        kind,
        options,
        pane,
        setData: vi.fn(),
        update: vi.fn(),
        applyOptions: vi.fn(),
        createPriceLine: mocks.createLine,
        removePriceLine: mocks.removeLine,
        attachPrimitive: vi.fn(),
        priceScale: () => ({ applyOptions: vi.fn() }),
      }
      // Keep the original spies observable after the host decorates setData.
      mocks.series.push({ ...s })
      return s
    },
    panes: () => [
      { setStretchFactor: vi.fn() },
      { setStretchFactor: vi.fn() },
      { setStretchFactor: vi.fn() },
    ],
    timeScale: () => ({ setVisibleLogicalRange: mocks.range }),
    clearCrosshairPosition: vi.fn(),
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
  vi.mocked(loadEmaBackfill).mockImplementation(async candles => serverEmaFixture(candles))
  vi.clearAllMocks()
  vi.mocked(useDeltaCandle).mockReturnValue({ connected: false } as never)
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
it.each([
  'CE',
  'PE',
])('plots an outside entry and automatic 2R plan on the matching %s premium', async (side) => {
  const symbol = `NIFTY03NOV2623050${side}`
  const contract = { symbol, ltp: 107, ask: 107, lotsize: 65, tick_size: 0.05 }
  const candles = Array.from({ length: 35 }, (_, i) => ({
    time: history.candles[0].time + i * 300,
    open: 100,
    high: 102,
    low: 98,
    close: 100,
    volume: 0,
  }))
  candles[25] = { ...candles[25], open: 98, high: 100, low: 94, close: 98 }
  candles[29] = { ...candles[29], open: 104, high: 108, low: 102, close: 104 }
  vi.mocked(scalpingApi.getHistory).mockResolvedValue({
    ...history,
    interval: '5m',
    candles,
    symbol,
    exchange: 'NFO',
  })
  const reference = {
    underlying: 'NIFTY',
    exchange: 'NSE_INDEX',
    optionExchange: 'NFO',
    expiry: '03NOV26',
    [side.toLowerCase()]: { symbol, strike: 23050, contract },
  }
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart
        symbol={symbol}
        exchange="NFO"
        interval="5m"
        optionReference={reference as never}
        focusMode
      />
    </QueryClientProvider>
  )
  await waitFor(() => expect(mocks.series[0]?.setData).toHaveBeenCalled())
  fireEvent.click(screen.getByRole('button', { name: /Entry.*SL.*Target/ }))
  fireEvent.change(screen.getByLabelText('Your entry price'), { target: { value: '100' } })
  await screen.findByLabelText('Estimated net profit')
  const body = vi.mocked(optionRiskApi.preview).mock.lastCall![0]
  expect(body).toMatchObject({ symbol, exchange: 'NFO', entry: '100.00', lots: 1 })
  expect(Number(body.stop)).toBeLessThan(94)
  await waitFor(() =>
    expect(mocks.createLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: 100, title: 'Entry (preview)' })
    )
  )
  expect(mocks.createLine).toHaveBeenCalledWith(
    expect.objectContaining({ price: Number(body.stop), title: 'SL (preview)' })
  )
  expect(mocks.createLine).toHaveBeenCalledWith(
    expect.objectContaining({
      price: Number((100 + 2 * (100 - Number(body.stop))).toFixed(2)),
      title: 'Target 1:2',
    })
  )
})
it('applies every research Setup choice and target immediately, including Off', async () => {
  vi.mocked(scalpingApi.getHistory).mockResolvedValue({ ...history, interval: '1m' })
  const update = vi.spyOn(PiyushResearchLayer.prototype, 'update')
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="1m" focusMode />
    </QueryClientProvider>
  )
  await waitFor(() => expect(mocks.series[0]?.setData).toHaveBeenCalled())
  for (const [mode] of PIYUSH_MODES) {
    fireEvent.click(screen.getByRole('combobox', { name: 'Setup' }))
    const list = await screen.findByRole('listbox', { name: 'Research setup choices' })
    fireEvent.click(
      within(list).getByRole('option', { name: PIYUSH_MODES.find(([value]) => value === mode)![1] })
    )
    await waitFor(() =>
      expect(update).toHaveBeenLastCalledWith(
        expect.any(Array),
        mode,
        2,
        'NIFTY',
        '1m',
        expect.any(Number),
        expect.any(Number),
        expect.objectContaining({ universal: true })
      )
    )
  }
  expect(screen.getByLabelText('Target')).toHaveTextContent('1:2')
  update.mockRestore()
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

it('defaults CE signals to premium candles and keeps underlying signals as an explicit choice', async () => {
  vi.mocked(scalpingApi.getHistory).mockImplementation(async (s, e) =>
    optionFixture(s, e, s === 'NIFTY')
  )
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart
        symbol="NIFTY03NOV2623000CE"
        exchange="NFO"
        interval="1m"
        studies={['nine-ma']}
      />
    </QueryClientProvider>
  )
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('Moving Averages signal')).getByText('AVOID CE')
    ).toBeVisible()
  )
  expect(screen.getByRole('combobox', { name: 'Signal price source' })).toHaveValue('premium')
  expect(screen.getByRole('combobox', { name: 'Independent indicators source' })).toHaveValue(
    'premium'
  )
  expect(scalpingApi.getHistory).not.toHaveBeenCalledWith(
    'NIFTY',
    'NSE_INDEX',
    '1m',
    undefined,
    expect.anything()
  )
  fireEvent.change(screen.getByRole('combobox', { name: 'Signal price source' }), {
    target: { value: 'underlying' },
  })
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('Moving Averages signal')).getByText('BUY CE')
    ).toBeVisible()
  )
  expect(screen.getByRole('combobox', { name: 'Independent indicators source' })).toHaveValue(
    'underlying'
  )
})

function optionFixture(symbol: string, exchange: string, rising: boolean, count = 70) {
  return {
    ...history,
    symbol,
    exchange,
    interval: '1m',
    candles: Array.from({ length: count }, (_, i) => {
      const close = i < 50 ? 100 : rising ? 110 : 90
      return {
        time: Date.UTC(2026, 9, 15, 9, 15) / 1000 + i * 60,
        open: close,
        high: close + 1,
        low: close - 1,
        close,
        volume: 100,
      }
    }),
  }
}
it.each([
  false,
  true,
])('inverts index direction on PE and replays verified history (empty date response: %s)', async (emptyDate) => {
  vi.mocked(scalpingApi.getHistory).mockImplementation(async (s, e, _interval, date) => {
    const response = optionFixture(s, e, s !== 'NIFTY')
    return emptyDate && s === 'NIFTY' && date ? { ...response, candles: [] } : response
  })
  vi.mocked(neoReportsApi.chart).mockImplementation(async (s, e) => ({
    ...optionFixture(s, e, false),
    candles: [],
  }))
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart
        symbol="NIFTY03NOV2623000PE"
        exchange="NFO"
        interval="1m"
        studies={['nine-ma']}
      />
    </QueryClientProvider>
  )
  fireEvent.change(screen.getByRole('combobox', { name: 'Signal price source' }), {
    target: { value: 'underlying' },
  })
  const row = () => within(screen.getByLabelText('Moving Averages signal'))
  await waitFor(() => expect(row().getByText('BUY PE')).toBeVisible())
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  await waitFor(() =>
    expect(scalpingApi.getHistory).toHaveBeenCalledWith(
      'NIFTY',
      'NSE_INDEX',
      '1m',
      '2026-10-15',
      expect.anything()
    )
  )
  await waitFor(() => expect(row().getByText('WAIT')).toBeVisible())
  expect(row().queryByText('BUY PE')).not.toBeInTheDocument()
  fireEvent.change(screen.getByRole('slider', { name: 'Replay candle' }), {
    target: { value: '69' },
  })
  await waitFor(() => expect(row().getByText('BUY PE')).toBeVisible())
})
it.each([
  'failure',
  'mismatch',
])('waits when underlying history has a %s and allows premium mode', async (failure) => {
  vi.mocked(scalpingApi.getHistory).mockImplementation(async (s, e) => {
    if (s === 'NIFTY') {
      if (failure === 'failure') throw Error('No index candles')
      return optionFixture('SENSEX', 'BSE_INDEX', true)
    }
    return optionFixture(s, e, true)
  })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart
        symbol="NIFTY03NOV2623000PE"
        exchange="NFO"
        interval="1m"
        studies={['nine-ma']}
      />
    </QueryClientProvider>
  )
  fireEvent.change(screen.getByRole('combobox', { name: 'Signal price source' }), {
    target: { value: 'underlying' },
  })
  await waitFor(() =>
    expect(scalpingApi.getHistory).toHaveBeenCalledWith(
      'NIFTY',
      'NSE_INDEX',
      '1m',
      undefined,
      expect.anything()
    )
  )
  expect(within(screen.getByLabelText('Moving Averages signal')).getByText('WAIT')).toBeVisible()
  fireEvent.change(screen.getByRole('combobox', { name: 'Independent indicators source' }), {
    target: { value: 'premium' },
  })
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('Moving Averages signal')).getByText('BUY PE')
    ).toBeVisible()
  )
})
it('does not reuse a NIFTY result when switching to SENSEX PE with delayed source history', async () => {
  vi.mocked(scalpingApi.getHistory).mockImplementation(async (s, e) =>
    s === 'SENSEX' ? new Promise(() => {}) : optionFixture(s, e, true)
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = (symbol: string, exchange: string) => (
    <QueryClientProvider client={client}>
      <NeoMarketChart symbol={symbol} exchange={exchange} interval="1m" studies={['nine-ma']} />
    </QueryClientProvider>
  )
  const view = render(content('NIFTY03NOV2623000CE', 'NFO'))
  fireEvent.change(screen.getByRole('combobox', { name: 'Signal price source' }), {
    target: { value: 'underlying' },
  })
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('Moving Averages signal')).getByText('BUY CE')
    ).toBeVisible()
  )
  view.rerender(content('SENSEX05NOV2675000PE', 'BFO'))
  expect(within(screen.getByLabelText('Moving Averages signal')).getByText('WAIT')).toBeVisible()
  await waitFor(() =>
    expect(scalpingApi.getHistory).toHaveBeenCalledWith(
      'SENSEX',
      'BSE_INDEX',
      '1m',
      undefined,
      expect.anything()
    )
  )
  expect(screen.getByText('Price signals: SENSEX.')).toBeVisible()
})
it('does not confirm a cached partial premium candle just because the clock advances', async () => {
  vi.mocked(Date.now).mockReturnValue(
    (Date.UTC(2026, 9, 15, 9, 15) / 1000 - 19800 + 50 * 60 + 30) * 1000
  )
  vi.mocked(scalpingApi.getHistory).mockImplementation(async (s, e) =>
    optionFixture(s, e, true, 51)
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = (title: string) => (
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol="NIFTY03NOV2623000PE"
        exchange="NFO"
        interval="1m"
        studies={['nine-ma']}
        title={title}
      />
    </QueryClientProvider>
  )
  const view = render(content('PE'))
  await waitFor(() => expect(mocks.series[0]?.setData.mock.calls.at(-1)?.[0]).toHaveLength(51))
  fireEvent.change(screen.getByRole('combobox', { name: 'Independent indicators source' }), {
    target: { value: 'premium' },
  })
  expect(within(screen.getByLabelText('Moving Averages signal')).getByText('WAIT')).toBeVisible()
  vi.mocked(Date.now).mockReturnValue(Date.now() + 60000)
  view.rerender(content('Later PE'))
  fireEvent.change(screen.getByRole('combobox', { name: 'Independent indicators source' }), {
    target: { value: 'underlying' },
  })
  fireEvent.change(screen.getByRole('combobox', { name: 'Independent indicators source' }), {
    target: { value: 'premium' },
  })
  expect(within(screen.getByLabelText('Moving Averages signal')).getByText('WAIT')).toBeVisible()
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
  expect(scalpingApi.getHistory).toHaveBeenCalledWith(
    'NIFTY',
    'NSE_INDEX',
    '15m',
    '2026-10-12',
    expect.objectContaining({ timeoutMs: 30000 })
  )
  expect(scalpingApi.getHistory).toHaveBeenCalledWith(
    'NIFTY',
    'NSE_INDEX',
    '15m',
    '2026-10-13',
    expect.objectContaining({ timeoutMs: 30000 })
  )
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

it('keeps disabled legacy studies out of the live toolkit redraw and loads references only on demand', async () => {
  vi.mocked(Date.now).mockReturnValue(Date.UTC(2026, 9, 15, 9, 40))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = () => (
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="15m"
        studies={['neo-toolkit']}
        focusMode
      />
    </QueryClientProvider>
  )
  const view = render(content())
  await waitFor(() => expect(mocks.series[0]?.setData.mock.calls.at(-1)?.[0]).toHaveLength(24))
  expect(computeStudies).not.toHaveBeenCalled()
  expect(scalpingApi.getHistory).not.toHaveBeenCalledWith(
    'NIFTY',
    'NSE_INDEX',
    '1h',
    undefined,
    expect.objectContaining({ timeoutMs: 30000 })
  )
  expect(mocks.series.slice(6, 8).every((s) => !s.setData.mock.calls.length)).toBe(true)
  const legacyWrites = mocks.series.map((s) => s.setData.mock.calls.length)
  mocks.market.mockReturnValue({
    data: new Map([['NSE_INDEX:NIFTY', { data: { ltp: 100.5, timestamp: Date.now() } }]]),
    isConnected: true,
  })
  for (let i = 0; i < 25; i++) {
    mocks.market.mockReturnValue({
      data: new Map([
        ['NSE_INDEX:NIFTY', { data: { ltp: 100.5 + i / 100, timestamp: Date.now() } }],
      ]),
      isConnected: true,
    })
    view.rerender(content())
  }
  expect(computeStudies).not.toHaveBeenCalled()
  expect(mocks.series.map((s) => s.setData.mock.calls.length)).toEqual(legacyWrites)
  fireEvent.click(screen.getByRole('button', { name: 'Signals & details' }))
  fireEvent.click(screen.getByText('Details'))
  fireEvent.click(screen.getByRole('checkbox', { name: '1D / 4H / 1H high & low' }))
  await waitFor(() =>
    expect(scalpingApi.getHistory).toHaveBeenCalledWith(
      'NIFTY',
      'NSE_INDEX',
      '1h',
      undefined,
      expect.objectContaining({ timeoutMs: 30000 })
    )
  )
})
it('coalesces quote bursts into one study redraw while preserving every candle price/extreme', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const studies = ['bb-chikou']
  const ui = () => (
    <QueryClientProvider client={client}>
      <NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" studies={studies} />
    </QueryClientProvider>
  )
  const view = render(ui())
  await waitFor(() => expect(mocks.series[0]?.setData.mock.calls.at(-1)?.[0]).toHaveLength(24))
  vi.useFakeTimers()
  vi.mocked(calculateBBChikou).mockClear()
  for (let i = 0; i < 50; i++) {
    mocks.market.mockReturnValue({
      data: new Map([
        [
          'NSE_INDEX:NIFTY',
          { data: { ltp: i === 0 ? 120 : i === 1 ? 80 : 100 + i / 100, timestamp: Date.now() } },
        ],
      ]),
      isConnected: true,
    })
    view.rerender(ui())
  }
  expect(calculateBBChikou).not.toHaveBeenCalled()
  const lastUpdate = (
    mocks.series[0] as unknown as { update: ReturnType<typeof vi.fn> }
  ).update.mock.calls.at(-1)?.[0]
  expect(lastUpdate).toMatchObject({ close: 100.49, high: 120, low: 80 })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(200)
  })
  expect(calculateBBChikou).toHaveBeenCalledTimes(1)
  view.unmount()
  client.clear()
  vi.useRealTimers()
})

it('shows saved candles immediately during a slow load and keeps the trade side on WAIT', async () => {
  saveHistorySnapshot(undefined, 'live', history)
  vi.mocked(scalpingApi.getHistory).mockImplementation(() => new Promise(() => {}))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="15m"
        studies={['neo-toolkit']}
        focusMode
      />
    </QueryClientProvider>
  )
  await waitFor(() => expect(mocks.series[0]?.setData.mock.calls.at(-1)?.[0]).toHaveLength(24))
  expect(screen.getByText('Saved candles · updating')).toBeVisible()
  expect(screen.getByLabelText('Confirmed price signal')).toHaveTextContent('WAIT')
  expect(screen.getByLabelText('Confirmed price signal')).toHaveTextContent(
    'Waiting for candle history'
  )
})

it('keeps candlestick probability optional and independent of the existing studies', async () => {
  mount()
  const choice = screen.getByLabelText('Candlestick probability · 2R / 10 candles')
  expect(choice).not.toBeChecked()
  expect(screen.queryByLabelText('Candlestick probability')).not.toBeInTheDocument()
  fireEvent.click(choice)
  expect(await screen.findByLabelText('Candlestick probability')).toBeVisible()
  fireEvent.click(choice)
  expect(screen.queryByLabelText('Candlestick probability')).not.toBeInTheDocument()
})

it('uses the history observation to close candles, ignoring advancing time and live candle changes', async () => {
  const start = Date.UTC(2026, 9, 15, 3, 45) / 1000
  vi.mocked(Date.now).mockReturnValue((start + 11 * 60 + 30) * 1000)
  const source = {
    ...history,
    interval: '1m',
    candles: [
      ...Array.from({ length: 10 }, (_, i) => ({
        time: start + 19800 + i * 60,
        open: 100,
        high: 101,
        low: 99,
        close: 100,
        volume: 0,
      })),
      { time: start + 19800 + 600, open: 100.5, high: 100.8, low: 99.8, close: 100, volume: 0 },
      { time: start + 19800 + 660, open: 99.9, high: 101, low: 99.5, close: 100.8, volume: 0 },
    ],
  }
  vi.mocked(scalpingApi.getHistory).mockResolvedValue(source)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = (title: string) => (
    <QueryClientProvider client={client}>
      <NeoMarketChart
        title={title}
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="1m"
        studies={['candle-probability']}
      />
    </QueryClientProvider>
  )
  const view = render(content('Initial history'))
  await waitFor(() =>
    expect(screen.getByLabelText('Candlestick probability')).toHaveTextContent(
      'No setup on the latest completed candle'
    )
  )
  expect(screen.queryByText('Bullish engulfing')).not.toBeInTheDocument()
  vi.mocked(Date.now).mockReturnValue((start + 12 * 60 + 5) * 1000)
  mocks.market.mockReturnValue({
    data: new Map([['NSE_INDEX:NIFTY', { data: { ltp: 102, timestamp: Date.now() } }]]),
    isConnected: true,
  })
  view.rerender(content('Later live quote'))
  expect(screen.queryByText('Bullish engulfing')).not.toBeInTheDocument()
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['neo-tv-history'] })
  })
  await waitFor(() => expect(screen.getByText('Bullish engulfing')).toBeVisible())
  expect(screen.getByLabelText('Price references')).toHaveTextContent('100.80')
  expect(computeStudies).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(screen.queryByText('Bullish engulfing')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Candlestick probability')).toHaveTextContent('REPLAY')
  fireEvent.click(screen.getByRole('button', { name: 'Return to live' }))
  expect(screen.getByText('Bullish engulfing')).toBeVisible()
  vi.mocked(scalpingApi.getHistory).mockRejectedValue(Error('Fresh history failed'))
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['neo-tv-history'] })
  })
  await waitFor(() =>
    expect(screen.getByLabelText('Candlestick probability')).toHaveTextContent(
      'Waiting for verified candle history'
    )
  )
  view.unmount()
})

it('does not use a saved snapshot as confirmed candlestick evidence', async () => {
  saveHistorySnapshot(undefined, 'live', history)
  vi.mocked(scalpingApi.getHistory).mockRejectedValue(Error('No fresh source'))
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="15m"
        studies={['candle-probability']}
      />
    </QueryClientProvider>
  )
  expect(await screen.findByLabelText('Candlestick probability')).toHaveTextContent('WAIT')
  expect(screen.getByLabelText('Candlestick probability')).toHaveTextContent(
    'Waiting for verified candle history'
  )
})

it('does not turn unverified initial candles into verified evidence when the chart remounts', async () => {
  const start = Date.UTC(2026, 9, 15, 3, 45) / 1000
  vi.mocked(Date.now).mockReturnValue((start + 13 * 60) * 1000)
  const cached = {
    ...history,
    interval: '1m',
    candles: [
      ...Array.from({ length: 10 }, (_, i) => ({
        time: start + 19800 + i * 60,
        open: 100,
        high: 101,
        low: 99,
        close: 100,
        volume: 0,
      })),
      { time: start + 19800 + 600, open: 100.5, high: 100.8, low: 99.8, close: 100, volume: 0 },
      { time: start + 19800 + 660, open: 99.9, high: 101, low: 99.5, close: 100.8, volume: 0 },
    ],
  }
  vi.mocked(scalpingApi.getHistory).mockImplementation(() => new Promise(() => {}))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const first = render(
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="1m"
        initialHistory={cached}
        studies={['candle-probability']}
      />
    </QueryClientProvider>
  )
  expect(screen.queryByText('Bullish engulfing')).not.toBeInTheDocument()
  first.unmount()
  render(
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="1m"
        studies={['candle-probability']}
      />
    </QueryClientProvider>
  )
  expect(screen.queryByText('Bullish engulfing')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Candlestick probability')).toHaveTextContent(
    'Waiting for verified candle history'
  )
})

it('automatically recovers verified history after a transient failure without a manual retry', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] })
  let view: ReturnType<typeof render> | undefined
  try {
    saveHistorySnapshot(undefined, 'live', history)
    vi.mocked(scalpingApi.getHistory)
      .mockRejectedValueOnce(Error('Broker temporarily delayed'))
      .mockResolvedValue(history)
    view = render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" studies={['nine-ma']} />
      </QueryClientProvider>
    )
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100)
    })
    expect(scalpingApi.getHistory).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Retry history' })).toBeEnabled()
    expect(screen.getByRole('alert')).toHaveTextContent('Retrying automatically')
    expect(screen.getByText(/historical events only/)).toBeVisible()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15500)
    })
    expect(scalpingApi.getHistory).toHaveBeenCalledTimes(2)
    expect(screen.queryByRole('button', { name: 'Retry history' })).not.toBeInTheDocument()
    expect(screen.queryByText(/historical events only/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Saved candles/)).not.toBeInTheDocument()
  } finally {
    view?.unmount()
    vi.useRealTimers()
  }
})

it('does not prefill a premium alert with support inherited from an index chart', async () => {
  const original = ToolkitEngine.prototype.update
  vi.spyOn(ToolkitEngine.prototype, 'update').mockImplementation(function (
    this: ToolkitEngine,
    ...args
  ) {
    const r = original.apply(this, args)
    return {
      ...r,
      zones: [
        {
          id: 1,
          time: args[0][0]?.time ?? 0,
          confirmedTime: args[0][0]?.time ?? 0,
          high: 9001,
          low: 9000,
          above: false,
        },
      ],
    }
  })
  vi.mocked(scalpingApi.getHistory).mockImplementation(async (symbol) =>
    symbol === 'NIFTY' ? history : await new Promise(() => {})
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = (symbol: string, exchange: string) => (
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol={symbol}
        exchange={exchange}
        interval="15m"
        studies={['neo-toolkit']}
        focusMode
      />
    </QueryClientProvider>
  )
  const view = render(ui('NIFTY', 'NSE_INDEX'))
  await waitFor(() => expect(mocks.series[0]?.setData.mock.calls.at(-1)?.[0]).toHaveLength(24))
  view.rerender(ui('NIFTY03NOV2623500CE', 'NFO'))
  fireEvent.click(screen.getByText('Price alerts'))
  expect(screen.getByLabelText('Alert premium price')).toHaveValue(null)
  expect(screen.getByRole('button', { name: 'Add alert' })).toBeDisabled()
})

it.each([
  'CE',
  'PE',
])('keeps toolkit confirmations at verified history time for %s premiums', async (side) => {
  const observed = Date.UTC(2026, 9, 15, 9, 15) / 1000 - 19800 + 50 * 60 + 30
  vi.mocked(Date.now).mockReturnValue(observed * 1000)
  vi.mocked(scalpingApi.getHistory).mockImplementation(async (s, e) =>
    optionFixture(s, e, true, 51)
  )
  const update = vi.spyOn(ToolkitEngine.prototype, 'update')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = (extra: boolean) => (
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol={`NIFTY03NOV2623000${side}`}
        exchange="NFO"
        interval="1m"
        studies={
          extra ? ['neo-toolkit', 'bb-chikou', 'neo-structure'] : ['neo-toolkit', 'bb-chikou']
        }
      />
    </QueryClientProvider>
  )
  const view = render(ui(false))
  await waitFor(() => expect(mocks.series[0]?.setData.mock.calls.at(-1)?.[0]).toHaveLength(51))
  expect(update.mock.results.at(-1)?.value.closedTime).toBe(observed - 90)
  vi.mocked(Date.now).mockReturnValue((observed + 60) * 1000)
  view.rerender(ui(true))
  expect(update.mock.results.at(-1)?.value.closedTime).toBe(observed - 90)
  expect(vi.mocked(calculateBBChikou).mock.calls.at(-1)?.[1].asOf).toBe(observed)
  expect(vi.mocked(computeStudies).mock.calls.at(-1)?.[2]).toBe(observed)
  await act(async () => {
    await client.invalidateQueries()
  })
  await waitFor(() => expect(update.mock.results.at(-1)?.value.closedTime).toBe(observed - 30))
  update.mockRestore()
})

it('does not promote cached partial crypto candles into confirmed signals when only the clock advances', async () => {
  const observed = (Date.UTC(2026, 9, 15, 9, 15) / 1000 - 19800 + 50 * 60 + 30) * 1000
  vi.mocked(Date.now).mockReturnValue(observed)
  vi.mocked(readDeltaHistory).mockResolvedValue(optionFixture('BTCUSD', 'DELTA', true, 51))
  const update = vi.spyOn(NineIndicatorEngine.prototype, 'update')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = (more = false) => (
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol="BTCUSD"
        exchange="DELTA"
        interval="1m"
        studies={more ? ['bb-chikou', 'nine-ma', 'rsi'] : ['bb-chikou', 'nine-ma']}
        focusMode
      />
    </QueryClientProvider>
  )
  const view = render(content())
  await waitFor(() => expect(mocks.series[0]?.setData.mock.lastCall?.[0]).toHaveLength(51))
  await waitFor(() => expect(calculateBBChikou).toHaveBeenCalled())
  vi.mocked(Date.now).mockReturnValue(observed + 60000)
  view.rerender(content(true))
  await waitFor(() =>
    expect(vi.mocked(calculateBBChikou).mock.lastCall?.[1].asOf).toBe(observed / 1000)
  )
  expect(update.mock.lastCall?.[1].asOf).toBe(observed / 1000)
  update.mockRestore()
})

it('never confirms separately cached partial hourly crypto references using a newer chart observation', async () => {
  const at = Date.parse('2026-10-15T11:59:30Z'),
    hour = Date.parse('2026-10-15T11:00:00Z') / 1000
  vi.mocked(Date.now).mockReturnValue(at)
  vi.mocked(readDeltaHistory).mockImplementation(async (s, tf) => ({
    ...optionFixture(s, 'DELTA', true, 51),
    interval: tf,
    candles:
      tf === '1h'
        ? [{ time: hour + 19800, open: 100, high: 120, low: 90, close: 110, volume: 100 }]
        : optionFixture(s, 'DELTA', true, 51).candles,
  }))
  const completed = vi.spyOn(toolkitModel, 'completedReferences')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol="BTCUSD"
        exchange="DELTA"
        interval="1m"
        studies={['neo-toolkit']}
        focusMode
      />
    </QueryClientProvider>
  )
  await waitFor(() => expect(mocks.series[0]?.setData.mock.lastCall?.[0]).toHaveLength(51))
  fireEvent.click(screen.getByRole('button', { name: 'Signals & details' }))
  fireEvent.click(screen.getByText('Details'))
  fireEvent.click(screen.getByRole('checkbox', { name: '1D / 4H / 1H high & low' }))
  await waitFor(() =>
    expect(readDeltaHistory).toHaveBeenCalledWith(
      'BTCUSD',
      '1h',
      undefined,
      expect.any(AbortSignal)
    )
  )
  await waitFor(() => expect(completed).toHaveBeenCalled())
  expect(completed.mock.lastCall![0]).toEqual([])
  const later = Date.parse('2026-10-15T12:01:00Z')
  vi.mocked(Date.now).mockReturnValue(later)
  act(() =>
    client.setQueryData(
      ['neo-tv-history', 'DELTA', 'BTCUSD', '1m', undefined, undefined],
      (old: Record<string, unknown>) => ({ ...old, observedAt: later / 1000 })
    )
  )
  await waitFor(() => expect(completed.mock.lastCall![2]).toBe(later / 1000))
  expect(completed.mock.lastCall![0]).toEqual([])
  completed.mockRestore()
})

it('clears candlestick overlay evidence as soon as the current history refresh fails', async () => {
  const update = vi.spyOn(CandleProbabilityLayer.prototype, 'update')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="15m"
        studies={['candle-probability']}
      />
    </QueryClientProvider>
  )
  await waitFor(() => expect(update.mock.calls.some(([study]) => study != null)).toBe(true))
  vi.mocked(scalpingApi.getHistory).mockRejectedValue(Error('temporary broker delay'))
  await act(async () => {
    await client.refetchQueries({
      queryKey: ['neo-tv-history', 'NSE_INDEX', 'NIFTY', '15m'],
      exact: false,
    })
  })
  await waitFor(() => expect(update.mock.calls.at(-1)?.[0]).toBeNull())
  expect(screen.getByLabelText('Candlestick probability')).toHaveTextContent(
    'Waiting for verified candle history'
  )
  view.unmount()
})

it('uses verified selected-date candlestick evidence even if the independent recent-history request fails', async () => {
  const update = vi.spyOn(CandleProbabilityLayer.prototype, 'update')
  const start = Date.UTC(2026, 9, 14, 9, 15) / 1000
  const source = {
    ...history,
    interval: '1m',
    date: '2026-10-14',
    candles: [
      ...Array.from({ length: 10 }, (_, i) => ({
        time: start + i * 60,
        open: 100,
        high: 101,
        low: 99,
        close: 100,
        volume: 0,
      })),
      { time: start + 600, open: 100.5, high: 100.8, low: 99.8, close: 100, volume: 0 },
      { time: start + 660, open: 99.9, high: 101, low: 99.5, close: 100.8, volume: 0 },
    ],
  }
  vi.mocked(scalpingApi.getHistory).mockImplementation(async (_s, _e, _i, date) => {
    if (!date) throw Error('recent history delayed')
    return { ...source, candles: date === '2026-10-14' ? source.candles : [] }
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="1m"
        studies={['candle-probability']}
      />
    </QueryClientProvider>
  )
  await waitFor(() =>
    expect(
      client.getQueryState(['neo-tv-history', 'NSE_INDEX', 'NIFTY', '1m', undefined, undefined])
        ?.status
    ).toBe('error')
  )
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-14' } })
  fireEvent.input(screen.getByLabelText('To date IST'), { target: { value: '2026-10-14' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  await waitFor(() => expect(update.mock.calls.at(-1)?.[0]?.latest?.pattern).toBe('engulfing'))
  expect(screen.getByLabelText('Candlestick probability')).not.toHaveTextContent(
    'Waiting for verified candle history'
  )
  view.unmount()
})

it('changes the chart candlestick family and clears unrelated candidate levels', async () => {
  const start = Date.UTC(2026, 9, 15, 3, 45) / 1000
  vi.mocked(Date.now).mockReturnValue((start + 13 * 60) * 1000)
  vi.mocked(scalpingApi.getHistory).mockResolvedValue({
    ...history,
    interval: '1m',
    candles: [
      ...Array.from({ length: 10 }, (_, i) => ({
        time: start + 19800 + i * 60,
        open: 100,
        high: 101,
        low: 99,
        close: 100,
        volume: 0,
      })),
      { time: start + 19800 + 600, open: 100.5, high: 100.8, low: 99.8, close: 100, volume: 0 },
      { time: start + 19800 + 660, open: 99.9, high: 101, low: 99.5, close: 100.8, volume: 0 },
    ],
  })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="1m"
        studies={['candle-probability']}
      />
    </QueryClientProvider>
  )
  await waitFor(() => expect(screen.getByText('Bullish engulfing')).toBeVisible())
  fireEvent.change(screen.getByLabelText('Pattern setup'), { target: { value: 'rejection' } })
  expect(screen.getByLabelText('Pattern setup')).toHaveValue('rejection')
  expect(screen.queryByText('Bullish engulfing')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Candlestick probability')).toHaveTextContent(
    'No setup on the latest completed candle'
  )
})
it('routes a source template to its chart tool without inventing a research signal or shrinking the plot', async () => {
  const update = vi.spyOn(PiyushResearchLayer.prototype, 'update')
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" focusMode />
    </QueryClientProvider>
  )
  await waitFor(() => expect(mocks.series[0]?.setData).toHaveBeenCalled())
  fireEvent.click(screen.getByRole('combobox', { name: 'Setup' }))
  fireEvent.click(await screen.findByRole('option', { name: 'A-01 · Nifty Alpha Edge' }))
  expect(screen.getByLabelText('Study status')).toHaveTextContent('Strategy preview')
  expect(update.mock.calls.every((args) => !String(args[1]).startsWith('A-'))).toBe(true)
  expect(screen.getByRole('dialog', { name: 'Strategy' })).toBeVisible()
  expect(screen.getByRole('dialog', { name: 'Strategy' })).toHaveTextContent('Entry and exit rules')
  expect(screen.getByRole('region', { name: 'TradingView candlesticks' })).toHaveClass('flex-1')
  fireEvent.click(screen.getByRole('button', { name: 'Close Strategy' }))
  fireEvent.click(screen.getByRole('combobox', { name: 'Setup' }))
  fireEvent.click(await screen.findByRole('option', { name: 'EMA 8/33 cross · 5m' }))
  await waitFor(() => expect(update.mock.lastCall?.[1]).toBe('ema_cross_5m'))
  expect(screen.queryByRole('button', { name: 'Strategy settings' })).not.toBeInTheDocument()
  update.mockRestore()
})

it.each([
  ['NIFTY24NOV26FUT', 'A-06 · Titan Naked Strike'],
  ['BANKNIFTY24NOV26FUT', 'A-07 · Titan Naked Blitz · BankNifty'],
])('updates and cleans explicit futures references for %s', async (symbol, label) => {
  const { useAuthStore } = await import('@/stores/authStore'),
    { useThemeStore } = await import('@/stores/themeStore')
  const originalUser = useAuthStore.getState().user
  act(() =>
    useAuthStore.setState({
      user: { username: 'source-preview-user', broker: 'fyers', isLoggedIn: true, loginTime: null },
    })
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(
    [
      'chart-contract-metadata',
      useAuthStore.getState().user?.username,
      useThemeStore.getState().appMode,
      symbol,
      'NFO',
    ],
    {
      symbol,
      exchange: 'NFO',
      tick_size: 0.05,
      lotsize: 65,
      session: { start: 555, end: 940, offset: 19800 },
    }
  )
  vi.mocked(scalpingApi.getHistory).mockResolvedValue({ ...history, symbol, exchange: 'NFO' })
  const view = render(
    <QueryClientProvider client={client}>
      <NeoMarketChart symbol={symbol} exchange="NFO" interval="15m" focusMode />
    </QueryClientProvider>
  )
  await waitFor(() => expect(mocks.series[0]?.setData).toHaveBeenCalled())
  fireEvent.click(screen.getByRole('combobox', { name: 'Setup' }))
  fireEvent.click(await screen.findByRole('option', { name: label }))
  expect(screen.getByRole('dialog', { name: 'Strategy' })).toBeVisible()
  fireEvent.change(screen.getByLabelText('Actual futures entry'), { target: { value: '24000' } })
  fireEvent.change(screen.getByLabelText('Your direction'), { target: { value: 'long' } })
  await waitFor(() =>
    expect(mocks.createLine).toHaveBeenCalledWith(
      expect.objectContaining({ title: '200-point stop reference', price: 23800 })
    )
  )
  fireEvent.change(screen.getByLabelText('Actual futures entry'), { target: { value: '24100' } })
  await waitFor(() =>
    expect(mocks.createLine).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Entry reference', price: 24100 })
    )
  )
  expect(mocks.removeLine).toHaveBeenCalledWith(
    expect.objectContaining({ title: 'Entry reference', price: 24000 })
  )
  fireEvent.change(screen.getByLabelText('Your direction'), { target: { value: 'short' } })
  await waitFor(() =>
    expect(mocks.createLine).toHaveBeenCalledWith(
      expect.objectContaining({ title: '200-point stop reference', price: 24300 })
    )
  )
  fireEvent.click(screen.getByRole('button', { name: 'Close Strategy' }))
  fireEvent.click(screen.getByRole('combobox', { name: 'Setup' }))
  fireEvent.click(await screen.findByRole('option', { name: label }))
  expect(screen.getByLabelText('Actual futures entry')).toHaveValue(24100)
  fireEvent.click(screen.getByRole('button', { name: 'Close Strategy' }))
  fireEvent.click(screen.getByRole('combobox', { name: 'Setup' }))
  fireEvent.click(await screen.findByRole('option', { name: 'Off' }))
  expect(mocks.removeLine).toHaveBeenCalledWith(
    expect.objectContaining({ title: '200-point stop reference', price: 24300 })
  )
  fireEvent.click(screen.getByRole('combobox', { name: 'Setup' }))
  fireEvent.click(await screen.findByRole('option', { name: label }))
  await waitFor(() => expect(screen.getByLabelText('Actual futures entry')).toHaveValue(24100))
  mocks.removeLine.mockClear()
  view.unmount()
  expect(mocks.removeLine).toHaveBeenCalledWith(
    expect.objectContaining({ title: 'Entry reference', price: 24100 })
  )
  act(() => useAuthStore.setState({ user: originalUser }))
})
it('keeps option payoff off the premium axis and plots only explicit matching underlying strike guides', async () => {
  vi.mocked(scalpingApi.getExpiry).mockResolvedValue({ status: 'success', data: ['02JAN80'] })
  vi.mocked(scalpingApi.getStrikes).mockImplementation(async (underlying, _exchange, expiry) => ({
    status: 'success',
    underlying,
    expiry_date: expiry,
    fo_exchange: 'NFO',
    atm_strike: 23000,
    chain: [22800, 23000].map((strike) => ({
      strike,
      ce: { symbol: `${strike}CE`, label: '', ltp: 100 },
      pe: { symbol: `${strike}PE`, label: '', ltp: 40 },
    })),
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(
    <QueryClientProvider client={client}>
      <NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" focusMode />
    </QueryClientProvider>
  )
  await waitFor(() => expect(mocks.series[0]?.setData).toHaveBeenCalled())
  fireEvent.click(screen.getByRole('combobox', { name: 'Setup' }))
  fireEvent.click(await screen.findByRole('option', { name: 'A-01 · Nifty Alpha Edge' }))
  await waitFor(() => expect(screen.getByLabelText('Strike price')).toHaveValue('23000'))
  await waitFor(() =>
    expect(
      mocks.createLine.mock.calls.some(
        ([config]) => config.price === 23000 && config.title?.includes('strike')
      )
    ).toBe(true)
  )
  fireEvent.change(screen.getByLabelText('Leg 1 premium'), { target: { value: '100' } })
  fireEvent.change(screen.getByLabelText('Leg 2 premium'), { target: { value: '40' } })
  expect(
    mocks.createLine.mock.calls.some(
      ([config]) => config.price === 60 && config.title?.includes('strike')
    )
  ).toBe(false)
  mocks.removeLine.mockClear()
  view.rerender(
    <QueryClientProvider client={client}>
      <NeoMarketChart symbol="NIFTY03NOV2623000CE" exchange="NFO" interval="15m" focusMode />
    </QueryClientProvider>
  )
  expect(
    mocks.removeLine.mock.calls.some(
      ([config]) => config.price === 23000 && config.title?.includes('strike')
    )
  ).toBe(true)
  fireEvent.click(screen.getByRole('combobox', { name: 'Setup' }))
  fireEvent.click(await screen.findByRole('option', { name: 'A-01 · Nifty Alpha Edge' }))
  mocks.createLine.mockClear()
  await waitFor(() => expect(screen.getByLabelText('Strike price')).toHaveValue('23000'))
  expect(
    screen.getByRole('link', { name: 'Open NIFTY index to view strike guides' })
  ).toHaveAttribute('href', '/trading?symbol=NIFTY&exchange=NSE_INDEX&interval=15m')
  expect(mocks.createLine.mock.calls.some(([config]) => config.title?.includes('strike'))).toBe(
    false
  )
  view.unmount()
})
it('floats the selected template editor on a saved-chart-sized non-fitted chart too', async () => {
  const view = mount()
  await waitFor(() => expect(mocks.series[0]?.setData).toHaveBeenCalled())
  fireEvent.click(screen.getByRole('combobox', { name: 'Setup' }))
  fireEvent.click(await screen.findByRole('option', { name: 'A-01 · Nifty Alpha Edge' }))
  expect(screen.getByRole('dialog', { name: 'Strategy' })).toHaveClass('absolute')
  expect(screen.getByRole('region', { name: 'TradingView candlesticks' })).toHaveClass('flex-1')
  view.unmount()
})

it.each([
  'all',
  'candles',
  'shapes',
  'setups',
  'off',
])('uses one final pattern indicator despite a saved %s legacy mode', (mode) => {
  localStorage.setItem('neo.native.chart.relatedGuide', mode)
  localStorage.setItem('neo.native.chart.patternGuide', 'pinterest-reversals')
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart
        symbol="BTCUSD"
        exchange="DELTA"
        interval="15m"
        studies={['candle-patterns']}
      />
    </QueryClientProvider>
  )
  expect(screen.queryByLabelText('Related image patterns')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Pattern guide')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Unified pattern indicator')).toHaveTextContent('Pattern analysis')
  expect(screen.getByLabelText('Trend analysis')).toBeVisible()
  expect(screen.getByLabelText('Latest pattern reading')).toHaveTextContent('Candle pattern')
  expect(screen.getByRole('checkbox', { name: 'Show neutral patterns' })).not.toBeChecked()
  expect(localStorage.getItem('neo.native.chart.relatedGuide')).toBeNull()
  expect(screen.getByRole('combobox', { name: 'Setup' })).toHaveTextContent('Off')
})

it.each(['candle-patterns','video-strategy-guide'])('reconciles verified Delta history at each live boundary for %s', async (study) => {
  let now = Math.floor(Date.UTC(2026, 9, 15, 9, 50) / 1000)
  vi.mocked(Date.now).mockImplementation(() => now * 1000)
  const stream = (start: number, close = 102) => ({
    symbol: 'BTCUSD',
    interval: '1m',
    connected: true,
    published: now,
    bar: { time: start, open: 100, high: 103, low: 99, close, volume: 1 },
  })
  vi.mocked(useDeltaCandle).mockReturnValue(stream(now) as never)
  vi.mocked(readDeltaHistory).mockImplementation(async () => ({
    ...history,
    symbol: 'BTCUSD',
    exchange: 'DELTA',
    interval: '1m',
    observedAt: now,
    candles: Array.from({ length: 12 }, (_, i) => ({
      time: now - (11 - i) * 60 + 19800,
      open: 100,
      high: 103,
      low: 99,
      close: 102,
      volume: 1,
    })),
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = () => (
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol="BTCUSD"
        exchange="DELTA"
        interval="1m"
        studies={[study]}
      />
    </QueryClientProvider>
  )
  const view = render(content())
  await waitFor(() => expect(readDeltaHistory).toHaveBeenCalled())
  if (study === 'candle-patterns') await waitFor(() =>
    expect(screen.getByLabelText('Latest pattern reading')).not.toHaveTextContent('No completed candle')
  )
  else await waitFor(() => expect(screen.getByRole('group',{name:'Video strategy guide'})).not.toHaveTextContent('Waiting for verified completed candles.'))
  const reads = () =>
    vi
      .mocked(readDeltaHistory)
      .mock.calls.filter((args) => args[0] === 'BTCUSD' && args[1] === '1m' && !args[2]).length
  const initial = reads()
  now += 60
  vi.mocked(useDeltaCandle).mockReturnValue(stream(now) as never)
  view.rerender(content())
  await waitFor(() => expect(reads()).toBe(initial + 1))
  vi.mocked(useDeltaCandle).mockReturnValue(stream(now, 102.5) as never)
  view.rerender(content())
  expect(reads()).toBe(initial + 1)
})

it('shows chart and higher-timeframe trends using the same selected contract and completed candles', async () => {
  const observed = Math.floor(Date.UTC(2026, 9, 15, 12) / 1000)
  vi.mocked(Date.now).mockReturnValue(observed * 1000)
  vi.mocked(readDeltaHistory).mockImplementation(async (selectedSymbol, selectedInterval) => {
    const seconds = selectedInterval === '5m' ? 300 : 60
    return {
      ...history,
      symbol: selectedSymbol,
      exchange: 'DELTA',
      interval: selectedInterval,
      candles: Array.from({ length: 101 }, (_, i) => ({
        time: observed - (100 - i) * seconds + 19800,
        open: 1000 + i * 5,
        high: 1007 + i * 5,
        low: 998 + i * 5,
        close: 1005 + i * 5,
        volume: 10,
      })),
    } as never
  })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart
        symbol="BTCUSD"
        exchange="DELTA"
        interval="1m"
        studies={['candle-patterns']}
      />
    </QueryClientProvider>
  )
  await waitFor(() =>
    expect(screen.getByLabelText('Trend analysis')).toHaveTextContent('5m: Uptrend')
  )
  await waitFor(() =>
    expect(screen.getByLabelText('Trend analysis')).toHaveTextContent('1m: Uptrend')
  )
  expect(screen.getByLabelText('Trend analysis')).toHaveTextContent('Trend agrees')
  expect(screen.getByLabelText('Trend analysis')).not.toHaveTextContent('Need more data')
  expect(
    vi.mocked(readDeltaHistory).mock.calls.some((args) => args[0] === 'BTCUSD' && args[1] === '5m')
  ).toBe(true)
})

it('does not fetch current higher-timeframe candles into replay trend analysis', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="15m"
        studies={['candle-patterns']}
      />
    </QueryClientProvider>
  )
  await waitFor(() => expect(mocks.series[0]?.setData.mock.calls.at(-1)?.[0]).toHaveLength(24))
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(screen.getByLabelText('Trend analysis')).toHaveTextContent(
    'Higher timeframe is off in replay'
  )
  const reads = vi
    .mocked(scalpingApi.getHistory)
    .mock.calls.filter((args) => args[2] === '1h').length
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['neo-trend-history'] })
  })
  expect(
    vi.mocked(scalpingApi.getHistory).mock.calls.filter((args) => args[2] === '1h')
  ).toHaveLength(reads)
})
it('places the trend reading beside the plot instead of inside its candle area', () => {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart
        symbol="BTCUSD"
        exchange="DELTA"
        interval="5m"
        studies={['candle-patterns']}
      />
    </QueryClientProvider>
  )
  const reading = screen.getByLabelText('Latest pattern reading')
  const plot = screen.getByRole('region', { name: 'Chart plot area' })
  expect(plot).toContainElement(screen.getByRole('region', { name: 'TradingView candlesticks' }))
  expect(plot).not.toContainElement(reading)
  expect(plot.parentElement).toContainElement(reading)
})

it('collapses the trend panel and remembers the compact view after reopening the chart', () => {
  const content = () => (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart
        symbol="BTCUSD"
        exchange="DELTA"
        interval="5m"
        studies={['candle-patterns']}
      />
    </QueryClientProvider>
  )
  const view = render(content())
  fireEvent.click(screen.getByRole('button', { name: 'Collapse trend panel' }))
  expect(screen.getByLabelText('Trend analysis')).not.toBeVisible()
  expect(screen.getByRole('button', { name: 'Expand trend panel' })).toHaveAttribute(
    'aria-expanded',
    'false'
  )
  view.unmount()
  render(content())
  expect(screen.getByLabelText('Trend analysis')).not.toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Expand trend panel' }))
  expect(screen.getByLabelText('Trend analysis')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Collapse trend panel' })).toHaveAttribute(
    'aria-expanded',
    'true'
  )
})

it('refreshes completed candles at the close even without another websocket message', async () => {
  let now = Date.UTC(2026, 9, 15, 9, 50, 59, 800) / 1000
  vi.mocked(Date.now).mockImplementation(() => now * 1000)
  vi.mocked(useDeltaCandle).mockReturnValue({
    symbol: 'BTCUSD',
    interval: '1m',
    connected: true,
    published: now,
    bar: { time: Math.floor(now / 60) * 60, open: 100, high: 103, low: 99, close: 102, volume: 1 },
  } as never)
  vi.mocked(readDeltaHistory).mockImplementation(async () => ({
    ...history,
    symbol: 'BTCUSD',
    exchange: 'DELTA',
    interval: '1m',
    candles: Array.from({ length: 12 }, (_, i) => ({
      time: Math.floor(now / 60) * 60 - (11 - i) * 60 + 19800,
      open: 100,
      high: 103,
      low: 99,
      close: 102,
      volume: 1,
    })),
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <NeoMarketChart
        symbol="BTCUSD"
        exchange="DELTA"
        interval="1m"
        studies={['candle-patterns']}
      />
    </QueryClientProvider>
  )
  const reads = () =>
    vi
      .mocked(readDeltaHistory)
      .mock.calls.filter((args) => args[0] === 'BTCUSD' && args[1] === '1m' && !args[2]).length
  await waitFor(() => expect(reads()).toBeGreaterThan(0))
  const initial = reads()
  now = Math.floor(now / 60) * 60 + 60.05
  // Both display and independent execution histories may refresh. No new stream packet: the close timer must fetch the source.
  await waitFor(() => expect(reads()).toBeGreaterThanOrEqual(initial + 1))
})

it('draws completed 1H and 4H levels for the same crypto symbol and shows their values beside the plot', async () => {
  const start = Date.UTC(2026, 10, 1, 0) / 1000,
    now = start + 6.5 * 3600
  vi.mocked(Date.now).mockReturnValue(now * 1000)
  vi.mocked(readDeltaHistory).mockImplementation(async (selectedSymbol, selectedInterval) => ({
    ...history,
    symbol: selectedSymbol,
    exchange: 'DELTA',
    interval: selectedInterval,
    candles:
      selectedInterval === '1h'
        ? Array.from({ length: 8 }, (_, i) => ({
            time: start + i * 3600 + 19800,
            open: 100 + i,
            high: 110 + i,
            low: 90 + i,
            close: 105 + i,
            volume: 100,
          }))
        : Array.from({ length: 12 }, (_, i) => ({
            time: now - (11 - i) * 60 + 19800,
            open: 100,
            high: 103,
            low: 99,
            close: 102,
            volume: 100,
          })),
  }))
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoMarketChart
        symbol="BTCUSD"
        exchange="DELTA"
        interval="1m"
        studies={['candle-patterns']}
      />
    </QueryClientProvider>
  )
  const levels = await screen.findByLabelText('Support and timeframe levels')
  await waitFor(() => expect(levels).toHaveTextContent('4H HIGH'))
  for (const [title, price] of [
    ['1H HIGH', 115],
    ['1H LOW', 95],
    ['4H HIGH', 113],
    ['4H LOW', 90],
  ] as const) {
    expect(mocks.createLine).toHaveBeenCalledWith(
      expect.objectContaining({ title, price, axisLabelVisible: true })
    )
    expect(levels).toHaveTextContent(title)
    expect(levels).toHaveTextContent(String(price))
  }
  expect(screen.getByLabelText('Chart plot area')).not.toContainElement(levels)
  expect(
    vi
      .mocked(readDeltaHistory)
      .mock.calls.filter((args) => args[1] === '1h')
      .every((args) => args[0] === 'BTCUSD')
  ).toBe(true)
})

it('shows Delta trading outside the candle plot and disables it in saved history', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = (savedRange?: { start: string; end: string }) => (
    <QueryClientProvider client={client}>
      <NeoMarketChart symbol="BTCUSD" exchange="DELTA" interval="1m" savedRange={savedRange} />
    </QueryClientProvider>
  )
  const view = render(content())
  const panel = await screen.findByLabelText('Delta trading integration')
  expect(panel).toHaveAttribute('data-enabled', 'true')
  expect(screen.getByLabelText('Chart plot area')).not.toContainElement(panel)
  view.rerender(content({ start: '2026-10-30', end: '2026-10-30' }))
  expect(screen.getByLabelText('Delta trading integration')).toHaveAttribute(
    'data-enabled',
    'false'
  )
})

it('does not mount Delta execution controls on another exchange', () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="5m" />
    </QueryClientProvider>
  )
  expect(screen.queryByLabelText('Delta trading integration')).not.toBeInTheDocument()
})

it('plots actual Delta volume separately below price and keeps RSI below volume through toggles', async () => {
  const fixture = optionFixture('BTCUSD', 'DELTA', true, 51)
  fixture.candles = fixture.candles.map((bar, i) => ({
    ...bar,
    volume: 100 + i,
    open: i % 2 ? bar.close + 1 : bar.close - 1,
  }))
  vi.mocked(readDeltaHistory).mockResolvedValue(fixture)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = (studies: string[]) => (
    <QueryClientProvider client={client}>
      <NeoMarketChart symbol="BTCUSD" exchange="DELTA" interval="1m" studies={studies} focusMode />
    </QueryClientProvider>
  )
  const view = render(content(['volume', 'rsi']))
  await waitFor(() =>
    expect(
      mocks.series.find((s) => s.kind === 'histogram')?.setData.mock.lastCall?.[0]
    ).toHaveLength(51)
  )
  const volume = mocks.series.find((s) => s.kind === 'histogram')!
  expect(volume.pane).toBe(1)
  const points = volume.setData.mock.lastCall![0] as { value: number; color: string }[]
  expect(points[0]).toMatchObject({ value: 100, color: '#26a69a' })
  expect(points[1]).toMatchObject({ value: 101, color: '#ef5350' })
  const rsi = () =>
    mocks.series.filter((s) => s.options?.priceFormat && s.options?.color === '#b39ddb').at(-1)!
  expect(rsi().pane).toBe(2)
  expect((rsi().options!.autoscaleInfoProvider as () => unknown)()).toEqual({
    priceRange: { minValue: 0, maxValue: 100 },
  })
  view.rerender(content(['rsi']))
  await waitFor(() => expect(rsi().pane).toBe(1))
  view.rerender(content(['volume', 'rsi']))
  await waitFor(() => expect(rsi().pane).toBe(2))
})

it('keeps actual live Delta volume and reveals only the replayed candle volumes', async () => {
  const now = Math.floor(Date.now() / 1000 / 60) * 60
  const candles = Array.from({ length: 20 }, (_, i) => ({
    time: now - (19 - i) * 60 + 19800,
    open: 100,
    high: 105,
    low: 99,
    close: 102,
    volume: 10 + i,
  }))
  vi.mocked(readDeltaHistory).mockImplementation(async () => ({
    ...history,
    symbol: 'BTCUSD',
    exchange: 'DELTA',
    interval: '1m',
    observedAt: now,
    candles,
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = () => (
    <QueryClientProvider client={client}>
      <NeoMarketChart symbol="BTCUSD" exchange="DELTA" interval="1m" studies={['volume', 'rsi']} />
    </QueryClientProvider>
  )
  const view = render(content())
  const histogram = () => mocks.series.find((s) => s.kind === 'histogram')!
  await waitFor(() => expect(histogram()?.setData.mock.lastCall?.[0]).toHaveLength(20))
  vi.mocked(useDeltaCandle).mockReturnValue({
    symbol: 'BTCUSD',
    interval: '1m',
    connected: true,
    published: now,
    bar: { time: now, open: 100, high: 105, low: 99, close: 104, volume: 99 },
  } as never)
  view.rerender(content())
  await waitFor(() =>
    expect(histogram().setData.mock.lastCall?.[0].at(-1)).toMatchObject({ value: 99 })
  )
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  await waitFor(() => expect(histogram().setData.mock.lastCall?.[0]).toHaveLength(1))
  expect(histogram().setData.mock.lastCall?.[0][0]).toMatchObject({ value: 10 })
  fireEvent.click(screen.getByRole('button', { name: 'Next replay candle' }))
  await waitFor(() => expect(histogram().setData.mock.lastCall?.[0]).toHaveLength(2))
  expect(histogram().setData.mock.lastCall?.[0][1]).toMatchObject({ value: 11 })
})

it('draws EMA 9/15/21 independently and completed-day Fibonacci levels, then clears them when disabled', async () => {
  const asOf = Date.UTC(2026, 9, 15, 9, 50) / 1000
  vi.mocked(Date.now).mockReturnValue(asOf * 1000)
  vi.mocked(readDeltaHistory).mockImplementation(async (_symbol, interval) => ({
    status: 'success',
    symbol: 'BTCUSD',
    exchange: 'DELTA',
    interval,
    date: null,
    candles:
      interval === '1d'
        ? [
            {
              time: Date.UTC(2026, 9, 14) / 1000 + 19800,
              open: 100,
              high: 120,
              low: 90,
              close: 110,
              volume: 1,
            },
            {
              time: Date.UTC(2026, 9, 15) / 1000 + 19800,
              open: 1000,
              high: 2000,
              low: 900,
              close: 1500,
              volume: 1,
            },
          ]
        : Array.from({ length: 60 }, (_, i) => ({
            time: asOf - (60 - i) * 60 + 19800,
            open: 100 + i,
            high: 103 + i,
            low: 99 + i,
            close: 102 + i,
            volume: 1,
          })),
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = (studies: string[]) => (
    <QueryClientProvider client={client}>
      <NeoMarketChart symbol="BTCUSD" exchange="DELTA" interval="1m" studies={studies} />
    </QueryClientProvider>
  )
  const view = render(content(['ema-9-15', 'fibonacci-pivots']))
  await waitFor(() =>
    expect(mocks.createLine).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Fib P', price: (120 + 90 + 110) / 3 })
    )
  )
  const emaSeries = mocks.series.filter(
    (s) => ['#3b82f6', '#ef5350', '#a855f7'].includes(s.options?.color)
  )
  expect(emaSeries.some((s) => (s.setData.mock.calls.at(-1)?.[0]?.length ?? 0) > 0)).toBe(true)
  const ema21 = emaSeries.find(s => s.options?.color === '#a855f7')
  expect(ema21).toBeDefined()
  expect(ema21?.setData.mock.calls.at(-1)?.[0]?.length).toBeGreaterThan(0)
  expect(ema21?.applyOptions).toHaveBeenCalledWith(expect.objectContaining({ title: 'EMA 21', visible: true }))
  expect(
    mocks.createLine.mock.calls.some(
      ([line]) => line.title === 'Fib R3' && line.price === (120 + 90 + 110) / 3 + 30
    )
  ).toBe(true)
  view.rerender(content([]))
  await waitFor(() =>
    expect(emaSeries.every((s) => s.setData.mock.calls.at(-1)?.[0]?.length === 0)).toBe(true)
  )
  expect(mocks.removeLine).toHaveBeenCalledWith(expect.objectContaining({ title: 'Fib P' }))
  view.unmount()
  client.clear()
})

it('keeps 1m/5m execution independent of a 15m or 1h display and hidden pattern studies', async () => {
  const observed = Date.UTC(2026, 10, 2, 3) / 1000 + 1
  vi.mocked(Date.now).mockReturnValue(observed * 1000)
  vi.mocked(readDeltaHistory).mockImplementation(async (symbol, interval) => {
    const seconds =
      ({ '1m': 60, '5m': 300, '15m': 900, '1h': 3600 } as Record<string, number>)[interval] ?? 60
    const end = Math.floor(observed / seconds) * seconds
    return {
      ...history,
      symbol,
      exchange: 'DELTA',
      interval,
      candles: Array.from({ length: 101 }, (_, i) => ({
        time: end - (100 - i) * seconds + 19800,
        open: 1000 + i * 5,
        high: 1007 + i * 5,
        low: 998 + i * 5,
        close: 1005 + i * 5,
        volume: 1,
      })),
    } as never
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = (interval: string) => (
    <QueryClientProvider client={client}>
      <NeoMarketChart symbol="BTCUSD" exchange="DELTA" interval={interval} studies={[]} />
    </QueryClientProvider>
  )
  const view = render(content('15m'))
  const panel = screen.getByLabelText('Delta trading integration')
  await waitFor(() => expect(panel).toHaveAttribute('data-risk-seconds', '60'))
  await waitFor(() => expect(panel).toHaveAttribute('data-risk-aligned', 'true'))
  expect(panel).toHaveAttribute('data-execution-mode', 'scalp-1m-5m-v1')
  view.rerender(content('1h'))
  await waitFor(() => expect(panel).toHaveAttribute('data-risk-seconds', '60'))
  await waitFor(() => expect(panel).toHaveAttribute('data-risk-aligned', 'true'))
  expect(vi.mocked(readDeltaHistory).mock.calls.some((c) => c[1] === '5m')).toBe(true)
})

it('keeps EMA closed OHLC in UTC across live ticks and confirms the final candle on history refresh', async () => {
  const now = Math.floor(Date.now() / 1000 / 60) * 60
  const candles = Array.from({ length: 31 }, (_, i) => ({
    time: now - (30 - i) * 60 + 19800,
    open: 100 + i, high: 103 + i, low: 99 + i, close: 102 + i, volume: 1,
  }))
  const response = { ...history, symbol: 'BTCUSD', exchange: 'DELTA', interval: '1m', observedAt: now, candles }
  vi.mocked(readDeltaHistory).mockResolvedValue(response)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = () => <QueryClientProvider client={client}>
    <NeoMarketChart symbol="BTCUSD" exchange="DELTA" interval="1m" studies={['ema-9-15']} />
  </QueryClientProvider>
  const view = render(content())
  await waitFor(() => expect(vi.mocked(loadEmaBackfill).mock.calls.at(-1)?.[0].length).toBeGreaterThan(0))
  const baseline = vi.mocked(loadEmaBackfill).mock.calls.at(-1)![0]
  expect(baseline).toHaveLength(30)
  expect(baseline.at(-1)).toMatchObject({ time: now - 60, open: 129, high: 132, low: 128, close: 131 })
  expect(vi.mocked(loadEmaBackfill).mock.calls.at(-1)![2]).toEqual({ intervalSeconds: 60 })
  await act(async () => { await Promise.resolve() })
  const count = vi.mocked(loadEmaBackfill).mock.calls.length
  for (const close of [133, 134]) {
    vi.mocked(useDeltaCandle).mockReturnValue({ connected: true, symbol:'BTCUSD',interval:'1m',published:now,
      bar:{time:now,open:130,high:close+1,low:129,close,volume:2} } as never)
    view.rerender(content())
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 175)) })
    expect(loadEmaBackfill).toHaveBeenCalledTimes(count)
  }
  vi.mocked(Date.now).mockReturnValue((now + 60) * 1000)
  await act(async () => {
    client.setQueryData(['neo-tv-history','DELTA','BTCUSD','1m',undefined,undefined], {...response,observedAt:now+60})
  })
  await waitFor(() => expect(vi.mocked(loadEmaBackfill).mock.calls.at(-1)![0].at(-1)?.time).toBe(now))
  expect(vi.mocked(loadEmaBackfill).mock.calls.at(-1)![0]).toHaveLength(31)
  view.unmount()
  client.clear()
})

it('requests index alignment markers with the real display interval across session gaps', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(<QueryClientProvider client={client}>
    <NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" studies={['ema-9-15']} />
  </QueryClientProvider>)
  await waitFor(() => expect(vi.mocked(loadEmaBackfill).mock.calls.some(([candles,,options]) =>
    candles.length > 0 && options?.intervalSeconds === 900 && options.allowSessionGaps === true
  )).toBe(true))
  view.unmount()
  client.clear()
})


it('shows advisory Trade guide without changing execution controls', async () => {
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><NeoMarketChart symbol="BTCUSD" exchange="DELTA" interval="5m" fitViewport /></QueryClientProvider>)
  expect(await screen.findByRole('group', {name: 'Trade guide'})).toBeInTheDocument()
  expect(screen.getByLabelText('Delta trading integration')).toHaveAttribute('data-execution-mode', 'scalp-1m-5m-v1')
})

it('defaults to ten confirmed pattern candles and offers explicit history and preview choices', () => {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <NeoMarketChart symbol="BTCUSD" exchange="DELTA" interval="15m" studies={['candle-patterns']} />
  </QueryClientProvider>)
  const historyChoice = screen.getByRole('checkbox', { name: 'Show all historical patterns' })
  const previewChoice = screen.getByRole('checkbox', { name: 'Show unconfirmed patterns' })
  expect(historyChoice).not.toBeChecked()
  expect(previewChoice).not.toBeChecked()
  expect(screen.getByLabelText('Unified pattern indicator')).toHaveTextContent('Last 10 candles')
  fireEvent.click(historyChoice)
  expect(historyChoice).toBeChecked()
  expect(screen.getByLabelText('Unified pattern indicator')).toHaveTextContent('All history')
  fireEvent.click(previewChoice)
  expect(screen.getByLabelText('Unified pattern indicator')).toHaveTextContent('Unconfirmed previews on')
  fireEvent.click(historyChoice)
  expect(screen.getByLabelText('Unified pattern indicator')).toHaveTextContent('Last 10 candles')
})

it('offers all video methods independently of candle patterns and resets the selection with chart scope', () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = (symbol: string) => <QueryClientProvider client={client}><NeoMarketChart symbol={symbol} exchange="DELTA" interval="1m" studies={['video-strategy-guide']} /></QueryClientProvider>
  const view = render(content('BTCUSD'))
  const selector = screen.getByRole('combobox', { name: 'Strategy from video' })
  expect(selector.querySelectorAll('option')).toHaveLength(16)
  fireEvent.change(selector, { target: { value: 'krm' } })
  expect(selector).toHaveValue('krm')
  view.rerender(content('ETHUSD'))
  expect(screen.getByRole('combobox', { name: 'Strategy from video' })).toHaveValue('')
  expect(screen.queryByLabelText('Unified pattern indicator')).not.toBeInTheDocument()
})

// Independent book guide integration; old study selections and old engines remain separate.
import { BookPatternEngine } from '../book-pattern-guide/engine'
import { BookPatternLayer } from '../book-pattern-guide/BookPatternLayer'
it('runs the independent book guide without older pattern studies and keeps UTC/quote evidence separate',async()=>{
 const reconcile=vi.spyOn(BookPatternEngine.prototype,'reconcile')
 const view=render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" studies={['book-pattern-risk-guide']}/></QueryClientProvider>)
 await screen.findByLabelText('Book patterns and risk guide')
 await waitFor(()=>expect(reconcile.mock.calls.some(c=>c[0].length>0)).toBe(true))
 const call=reconcile.mock.calls.filter(c=>c[0].length>0).at(-1)!
 expect(call[0][0].time).toBe(history.candles[0].time-19800)
 expect(call[1]).toMatchObject({symbol:'NIFTY',exchange:'NSE_INDEX',intervalSeconds:900,sourceReady:true,quoteObservedAt:0})
 expect(call[1].observedAt).toBe(Date.now()/1000)
 expect(screen.queryByLabelText('Video strategy guide')).not.toBeInTheDocument()
 view.unmount();reconcile.mockRestore()
})
it('clears the book layer on disable and destroys it on identity change without losing old selections',async()=>{
 const update=vi.spyOn(BookPatternLayer.prototype,'update'),destroy=vi.spyOn(BookPatternLayer.prototype,'destroy')
 localStorage.setItem('neo.native.chart.indicators','["rsi","book-pattern-risk-guide"]')
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 const tree=(symbol:string,studies:string[])=><QueryClientProvider client={client}><NeoMarketChart symbol={symbol} exchange="NSE_INDEX" interval="15m" studies={studies}/></QueryClientProvider>
 const view=render(tree('NIFTY',['rsi','book-pattern-risk-guide']))
 await screen.findByLabelText('Book patterns and risk guide')
 view.rerender(tree('NIFTY',['rsi']))
 await waitFor(()=>expect(update.mock.calls.at(-1)?.[0]).toBeNull())
 expect(screen.queryByLabelText('Book patterns and risk guide')).not.toBeInTheDocument()
 view.rerender(tree('BANKNIFTY',['rsi','book-pattern-risk-guide']))
 await waitFor(()=>expect(destroy).toHaveBeenCalled())
 expect(localStorage.getItem('neo.native.chart.indicators')).toBe('["rsi","book-pattern-risk-guide"]')
 view.unmount();update.mockRestore();destroy.mockRestore()
})
it('does not add the book study to a fresh uncontrolled chart',async()=>{
 mount()
 await waitFor(()=>expect(mocks.series[0]?.setData).toHaveBeenCalled())
 expect(screen.queryByLabelText('Book patterns and risk guide')).not.toBeInTheDocument()
 expect(JSON.parse(localStorage.getItem('neo.native.chart.indicators')!)).not.toContain('book-pattern-risk-guide')
})

it('drops manually confirmed book units on symbol change while retaining price context and adapting interval',async()=>{
 const reconcile=vi.spyOn(BookPatternEngine.prototype,'reconcile')
 localStorage.setItem('neo.book-pattern-risk-guide.v1',JSON.stringify({instrumentScope:'NSE_INDEX:NIFTY',settings:{equity:250000},instrument:{kind:'linear',unitDefinition:'contract',accountCurrency:'INR',quoteCurrency:'INR',valuePerPriceUnit:2,quantityStep:1}}))
 vi.mocked(scalpingApi.getHistory).mockImplementation(async(symbol,exchange,interval)=>({...history,symbol,exchange,interval}))
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 const tree=(symbol:string,interval:string)=><QueryClientProvider client={client}><NeoMarketChart symbol={symbol} exchange="NSE_INDEX" interval={interval} studies={['book-pattern-risk-guide']}/></QueryClientProvider>
 const view=render(tree('NIFTY','15m'))
 await waitFor(()=>expect(reconcile.mock.calls.some(c=>c[1].instrument?.valuePerPriceUnit===2)).toBe(true))
 view.rerender(tree('BANKNIFTY','5m'))
 await waitFor(()=>expect(reconcile.mock.calls.some(c=>c[1].symbol==='BANKNIFTY'&&c[0].length>0&&c[1].sourceReady)).toBe(true))
 const call=reconcile.mock.calls.filter(c=>c[1].symbol==='BANKNIFTY'&&c[0].length>0).at(-1)!
 expect(call[1].instrument).toBeUndefined()
 expect(call[1].intervalSeconds).toBe(300)
 expect(call[2]?.equity).toBe(250000)
 expect(call[0][0].close).toBe(100)
 expect(screen.getByLabelText('Money per price unit')).toHaveValue(null)
 view.unmount();reconcile.mockRestore()
})


it('book source failure retains real 104 references, fixed completion, recovery suppression and identity isolation', async () => {
 const { bar, trendBars } = await import('../book-pattern-guide/fixtures')
 const start=Date.UTC(2026,9,15,3,45)/1000
 const candles=[...trendBars('short'),bar(100,110,99.9,102),bar(102.5,105,102.3,104)].map((b,i)=>({...b,time:start+19800+i*60}))
 const end=start+candles.length*60
 vi.mocked(Date.now).mockReturnValue(end*1000)
 mocks.market.mockReturnValue({data:new Map([['NSE_INDEX:NIFTY',{data:{ltp:104,timestamp:Date.now()}}]]),isConnected:true})
 vi.mocked(scalpingApi.getHistory).mockImplementation(async(symbol,exchange,interval)=>({...history,symbol,exchange,interval,candles}))
 const update=vi.spyOn(BookPatternLayer.prototype,'update')
 const reconcile=vi.spyOn(BookPatternEngine.prototype,'reconcile')
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 const tree=(symbol:string,title:string)=><QueryClientProvider client={client}><NeoMarketChart symbol={symbol} title={title} exchange="NSE_INDEX" interval="1m" studies={['book-pattern-risk-guide']}/></QueryClientProvider>
 const view=render(tree('NIFTY','Initial book history'))
 await waitFor(()=>expect(update.mock.calls.at(-1)?.[0]?.activePlan?.entry).toBe(104))
 const first=structuredClone(update.mock.calls.at(-1)![0]!.activePlan)
 vi.mocked(scalpingApi.getHistory).mockRejectedValue(Error('Transient book history failure'))
 vi.mocked(Date.now).mockReturnValue((end+120)*1000)
 await act(async()=>{await client.invalidateQueries({queryKey:['neo-tv-history']})})
 await waitFor(()=>expect(update.mock.calls.at(-1)?.[0]?.readiness).toBe('unavailable'))
 expect(reconcile.mock.calls.at(-1)?.[1]).toMatchObject({sourceReady:false,observedAt:0})
 expect(update.mock.calls.at(-1)?.[0]?.activePlan).toEqual(first)
 expect(screen.getByLabelText('Book compact summary')).toHaveTextContent('Entry 104')
 expect(screen.getByLabelText('Book compact summary')).toHaveTextContent('Data unavailable')
 expect(update.mock.calls.at(-1)?.[0]?.alerts).toEqual([])
 vi.mocked(scalpingApi.getHistory).mockImplementation(async(symbol,exchange,interval)=>({...history,symbol,exchange,interval,candles}))
 mocks.market.mockReturnValue({data:new Map([['NSE_INDEX:NIFTY',{data:{ltp:104,timestamp:Date.now()}}]]),isConnected:true})
 view.rerender(tree('NIFTY','Recovered book history'))
 await act(async()=>{await client.invalidateQueries({queryKey:['neo-tv-history']})})
 await waitFor(()=>expect(reconcile.mock.calls.at(-1)?.[1].sourceReady).toBe(true))
 expect(update.mock.calls.at(-1)?.[0]?.activePlan).toEqual(first)
 expect(update.mock.calls.at(-1)?.[0]?.alerts).toEqual([])
 const catchup=[...candles,{...bar(104,120,103,118),time:end+19800}]
 vi.mocked(Date.now).mockReturnValue((end+180)*1000)
 vi.mocked(scalpingApi.getHistory).mockImplementation(async(symbol,exchange,interval)=>({...history,symbol,exchange,interval,candles:catchup}))
 await act(async()=>{await client.invalidateQueries({queryKey:['neo-tv-history']})})
 await waitFor(()=>expect(update.mock.calls.at(-1)?.[0]?.lastTerminalPlan?.entry).toBe(104))
 expect(update.mock.calls.at(-1)?.[0]?.alerts).toEqual([])
 vi.mocked(scalpingApi.getHistory).mockRejectedValue(Error('Other symbol has no verified source'))
 view.rerender(tree('BANKNIFTY','New identity'))
 await waitFor(()=>expect(reconcile.mock.calls.at(-1)?.[1].symbol).toBe('BANKNIFTY'))
 expect(update.mock.calls.at(-1)?.[0]?.activePlan).toBeUndefined()
 view.unmount();update.mockRestore();reconcile.mockRestore()
})

//51-strategy study: independent source clocks, settings and layer ownership.
import { Strategy51Engine } from '../strategy51-guide/engine'
import { Strategy51Layer } from '../strategy51-guide/Strategy51Layer'
it('51 strategy integration evaluates verified UTC candles without enabling or changing the old Book study',async()=>{
 const reconcile=vi.spyOn(Strategy51Engine.prototype,'reconcile'),oldBook=vi.spyOn(BookPatternEngine.prototype,'reconcile')
 const view=render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" studies={['strategies-51-guide']}/></QueryClientProvider>)
 await screen.findByLabelText('51 strategies compact guide')
 await waitFor(()=>expect(reconcile.mock.calls.some(c=>c[0].length>0&&c[1].sourceReady)).toBe(true))
 const call=reconcile.mock.calls.filter(c=>c[0].length>0&&c[1].sourceReady).at(-1)!
 expect(call[0][0].time).toBe(history.candles[0].time-19800)
 expect(call[1]).toMatchObject({symbol:'NIFTY',exchange:'NSE_INDEX',intervalSeconds:900})
 expect(oldBook).not.toHaveBeenCalled()
 expect(screen.queryByLabelText('Book patterns and risk guide')).not.toBeInTheDocument()
 view.unmount();reconcile.mockRestore();oldBook.mockRestore()
})
it('51 strategy integration clears only its layer on disable and destroys owned drawings on unmount',async()=>{
 const update=vi.spyOn(Strategy51Layer.prototype,'update'),destroy=vi.spyOn(Strategy51Layer.prototype,'destroy')
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}}),tree=(ids:string[])=><QueryClientProvider client={client}><NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" studies={ids}/></QueryClientProvider>
 const view=render(tree(['rsi','strategies-51-guide']))
 await screen.findByLabelText('51 strategies compact guide')
 view.rerender(tree(['rsi']))
 await waitFor(()=>expect(update.mock.calls.at(-1)?.[0]).toBeNull())
 expect(screen.queryByLabelText('51 strategies compact guide')).not.toBeInTheDocument()
 view.unmount();expect(destroy).toHaveBeenCalled();update.mockRestore();destroy.mockRestore()
})
it('51 strategy guide coexists with the preserved Book guide without duplicate component identities',async()=>{
 localStorage.setItem('neo.strategy51-guide.v1',JSON.stringify({version:1,settings:{cleanChart:false}}))
 const errors=vi.spyOn(console,'error').mockImplementation(()=>{})
 const view=render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" studies={['book-pattern-risk-guide','strategies-51-guide']}/></QueryClientProvider>)
 await screen.findByLabelText('51 strategies compact guide')
 expect(screen.getByLabelText('Book patterns and risk guide')).toBeInTheDocument()
 expect(errors.mock.calls.filter(args=>args.join(' ').includes('same key'))).toEqual([])
 view.unmount();errors.mockRestore()
})

it('51 clean view hides overlapping guides temporarily and restores them when the new study is disabled',async()=>{
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 const tree=(ids:string[])=><QueryClientProvider client={client}><NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" studies={ids}/></QueryClientProvider>
 localStorage.setItem('neo.native.chart.indicators','["book-pattern-risk-guide","rsi"]')
 const view=render(tree(['book-pattern-risk-guide','rsi','strategies-51-guide']))
 await screen.findByLabelText('51 strategies compact guide')
 expect(screen.queryByLabelText('Book patterns and risk guide')).not.toBeInTheDocument()
 expect(screen.queryByLabelText('Trend analysis')).not.toBeInTheDocument()
 expect(screen.queryByRole('group',{name:'Trade guide'})).not.toBeInTheDocument()
 expect(localStorage.getItem('neo.native.chart.indicators')).toBe('["book-pattern-risk-guide","rsi"]')
 view.rerender(tree(['book-pattern-risk-guide','rsi']))
 await screen.findByLabelText('Book patterns and risk guide')
 view.unmount();client.clear()
})

it('51 clean view clears the competing automatic preview levels and restores them when disabled',async()=>{
 vi.spyOn(await import('./chartTradePlan'),'calculateEntryPlan').mockReturnValue({plan:{entry:100,stop:95,target:110,direction:'long',asOf:Date.now()/1000}} as never)
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 const tree=(ids:string[])=><QueryClientProvider client={client}><NeoMarketChart symbol="NIFTY" exchange="NSE_INDEX" interval="15m" studies={ids} fitViewport/></QueryClientProvider>
 const view=render(tree([]))
 await waitFor(()=>expect(mocks.createLine.mock.calls.some(([line])=>line.title==='Entry (preview)')).toBe(true))
 const prior=mocks.createLine.mock.results.filter(r=>r.type==='return').map(r=>r.value).filter(line=>['Entry (preview)','SL (preview)','Target 1:2'].includes(line.title)).slice(-3)
 mocks.removeLine.mockClear()
 mocks.createLine.mockClear()
 view.rerender(tree(['strategies-51-guide']))
 await screen.findByLabelText('51 strategies compact guide')
 await waitFor(()=>expect(prior.every(line=>mocks.removeLine.mock.calls.some(([removed])=>removed===line))).toBe(true))
 expect(mocks.createLine.mock.calls.filter(([line])=>['Entry (preview)','SL (preview)','Target 1:2'].includes(line.title??''))).toHaveLength(0)
 view.rerender(tree([]))
 await waitFor(()=>expect(mocks.createLine.mock.calls.filter(([line])=>line.title==='Entry (preview)').length).toBeGreaterThan(0))
 view.unmount();client.clear()
})
