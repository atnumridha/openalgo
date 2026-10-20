import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ScalpingCharts } from './ScalpingCharts'
import { candleKey, publishChartCandles } from './chartCandleStore'
import { useThemeStore } from '@/stores/themeStore'
import { useAuthStore } from '@/stores/authStore'
import { scalpingApi } from '@/api/scalping'

vi.mock('@/api/admin', () => ({
  adminApi: {
    checkTimings: async (date: string) => ({
      date,
      timings: [0, 6].includes(new Date(`${date}T00:00Z`).getUTCDay())
        ? []
        : [
            { exchange: 'NFO', start_time: '09:15', end_time: '15:40' },
            { exchange: 'BFO', start_time: '09:15', end_time: '15:40' },
          ],
    }),
  },
}))
vi.mock('@/api/scalping', () => ({ scalpingApi: { getHistory: vi.fn() } }))

vi.mock('./KotakAssistantChart', () => ({
  KotakAssistantChart: ({
    symbol,
    levels,
    interval,
    replay,
    showFvg,
  }: {
    symbol: string
    levels?: Array<{ title: string }>
    interval: string
    replay?: { until: number; bars?: Array<{ time: number; close: number }> }
    showFvg?: boolean
  }) => (
    <div
      data-testid={`chart-${symbol}`}
      data-replay={replay?.until}
      data-replay-prices={replay?.bars?.map((b) => b.close).join(',')}
      data-fvg={String(showFvg)}
    >
      {symbol} {interval} {levels?.map((l) => l.title).join(',')}
    </div>
  ),
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
  mode: 'analyze' as const,
  trades: [],
  indexLevels: [],
  activeLevels: [{ price: 144, title: 'Entry', color: 'blue' }],
  fills: [],
}

describe('Scalping chart terminal', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })
  it('selects the hovered option side without selecting the index', () => {
    const select = vi.fn()
    const view = render(<ScalpingCharts {...props} select={select} />)
    fireEvent.mouseEnter(screen.getByRole('group', { name: 'PE chart panel' }))
    expect(select).toHaveBeenLastCalledWith(pe.symbol)
    view.rerender(<ScalpingCharts {...props} selected={pe.symbol} select={select} />)
    fireEvent.mouseEnter(screen.getByRole('group', { name: 'CE chart panel' }))
    expect(select).toHaveBeenLastCalledWith(ce.symbol)
    fireEvent.mouseEnter(screen.getByRole('group', { name: 'Index chart panel' }))
    expect(select).toHaveBeenCalledTimes(2)
  })
  it('shows CE, index, PE in that order and keeps order levels on their own contract', () => {
    render(<ScalpingCharts {...props} />)
    const panels = screen
      .getAllByRole('group')
      .filter((n) => n.getAttribute('aria-label')?.endsWith('chart panel'))
    expect(panels.map((n) => n.getAttribute('aria-label'))).toEqual([
      'CE chart panel',
      'Index chart panel',
      'PE chart panel',
    ])
    expect(within(panels[0]).getByText(/Entry/)).toBeInTheDocument()
    expect(within(panels[2]).queryByText(/Entry/)).not.toBeInTheDocument()
  })
  it('offers two wider option charts and selecting PE only loads its ticket', () => {
    const select = vi.fn()
    render(<ScalpingCharts {...props} select={select} />)
    fireEvent.click(screen.getByRole('button', { name: 'CE and PE charts' }))
    expect(screen.queryByRole('group', { name: 'Index chart panel' })).not.toBeInTheDocument()
    expect(screen.getByTestId(`chart-${ce.symbol}`)).toBeInTheDocument()
    expect(screen.getByTestId(`chart-${pe.symbol}`)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Select PE for order' }))
    expect(select).toHaveBeenCalledExactlyOnceWith(pe.symbol)
  })
  it('uses one timeframe control for all panes', () => {
    const change = vi.fn()
    render(<ScalpingCharts {...props} onIntervalChange={change} />)
    fireEvent.change(screen.getByLabelText('Chart timeframe'), { target: { value: '5m' } })
    expect(change).toHaveBeenCalledWith('5m')
  })
  it('synchronizes every pane, toggles FVGs and discards replay on layout or timeframe change', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(Date.UTC(2026, 9, 16, 5, 0))
    useAuthStore.setState({ user: null })
    useThemeStore.setState({ appMode: 'live' })
    const current = Math.floor((Date.now() / 1000 + 19800) / 60) * 60
    const bars = Array.from({ length: 10 }, (_, i) => ({
      time: current - (10 - i) * 60,
      open: 100,
      high: 105,
      low: 99,
      close: 102,
      volume: 100,
    }))
    for (const [symbol, exchange] of [
      [ce.symbol, 'NFO'],
      [pe.symbol, 'NFO'],
      ['NIFTY', 'NSE_INDEX'],
    ])
      publishChartCandles(candleKey(undefined, 'live', symbol, exchange, '1m'), bars)
    const view = render(<ScalpingCharts {...props} />)
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
    for (const symbol of [ce.symbol, 'NIFTY', pe.symbol])
      expect(screen.getByTestId(`chart-${symbol}`)).toHaveAttribute(
        'data-replay',
        String(current - 9 * 60)
      )
    fireEvent.click(screen.getByRole('button', { name: 'Next replay candle' }))
    for (const symbol of [ce.symbol, 'NIFTY', pe.symbol])
      expect(screen.getByTestId(`chart-${symbol}`)).toHaveAttribute(
        'data-replay',
        String(current - 8 * 60)
      )
    fireEvent.click(screen.getByRole('checkbox', { name: 'Fair Value Gaps' }))
    expect(screen.getByTestId(`chart-${ce.symbol}`)).toHaveAttribute('data-fvg', 'false')
    fireEvent.click(screen.getByRole('button', { name: 'CE and PE charts' }))
    expect(screen.getByRole('button', { name: 'Replay charts' })).toBeInTheDocument()
    expect(screen.getByTestId(`chart-${ce.symbol}`)).not.toHaveAttribute('data-replay')
    fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
    view.rerender(<ScalpingCharts {...props} interval="5m" />)
    expect(screen.getByRole('button', { name: 'Replay charts' })).toBeInTheDocument()
    expect(screen.getByTestId(`chart-${ce.symbol}`)).not.toHaveAttribute('data-replay')
  })
})

