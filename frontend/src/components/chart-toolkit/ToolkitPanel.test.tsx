import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { scalpingApi } from '@/api/scalping'
import { ToolkitEngine, type Result } from './model'
import { ToolkitPanel, type DisplaySettings } from './ToolkitPanel'
vi.mock('@/api/scalping', () => ({ scalpingApi: { getHistory: vi.fn() } }))
afterEach(() => vi.restoreAllMocks())
beforeEach(() => vi.clearAllMocks())
const bars = Array.from({ length: 80 }, (_, i) => ({
  time: 1792980000 + i * 60,
  open: 100,
  close: 100 + Math.sin(i) * 2,
  high: 103,
  low: 97,
  volume: 0,
}))
const result = new ToolkitEngine().update(bars, { seconds: 60, asOf: bars.at(-1)!.time + 60 })
function mount(
  replay = false,
  value: Result = result,
  onSettings = vi.fn<(next: DisplaySettings) => void>(),
  feedFresh = true,
  context: { historyReady?: boolean; signalMarket?: 'index' | 'perpetual' | 'option' } = {}
) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ToolkitPanel
        result={value}
        references={[]}
        settings={{ slow: 21, bands: false, markerLimit: 4 }}
        onSettings={onSettings}
        feedFresh={feedFresh}
        {...context}
        replay={replay}
        reference={{
          underlying: 'NIFTY',
          exchange: 'NSE_INDEX',
          optionExchange: 'NFO',
          expiry: '27OCT26',
          ce: { symbol: 'NIFTY27OCT2622500CE', strike: 22500 },
        }}
      />
    </QueryClientProvider>
  )
}
it('shows price status and numeric momentum without claiming unavailable index volume or IV passes', () => {
  mount()
  expect(screen.getByLabelText('Price decision toolkit')).toHaveTextContent('WAIT')
  expect(screen.getByLabelText('Momentum values')).toHaveTextContent('RSI')
  expect(screen.getByLabelText('Momentum values')).not.toHaveTextContent('MFI')
  expect(scalpingApi.getHistory).not.toHaveBeenCalled()
})
it('loads IV only on demand and reports matching model inputs separately from price decisions', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-10-26T10:01:00+05:30'))
  const t = Date.parse('2026-10-26T10:00:00+05:30') / 1000 + 19800
  vi.mocked(scalpingApi.getHistory).mockImplementation(async (symbol, exchange, interval) => ({
    status: 'success',
    symbol,
    exchange,
    interval,
    date: '2026-10-26',
    candles: [
      {
        time: t,
        open: symbol === 'NIFTY' ? 22500 : 120,
        high: symbol === 'NIFTY' ? 22501 : 121,
        low: symbol === 'NIFTY' ? 22499 : 119,
        close: symbol === 'NIFTY' ? 22500 : 120,
        volume: 100,
      },
    ],
  }))
  mount()
  fireEvent.click(screen.getByText('Details'))
  fireEvent.click(screen.getByText('Option IV calculator · separate from price signal'))
  await waitFor(() => expect(screen.getByText(/Calculated IV/)).toBeInTheDocument())
  expect(screen.getByText(/Context only · no IV ceiling set/)).toBeInTheDocument()
  expect(screen.getByText(/Premium 120.00 · Spot 22500.00 · Strike 22500.00/)).toBeInTheDocument()
  expect(screen.getByLabelText('Price decision toolkit')).toHaveTextContent('WAIT')
})
it('does not show current option IV over historical replay candles', () => {
  mount(true)
  fireEvent.click(screen.getByText('Details'))
  fireEvent.click(screen.getByText('Option IV calculator · separate from price signal'))
  expect(
    screen.getByText('IV is hidden during replay / saved-history viewing.')
  ).toBeInTheDocument()
  expect(scalpingApi.getHistory).not.toHaveBeenCalled()
})

