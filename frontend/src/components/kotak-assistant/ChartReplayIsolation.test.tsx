import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render as renderView, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { candleKey, useChartCandles } from './chartCandleStore'
import { KotakAssistantChart } from './KotakAssistantChart'

const io = vi.hoisted(() => ({
  candles: vi.fn(),
  historyRequests: vi.fn(),
  subscriptions: vi.fn(),
  ticks: vi.fn(),
  lines: vi.fn(() => ({})),
  markers: vi.fn(() => ({ detach: vi.fn() })),
  history: [] as {
    time: number
    open: number
    high: number
    low: number
    close: number
    volume: number
  }[],
  quote: new Map(),
  calendarError: false,
}))
vi.mock('@/api/admin', () => ({
  adminApi: {
    checkTimings: async (date: string) => {
      if (io.calendarError) throw Error('Calendar offline')
      return {
        date,
        timings:
          date === '2026-10-20' || [0, 6].includes(new Date(`${date}T00:00Z`).getUTCDay())
            ? []
            : [{ exchange: 'NFO', start_time: '09:15', end_time: '15:40' }],
      }
    },
  },
}))
vi.mock('@/api/scalping', () => ({
  scalpingApi: { getHistory: async () => { io.historyRequests(); return { status: 'success', candles: io.history } } },
}))
vi.mock('@/hooks/useMarketData', () => ({ useMarketData: (options: unknown) => { io.subscriptions(options); return { data: io.quote } } }))
vi.mock('lightweight-charts', async (load) => ({
  ...(await load<typeof import('lightweight-charts')>()),
  createSeriesMarkers: io.markers,
  createChart: () => {
    let count = 0
    const scale = { applyOptions: vi.fn() }
    return {
      addSeries: () => {
        const candle = count++ === 0
        return {
          applyOptions: vi.fn(),
          priceScale: () => scale,
          createPriceLine: io.lines,
          removePriceLine: vi.fn(),
          priceToCoordinate: () => 50,
          setData: candle ? io.candles : vi.fn(),
          update: candle ? io.ticks : vi.fn(),
        }
      },
      panes: () => [{ setHeight: vi.fn() }, { setHeight: vi.fn() }],
      timeScale: () => ({
        subscribeVisibleLogicalRangeChange: vi.fn(),
        getVisibleLogicalRange: () => null,
        setVisibleLogicalRange: vi.fn(),
        scrollToPosition: vi.fn(),
      }),
      priceScale: () => scale,
      applyOptions: vi.fn(),
      subscribeCrosshairMove: vi.fn(),
      remove: vi.fn(),
    }
  },
}))
const symbol = 'NIFTY19OCT2622600CE'
function render(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return renderView(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}
function CacheReadout() {
  const bars = useChartCandles(candleKey(undefined, 'live', symbol, 'NFO', '5m'))
  return (
    <output aria-label="Live cache">
      {bars.length} bars · {bars.at(-1)?.close}
    </output>
  )
}
describe('Chart replay data isolation', () => {
  afterEach(() => vi.useRealTimers())
  beforeEach(() => {
    vi.clearAllMocks()
    io.quote = new Map()
    io.calendarError = false
    useThemeStore.setState({ appMode: 'live' })
    useAuthStore.setState({ user: null })
  })
  it('reveals only replay candles while live candles, cache and fills remain isolated', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-16T10:00:30+05:30'))
    const now = Math.floor(Date.now() / 1000)
    const current = Math.floor((now + 19800) / 300) * 300
    io.history = Array.from({ length: 10 }, (_, i) => ({
      time: current - (10 - i) * 300,
      open: 100,
      high: 105,
      low: 99,
      close: 102,
      volume: 100,
    }))
    const base = {
      symbol,
      exchange: 'NFO',
      interval: '5m',
      levels: [{ price: 300, title: 'Future ticket entry', color: 'blue' }],
      markers: [{ time: current - 19800 - 600, action: 'BUY', price: 102 }],
    }
    const view = render(
      <>
        <KotakAssistantChart {...base} />
        <CacheReadout />
      </>
    )
    await act(async () => {})
    expect(io.candles.mock.lastCall?.[0]).toHaveLength(10)
    const replay = {
      bars: io.history.map((b) => ({ ...b })),
      until: current - 7 * 300,
      seconds: 300,
    }
    view.rerender(
      <>
        <KotakAssistantChart {...base} replay={replay} />
        <CacheReadout />
      </>
    )
    expect(io.candles.mock.lastCall?.[0]).toHaveLength(3)
    expect(screen.getByLabelText('Live cache')).toHaveTextContent('10 bars')
    expect(io.markers.mock.lastCall?.[1]).toEqual([])
    expect(screen.queryByText(/FUTURE TICKET ENTRY/)).not.toBeInTheDocument()
    const writes = io.candles.mock.calls.length
    io.quote = new Map([
      [
        `NFO:${symbol}`,
        { data: { ltp: 107, timestamp: now, volume: 1500 }, updateSource: 'websocket' },
      ],
    ])
    view.rerender(
      <>
        <KotakAssistantChart {...base} title="Live tick delivered" replay={replay} />
        <CacheReadout />
      </>
    )
    expect(screen.getByLabelText('Live cache')).toHaveTextContent('11 bars · 107')
    expect(io.candles).toHaveBeenCalledTimes(writes)
    expect(io.ticks).not.toHaveBeenCalled()
    expect(within(screen.getByRole('region')).getByText(/REPLAY/)).toBeInTheDocument()
    view.rerender(
      <>
        <KotakAssistantChart {...base} />
        <CacheReadout />
      </>
    )
    expect(io.candles.mock.lastCall?.[0]).toHaveLength(11)
    expect(io.candles.mock.lastCall?.[0].at(-1).close).toBe(107)
  })
  it('confirms a Fair Value Gap at candle close even without another tick', async () => {
    vi.useFakeTimers()
    const start = Date.UTC(2026, 9, 15, 9, 15) / 1000
    vi.setSystemTime((start + 800 - 19800) * 1000)
    io.history = [
      { time: start, open: 100, high: 101, low: 99, close: 100, volume: 100 },
      { time: start + 300, open: 101, high: 110, low: 100, close: 108, volume: 100 },
      { time: start + 600, open: 108, high: 111, low: 105, close: 109, volume: 100 },
    ]
    render(<KotakAssistantChart symbol={symbol} exchange="NFO" interval="5m" />)
    await act(async () => {})
    expect(screen.getByText('FVG ↑0 ↓0')).toBeInTheDocument()
    await act(async () => vi.advanceTimersByTimeAsync(101000))
    expect(screen.getByText('FVG ↑1 ↓0')).toBeInTheDocument()
  })
  it('does not create or fill an FVG with candles still hidden by replay', async () => {
    const start = Math.floor((Date.now() / 1000 + 19800) / 300) * 300 - 3000
    io.history = [
      { time: start, open: 100, high: 101, low: 99, close: 100, volume: 100 },
      { time: start + 300, open: 101, high: 110, low: 100, close: 108, volume: 100 },
      { time: start + 600, open: 108, high: 111, low: 105, close: 109, volume: 100 },
      { time: start + 900, open: 109, high: 110, low: 99, close: 100, volume: 100 },
    ]
    const props = { symbol, exchange: 'NFO', interval: '5m' }
    const view = render(<KotakAssistantChart {...props} />)
    await act(async () => {})
    expect(screen.getByText('FVG ↑0 ↓0')).toBeInTheDocument()
    view.rerender(
      <KotakAssistantChart
        {...props}
        replay={{ bars: io.history, seconds: 300, until: start + 600 }}
      />
    )
    expect(screen.getByText('FVG ↑0 ↓0')).toBeInTheDocument()
    view.rerender(
      <KotakAssistantChart
        {...props}
        replay={{ bars: io.history, seconds: 300, until: start + 900 }}
      />
    )
    expect(screen.getByText('FVG ↑1 ↓0')).toBeInTheDocument()
    view.rerender(
      <KotakAssistantChart
        {...props}
        replay={{ bars: io.history, seconds: 300, until: start + 1200 }}
      />
    )
    expect(screen.getByText('FVG ↑0 ↓0')).toBeInTheDocument()
  })
  it.each([
    ['before opening', '2026-10-16T08:50:30+05:30'],
    ['after closing', '2026-10-16T18:00:30+05:30'],
    ['on an exchange holiday', '2026-10-20T10:00:30+05:30'],
  ])('keeps official history without making fresh-looking bars %s', async (_label, date) => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(date))
    const now = Date.now() / 1000
    const current = Math.floor((now + 19800) / 300) * 300
    io.history = [{ time: current - 300, open: 100, high: 105, low: 99, close: 102, volume: 100 }]
    const props = { symbol, exchange: 'NFO', interval: '5m' }
    const view = render(<KotakAssistantChart {...props} />)
    await act(async () => vi.advanceTimersByTimeAsync(1))
    io.quote = new Map([
      [`NFO:${symbol}`, { data: { ltp: 107, timestamp: now }, updateSource: 'websocket' }],
    ])
    view.rerender(<KotakAssistantChart {...props} title="Tick after history" />)
    expect(io.ticks).not.toHaveBeenCalled()
    expect(io.candles.mock.lastCall?.[0]).toEqual([
      { time: current - 300, open: 100, high: 105, low: 99, close: 102 },
    ])
    expect(screen.getByText(/Market closed · historical candles/)).toBeInTheDocument()
  })
  it('does not reuse the old exchange timestamp when REST refreshes a price', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-16T10:00:30+05:30'))
    const now = Date.now() / 1000
    const current = Math.floor((now + 19800) / 300) * 300
    io.history = [{ time: current - 300, open: 100, high: 105, low: 99, close: 102, volume: 100 }]
    const props = { symbol, exchange: 'NFO', interval: '5m' }
    const view = render(<KotakAssistantChart {...props} />)
    await act(async () => vi.advanceTimersByTimeAsync(1))
    io.quote = new Map([
      [`NFO:${symbol}`, { data: { ltp: 107, timestamp: now }, updateSource: 'websocket' }],
    ])
    view.rerender(<KotakAssistantChart {...props} title="Exchange tick" />)
    expect(io.ticks.mock.lastCall?.[0].close).toBe(107)
    const writes = io.ticks.mock.calls.length
    io.quote = new Map([
      [
        `NFO:${symbol}`,
        { data: { ltp: 190, timestamp: now }, updateSource: 'rest', lastUpdate: Date.now() + 1000 },
      ],
    ])
    view.rerender(<KotakAssistantChart {...props} title="REST receipt" />)
    expect(io.ticks).toHaveBeenCalledTimes(writes)
    expect(io.ticks.mock.lastCall?.[0].close).toBe(107)
  })
  it('keeps historical candles visible when the exchange calendar is unavailable', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-16T10:00:30+05:30'))
    io.calendarError = true
    const now = Date.now() / 1000
    const current = Math.floor((now + 19800) / 300) * 300
    io.history = [{ time: current - 300, open: 100, high: 105, low: 99, close: 102, volume: 100 }]
    const props = { symbol, exchange: 'NFO', interval: '5m' }
    const view = render(<KotakAssistantChart {...props} />)
    await act(async () => vi.advanceTimersByTimeAsync(1))
    io.quote = new Map([
      [`NFO:${symbol}`, { data: { ltp: 107, timestamp: now }, updateSource: 'websocket' }],
    ])
    view.rerender(<KotakAssistantChart {...props} title="Tick without calendar" />)
    expect(io.ticks).not.toHaveBeenCalled()
    expect(io.candles.mock.lastCall?.[0]).toHaveLength(1)
    expect(screen.getByText(/Calendar unavailable · historical candles/)).toBeInTheDocument()
  })
  it('uses an explicitly selected broker source without local history or subscriptions', async () => {
    const own = vi.fn(async () => ({ status: 'success', symbol, exchange: 'NFO', interval: '5m', date: null,
      candles: [{ time: 1792116000, open: 100, high: 102, low: 99, close: 101, volume: 10 }] }))
    io.history = [{ time: 1792116000, open: 9990, high: 9999, low: 9980, close: 9998, volume: 10 }]
    renderView(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <KotakAssistantChart symbol={symbol} exchange="NFO" interval="5m" externalSource={{ id: 'flat-account-live', getHistory: own }} />
    </QueryClientProvider>)
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    expect(own).toHaveBeenCalled()
    expect(io.historyRequests).not.toHaveBeenCalled()
    expect(io.subscriptions).toHaveBeenLastCalledWith(expect.objectContaining({ enabled: false }))
    expect(io.candles.mock.calls.flatMap(call => call[0]).some((bar: { close: number }) => bar.close === 101)).toBe(true)
    expect(io.candles.mock.calls.flatMap(call => call[0]).some((bar: { close: number }) => bar.close === 9998)).toBe(false)
  })

})