it('defaults Dashboard replay to today IST and starts at todays first shared closed candle', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(Date.UTC(2026, 9, 16, 5, 0))
  useAuthStore.setState({ user: null })
  useThemeStore.setState({ appMode: 'live' })
  const start = Date.UTC(2026, 9, 16, 9, 15) / 1000
  const candles = Array.from({ length: 3 }, (_, i) => ({
    time: start + i * 60,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 10,
  }))
  for (const [symbol, exchange] of [
    [ce.symbol, 'NFO'],
    [pe.symbol, 'NFO'],
    ['NIFTY', 'NSE_INDEX'],
  ])
    publishChartCandles(candleKey(undefined, 'live', symbol, exchange, '1m'), [
      ...candles.map((b) => ({ ...b, time: b.time - 86400 })),
      ...candles,
    ])
  render(<ScalpingCharts {...props} />)
  await act(async () => {})
  expect(screen.getByLabelText('From date IST')).toHaveValue('2026-10-16')
  expect(screen.getByLabelText('To date IST')).toHaveValue('2026-10-16')
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(screen.getByLabelText('Replay time')).toHaveTextContent('16 Oct, 09:16 IST · 1/3')
  expect(screen.getByLabelText('Replay start time IST')).toHaveAttribute('min', '2026-10-16T09:16')
  expect(screen.getByLabelText('Replay start time IST')).toHaveAttribute('max', '2026-10-16T09:18')
  for (const symbol of [ce.symbol, 'NIFTY', pe.symbol])
    expect(screen.getByTestId(`chart-${symbol}`)).toHaveAttribute('data-replay', String(start + 60))
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-15' } })
  fireEvent.input(screen.getByLabelText('To date IST'), { target: { value: '2026-10-15' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(screen.getByLabelText('Replay time')).toHaveTextContent('15 Oct, 09:16 IST · 1/3')
  fireEvent.click(screen.getByRole('button', { name: 'Today' }))
  expect(screen.getByLabelText('From date IST')).toHaveValue('2026-10-16')
  expect(screen.getByLabelText('To date IST')).toHaveValue('2026-10-16')
  expect(screen.getByTestId(`chart-${ce.symbol}`)).not.toHaveAttribute('data-replay')
})

it('defaults to the previous trading day when closed and switches to today at market open', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(Date.UTC(2026, 9, 16, 3, 44, 59))
  useAuthStore.setState({ user: null })
  useThemeStore.setState({ appMode: 'live' })
  const start = Date.UTC(2026, 9, 15, 9, 15) / 1000
  const candles = Array.from({ length: 3 }, (_, i) => ({
    time: start + i * 60,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 10,
  }))
  for (const [symbol, exchange] of [
    [ce.symbol, 'NFO'],
    [pe.symbol, 'NFO'],
    ['NIFTY', 'NSE_INDEX'],
  ])
    publishChartCandles(candleKey(undefined, 'live', symbol, exchange, '1m'), candles)
  const view = render(<ScalpingCharts {...props} />)
  await act(async () => {})
  expect(screen.getByLabelText('From date IST')).toHaveValue('2026-10-15')
  expect(
    screen.getByText('Market closed · replay defaults to the previous trading day')
  ).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(screen.getByLabelText('Replay time')).toHaveTextContent('15 Oct, 09:16 IST · 1/3')
  await act(async () => vi.advanceTimersByTimeAsync(2000))
  expect(screen.getByLabelText('From date IST')).toHaveValue('2026-10-16')
  expect(screen.getByTestId(`chart-${ce.symbol}`)).not.toHaveAttribute('data-replay')
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(screen.getByLabelText('Replay message')).toHaveTextContent(
    'No replay available for 2026-10-16'
  )
  view.unmount()
})

it('loads missing range history in every pane without replacing the live charts', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(Date.UTC(2026, 9, 16, 5))
  vi.mocked(scalpingApi.getHistory).mockImplementation(
    async (symbol, exchange, interval, date) => ({
      status: 'success',
      symbol,
      exchange,
      interval,
      date: date!,
      candles: Array.from({ length: 3 }, (_, i) => ({
        time: Date.parse(`${date}T09:15:00Z`) / 1000 + i * 60,
        open: 100,
        high: 101,
        low: 99,
        close: 100,
        volume: 10,
      })),
    })
  )
  render(<ScalpingCharts {...props} />)
  await act(async () => {})
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-12' } })
  fireEvent.input(screen.getByLabelText('To date IST'), { target: { value: '2026-10-13' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(screen.getByLabelText('Replay time')).toHaveTextContent('12 Oct, 09:16 IST · 1/6')
  expect(screen.getByLabelText('Replay start time IST')).toHaveAttribute('max', '2026-10-13T09:18')
  for (const symbol of [ce.symbol, 'NIFTY', pe.symbol])
    expect(screen.getByTestId(`chart-${symbol}`)).toHaveAttribute(
      'data-replay',
      String(Date.parse('2026-10-12T09:16:00Z') / 1000)
    )
})

it('keeps a manually chosen range across market open and allows restoring the automatic date', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(Date.UTC(2026, 9, 16, 3, 44, 59))
  render(<ScalpingCharts {...props} />)
  await act(async () => {})
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-14' } })
  fireEvent.input(screen.getByLabelText('To date IST'), { target: { value: '2026-10-15' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  await act(async () => vi.advanceTimersByTimeAsync(2000))
  expect(screen.getByLabelText('From date IST')).toHaveValue('2026-10-14')
  expect(screen.getByLabelText('To date IST')).toHaveValue('2026-10-15')
  fireEvent.click(screen.getByRole('button', { name: 'Use market default' }))
  expect(screen.getByLabelText('From date IST')).toHaveValue('2026-10-16')
  expect(screen.getByLabelText('To date IST')).toHaveValue('2026-10-16')
})

it('shows a range failure explicitly and can retry without altering live candles', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(Date.UTC(2026, 9, 16, 5))
  let fail = true
  vi.mocked(scalpingApi.getHistory).mockImplementation(async (symbol, exchange, interval, date) => {
    if (fail) throw Error('Broker history unavailable')
    return {
      status: 'success',
      symbol,
      exchange,
      interval,
      date: date!,
      candles: Array.from({ length: 3 }, (_, i) => ({
        time: Date.parse(`${date}T09:15:00Z`) / 1000 + i * 60,
        open: 100,
        high: 101,
        low: 99,
        close: 100,
        volume: 10,
      })),
    }
  })
  render(<ScalpingCharts {...props} />)
  await act(async () => {})
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-08' } })
  fireEvent.input(screen.getByLabelText('To date IST'), { target: { value: '2026-10-09' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  await act(async () => {})
  expect(screen.getByText(/History unavailable for 2026-10-08/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Replay charts' })).toBeDisabled()
  fail = false
  fireEvent.click(screen.getByRole('button', { name: 'Retry replay history' }))
  await act(async () => {})
  expect(screen.getByRole('button', { name: 'Replay charts' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(screen.getByLabelText('Replay time')).toHaveTextContent('08 Oct, 09:16 IST · 1/6')
})

it('keeps known special weekend-session candles when Today is selected manually', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(Date.UTC(2026, 10, 8, 13))
  useAuthStore.setState({ user: null })
  useThemeStore.setState({ appMode: 'live' })
  const start = Date.UTC(2026, 10, 8, 18) / 1000
  const candles = Array.from({ length: 3 }, (_, i) => ({
    time: start + i * 60,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 10,
  }))
  for (const [symbol, exchange] of [
    [ce.symbol, 'NFO'],
    [pe.symbol, 'NFO'],
    ['NIFTY', 'NSE_INDEX'],
  ])
    publishChartCandles(candleKey(undefined, 'live', symbol, exchange, '1m'), candles)
  render(<ScalpingCharts {...props} />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: 'Today' }))
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(screen.getByLabelText('Replay time')).toHaveTextContent('08 Nov, 18:01 IST · 1/3')
})

it('includes the latest completed candles when a manual Today replay starts later', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(Date.UTC(2026, 9, 16, 4, 30, 30))
  useAuthStore.setState({ user: null })
  useThemeStore.setState({ appMode: 'live' })
  const start = Date.UTC(2026, 9, 16, 9, 58) / 1000
  const candles = Array.from({ length: 3 }, (_, i) => ({
    time: start + i * 60,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 10,
  }))
  const panes = [
    [ce.symbol, 'NFO'],
    [pe.symbol, 'NFO'],
    ['NIFTY', 'NSE_INDEX'],
  ]
  for (const [symbol, exchange] of panes)
    publishChartCandles(candleKey(undefined, 'live', symbol, exchange, '1m'), candles)
  render(<ScalpingCharts {...props} />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: 'Today' }))
  await act(async () => {})
  vi.mocked(Date.now).mockReturnValue(Date.UTC(2026, 9, 16, 4, 35))
  const latest = [
    candles[0],
    candles[1],
    { ...candles[2], high: 104, close: 103 },
    ...Array.from({ length: 2 }, (_, i) => ({ ...candles[0], time: start + (i + 3) * 60 })),
  ]
  act(() => {
    for (const [symbol, exchange] of panes)
      publishChartCandles(candleKey(undefined, 'live', symbol, exchange, '1m'), latest)
  })
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(screen.getByLabelText('Replay start time IST')).toHaveAttribute('max', '2026-10-16T10:03')
  expect(screen.getByTestId(`chart-${ce.symbol}`)).toHaveAttribute(
    'data-replay-prices',
    '100,100,103,100,100'
  )
})

it('automatically loads missing previous-day candles without requiring Apply dates', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(Date.UTC(2026, 9, 15, 18, 40))
  useAuthStore.setState({ user: null })
  useThemeStore.setState({ appMode: 'live' })
  const start = Date.UTC(2026, 9, 14, 9, 15) / 1000
  const candles = Array.from({ length: 3 }, (_, i) => ({
    time: start + i * 60,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 10,
  }))
  for (const [symbol, exchange] of [
    [ce.symbol, 'NFO'],
    [pe.symbol, 'NFO'],
    ['NIFTY', 'NSE_INDEX'],
  ])
    publishChartCandles(candleKey(undefined, 'live', symbol, exchange, '1m'), candles)
  vi.mocked(scalpingApi.getHistory).mockImplementation(
    async (symbol, exchange, interval, date) => ({
      status: 'success',
      symbol,
      exchange,
      interval,
      date: date!,
      candles: candles.map((b) => ({ ...b, time: b.time + 86400 })),
    })
  )
  render(<ScalpingCharts {...props} />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(screen.getByLabelText('Replay time')).toHaveTextContent('15 Oct, 09:16 IST · 1/3')
  expect(scalpingApi.getHistory).toHaveBeenCalledWith(ce.symbol, 'NFO', '1m', '2026-10-15')
})