it('presents the confirmed candle signal instead of a competing live preview', () => {
  mount(false, {
    ...result,
    confirmed: { status: 'BEAR', reason: 'Price checks pass', rsiAge: 1, crossAge: 1 },
    preview: { status: 'BULL', reason: 'Unconfirmed preview', rsiAge: 0, crossAge: 0 },
  })
  expect(screen.getByLabelText('Confirmed price signal')).toHaveTextContent('BEAR')
  expect(screen.getByLabelText('Confirmed price signal')).not.toHaveTextContent('BULL')
  expect(screen.getByText('Details').closest('details')).not.toHaveAttribute('open')
})
it('keeps extra chart layers optional and independently switchable', () => {
  const onSettings = vi.fn()
  mount(false, result, onSettings)
  fireEvent.click(screen.getByText('Details'))
  const toggle = screen.getByRole('checkbox', { name: 'Liquidity zones' })
  expect(toggle).not.toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Diagonal trendlines' })).not.toBeChecked()
  expect(screen.getByRole('checkbox', { name: '1D / 4H / 1H high & low' })).not.toBeChecked()
  fireEvent.click(toggle)
  expect(onSettings).toHaveBeenCalledWith({
    slow: 21,
    bands: false,
    markerLimit: 4,
    liquidity: true,
  })
})

it('shows WAIT rather than an actionable old signal when live prices are stale', () => {
  mount(
    false,
    {
      ...result,
      confirmed: { status: 'BULL', reason: 'Price checks pass', rsiAge: 1, crossAge: 1 },
    },
    vi.fn(),
    false
  )
  expect(screen.getByLabelText('Confirmed price signal')).toHaveTextContent('WAIT')
  expect(screen.getByLabelText('Confirmed price signal')).toHaveTextContent(
    'Waiting for fresh prices'
  )
})

it.each([
  ['BULL', 'BUY CALL'],
  ['BEAR', 'BUY PUT'],
] as const)('labels a confirmed %s index price signal as the %s side', (status, side) => {
  mount(false, {
    ...result,
    confirmed: { status, reason: 'Price checks pass', rsiAge: 1, crossAge: 1 },
  })
  expect(screen.getByLabelText('Confirmed price signal')).toHaveTextContent(side)
})

it('never presents a cached bullish setup as a CALL before candle history is refreshed', () => {
  mount(
    false,
    {
      ...result,
      confirmed: { status: 'BULL', reason: 'Price checks pass', rsiAge: 1, crossAge: 1 },
    },
    vi.fn(),
    true,
    { historyReady: false }
  )
  expect(screen.getByLabelText('Confirmed price signal')).toHaveTextContent('WAIT')
  expect(screen.getByLabelText('Confirmed price signal')).not.toHaveTextContent('BULL')
})
it.each([
  ['BULL', 'LONG'],
  ['BEAR', 'SHORT'],
] as const)('uses %s/%s price direction for crypto perpetuals instead of options labels', (status, side) => {
  mount(
    false,
    { ...result, confirmed: { status, reason: 'Price checks pass', rsiAge: 1, crossAge: 1 } },
    vi.fn(),
    true,
    { signalMarket: 'perpetual' }
  )
  expect(screen.getByLabelText('Confirmed price signal')).toHaveTextContent(side)
  expect(screen.getByLabelText('Confirmed price signal')).not.toHaveTextContent('CALL')
  expect(screen.getByLabelText('Confirmed price signal')).not.toHaveTextContent('PUT')
})
it('does not convert a signal on a selected option premium into an underlying CALL/PUT direction', () => {
  mount(
    false,
    {
      ...result,
      confirmed: { status: 'BULL', reason: 'Price checks pass', rsiAge: 1, crossAge: 1 },
    },
    vi.fn(),
    true,
    { signalMarket: 'option' }
  )
  expect(screen.getByLabelText('Confirmed price signal')).toHaveTextContent('option premium only')
  expect(screen.getByLabelText('Confirmed price signal')).not.toHaveTextContent('CALL')
})

it('shows the closed-candle RSI and MACD used by the entry, rather than different live values', () => {
  const closed = result.points.at(-1)!
  mount(false, {
    ...result,
    closedTime: closed.time,
    current: { ...closed.metrics, rsi: 12.5, histogram: -9.75 },
    points: [
      ...result.points.slice(0, -1),
      { ...closed, metrics: { ...closed.metrics, rsi: 60.24, histogram: 0.65 } },
      { time: closed.time + 60, metrics: { ...closed.metrics, rsi: 12.5, histogram: -9.75 } },
    ],
  })
  expect(screen.getByLabelText('Momentum values')).toHaveTextContent('60.24')
  expect(screen.getByLabelText('Momentum values')).toHaveTextContent('0.65')
  expect(screen.getByLabelText('Momentum values')).not.toHaveTextContent('12.50')
  expect(screen.getByLabelText('Momentum values')).not.toHaveTextContent('-9.75')
})
