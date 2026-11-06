import * as cryptoOiApi from '../neo-desk/deltaOpenInterest'
import type { PlanBar } from '../neo-desk/chartTradePlan'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { apiClient, webClient } from '@/api/client'
import { scalpingApi } from '@/api/scalping'
import { useAuthStore } from '@/stores/authStore'
import { NineIndicatorPanel } from './NineIndicatorPanel'
import { INDICATORS, type IndicatorKey, type NineResult } from './nineIndicators'
import { optionPrice } from './model'
import type { OptionReference } from './ToolkitPanel'

vi.mock('@/api/client', () => ({ webClient: { get: vi.fn() }, apiClient: { post: vi.fn() } }))
vi.mock('@/api/scalping', () => ({
  scalpingApi: { getExpiry: vi.fn(), futures: vi.fn(), getHistory: vi.fn() },
}))
const now = Date.parse('2026-10-27T12:00:00+05:30') / 1000
const expiry = Date.parse('2026-11-03T15:30:00+05:30') / 1000
const result: NineResult = {
  lastTime: now - 900,
  bias: 'CALL',
  events: [],
  states: INDICATORS.map(({ key }) => ({
    key,
    value: 55,
    side: 'CALL',
    time: now - 900,
    reason: 'Last confirmed event: BUY CALL',
  })),
}
function mount(
  enabled: string[],
  extra: {
    replay?: boolean
    ready?: boolean
    embedded?: boolean
    exchange?: string
    symbol?: string
    source?: 'underlying' | 'premium'
    reference?: OptionReference
    result?: NineResult
    asOf?: number
    seconds?: number
    onMfiProxy?: (r: NineResult | null) => void
    liveValues?: Partial<Record<IndicatorKey, number | null>>
    liveValueTime?: number
    priceBars?: PlanBar[]
  } = {}
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <NineIndicatorPanel
        enabled={enabled}
        result={extra.result ?? result}
        symbol={extra.symbol ?? 'NIFTY'}
        exchange={extra.exchange ?? 'NSE_INDEX'}
        interval="15m"
        seconds={extra.seconds ?? 900}
        asOf={extra.asOf ?? now}
        priceBars={extra.priceBars}
        replay={extra.replay ?? false}
        ready={extra.ready ?? true}
        embedded={extra.embedded}
        reference={extra.reference}
        source={extra.source}
        onMfiProxy={extra.onMfiProxy ?? vi.fn()}
        liveValues={extra.liveValues}
        liveValueTime={extra.liveValueTime}
      />
    </QueryClientProvider>
  )
  return client
}
beforeEach(() => {
  vi.spyOn(Date, 'now').mockReturnValue(now * 1000)
  useAuthStore.setState({ user: { username: 'test' } as never, apiKey: 'test-key' })
  vi.mocked(scalpingApi.getExpiry).mockResolvedValue({ status: 'success', data: ['03NOV26'] })
  vi.mocked(scalpingApi.futures).mockResolvedValue({
    status: 'success',
    data: [{ symbol: 'NIFTY_FUT', expiry: '24-NOV-26', lotsize: 1, tick_size: 0.05 }],
  })
  vi.mocked(webClient.get).mockResolvedValue({
    data: {
      status: 'success',
      atm_strike: 100,
      chain: [
        { strike: 100, ce: { symbol: 'CE', volume: 200 }, pe: { symbol: 'PE', volume: 100 } },
      ],
    },
  })
  vi.mocked(apiClient.post).mockResolvedValue({
    data: { status: 'success', data: { ltp: 101, oi: 1000 } },
  })
  vi.mocked(scalpingApi.getHistory).mockImplementation(async (symbol) => ({
    status: 'success',
    symbol,
    exchange: 'NSE_INDEX',
    interval: '1m',
    date: '2026-10-27',
    candles: [now - 180, now - 120].map((time, i) => {
      const close =
        symbol === 'NIFTY'
          ? 100
          : optionPrice(
              100,
              100,
              (expiry - time - 60) / 31536000,
              0,
              0,
              i && symbol === 'CE' ? 0.18 : 0.2,
              symbol === 'CE'
            )
      return { time: time + 19800, open: close, high: close, low: close, close, volume: 100 }
    }),
  }))
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

it('shows dashboard tick previews without changing confirmed sides, votes or event times', () => {
  mount(['nine-rsi', 'nine-macd', 'nine-ma'], {
    embedded: true,
    liveValues: { rsi: 78.25, ma: null },
    liveValueTime: now,
  })
  const rsi = screen.getByLabelText('Relative Strength Index signal')
  expect(within(rsi).getByText('78.25')).toBeInTheDocument()
  expect(within(rsi).getByText('Live')).toHaveAttribute(
    'title',
    expect.stringContaining('12:00:00')
  )
  expect(within(rsi).getByText('BUY CALL')).toBeInTheDocument()
  expect(within(rsi).getByText('Last confirmed change')).toBeInTheDocument()
  expect(within(rsi).getByTitle('Relative Strength Index signal time')).toHaveAttribute(
    'dateTime',
    '2026-10-27T06:15:00.000Z'
  )
  expect(within(screen.getByLabelText('Moving Averages signal')).getByText('—')).toBeInTheDocument()
  const macd = screen.getByLabelText('MACD signal')
  expect(within(macd).getByText('55.00')).toBeInTheDocument()
  expect(within(macd).getByText('Closed candle')).toBeInTheDocument()
  expect(screen.getByLabelText('Overall indicator signal')).toHaveTextContent('BUY CALL')
  expect(screen.getByText('BUY CALL 3')).toBeInTheDocument()
})

it.each([
  { embedded: false, liveValueTime: now },
  { embedded: true, replay: true, liveValueTime: now },
  { embedded: true, liveValueTime: now - 91 },
  { embedded: true, liveValueTime: now + 1 },
  { embedded: true, liveValueTime: undefined },
])('does not display a live preview outside a current dashboard scope: %j', (scope) => {
  mount(['nine-rsi'], { ...scope, liveValues: { rsi: 78.25 } })
  const row = screen.getByLabelText('Relative Strength Index signal')
  expect(within(row).queryByText('78.25')).not.toBeInTheDocument()
  expect(within(row).getByText('55.00')).toBeInTheDocument()
})

it('refreshes an embedded OI value without letting intermediate polls change its confirmed vote', async () => {
  const client = mount(['nine-oi'], { embedded: true })
  const row = screen.getByLabelText('Open Interest signal')
  await waitFor(() => expect(within(row).getByText('1,000')).toBeInTheDocument())
  const observe = async (elapsed: number, price: number, oi: number) => {
    vi.mocked(Date.now).mockReturnValue((now + elapsed) * 1000)
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { status: 'success', data: { ltp: price, oi } },
    })
    await act(async () => {
      await client.invalidateQueries({ queryKey: ['nine-futures-oi'] })
    })
    await waitFor(() =>
      expect(within(row).getByText(oi.toLocaleString('en-IN'))).toBeInTheDocument()
    )
  }
  await observe(5, 102, 1200)
  expect(within(row).getByText('WAIT')).toBeInTheDocument()
  expect(screen.getByLabelText('Overall indicator signal')).toHaveTextContent('WAIT')
  await observe(31, 103, 1300)
  expect(within(row).getByText('BUY CALL')).toBeInTheDocument()
  const confirmedTime = within(row).getByTitle('Open Interest signal time').getAttribute('dateTime')
  await observe(36, 99, 1500)
  expect(within(row).getByText('BUY CALL')).toBeInTheDocument()
  expect(screen.getByLabelText('Overall indicator signal')).toHaveTextContent('BUY CALL')
  expect(within(row).getByTitle('Open Interest signal time')).toHaveAttribute(
    'dateTime',
    confirmedTime
  )
  expect(within(row).getByText('Observed · 5s')).toBeInTheDocument()
  await observe(62, 98, 1600)
  expect(within(row).getByText('BUY PUT')).toBeInTheDocument()
})

it('refreshes dashboard OI and PCR after five seconds while closed history keeps its cadence', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] })
  mount(['nine-oi', 'nine-pcr', 'nine-iv'], { embedded: true })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(20)
  })
  const oi = screen.getByLabelText('Open Interest signal')
  const pcr = screen.getByLabelText('Put / Call Ratio signal')
  const iv = screen.getByLabelText('Implied Volatility signal')
  expect(within(oi).getByText('1,000')).toBeInTheDocument()
  expect(within(pcr).getByText('0.50')).toBeInTheDocument()
  expect(within(iv).getByText('18.00')).toBeInTheDocument()
  vi.mocked(Date.now).mockReturnValue((now + 5) * 1000)
  vi.mocked(apiClient.post).mockResolvedValue({
    data: { status: 'success', data: { ltp: 102, oi: 1200 } },
  })
  vi.mocked(webClient.get).mockResolvedValue({
    data: {
      status: 'success',
      atm_strike: 100,
      chain: [
        { strike: 100, ce: { symbol: 'CE', volume: 200 }, pe: { symbol: 'PE', volume: 400 } },
      ],
    },
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000)
  })
  expect(within(oi).getByText('1,200')).toBeInTheDocument()
  expect(within(oi).getByText('WAIT')).toBeInTheDocument()
  expect(within(pcr).getByText('2.00')).toBeInTheDocument()
  expect(within(pcr).getByText('BUY PUT')).toBeInTheDocument()
  expect(within(iv).getByText('18.00')).toBeInTheDocument()
  expect(within(iv).getByText('Closed 1m candles')).toBeInTheDocument()
  expect(scalpingApi.getHistory).toHaveBeenCalledTimes(3)
})

it('expires a confirmed OI vote independently of the newer numeric quote', async () => {
  const client = mount(['nine-oi'], { embedded: true })
  const row = screen.getByLabelText('Open Interest signal')
  await waitFor(() => expect(within(row).getByText('1,000')).toBeInTheDocument())
  vi.mocked(Date.now).mockReturnValue((now + 31) * 1000)
  vi.mocked(apiClient.post).mockResolvedValue({
    data: { status: 'success', data: { ltp: 102, oi: 1100 } },
  })
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['nine-futures-oi'] })
  })
  await waitFor(() => expect(within(row).getByText('BUY CALL')).toBeInTheDocument())
  vi.mocked(Date.now).mockReturnValue((now + 36) * 1000)
  vi.mocked(apiClient.post).mockResolvedValue({
    data: { status: 'success', data: { ltp: 103, oi: 1200 } },
  })
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['nine-futures-oi'] })
  })
  await waitFor(() => expect(within(row).getByText('1,200')).toBeInTheDocument())
  vi.mocked(Date.now).mockReturnValue((now + 122) * 1000)
  vi.mocked(apiClient.post).mockRejectedValue(new Error('Quote delayed'))
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['nine-futures-oi'] })
  })
  await waitFor(() => expect(within(row).getByText('WAIT')).toBeInTheDocument())
  expect(within(row).getByText('1,200')).toBeInTheDocument()
  expect(screen.getByLabelText('Overall indicator signal')).toHaveTextContent('WAIT')
})

it('clears the previous account OI preview and confirmation while the new account is loading', async () => {
  mount(['nine-oi'], { embedded: true })
  const row = screen.getByLabelText('Open Interest signal')
  await waitFor(() => expect(within(row).getByText('1,000')).toBeInTheDocument())
  vi.mocked(apiClient.post).mockReturnValue(new Promise(() => {}))
  await act(async () => {
    useAuthStore.setState({ user: { username: 'other' } as never })
  })
  expect(within(row).queryByText('1,000')).not.toBeInTheDocument()
  expect(within(row).getByText('—')).toBeInTheDocument()
  expect(within(row).getByText('WAIT')).toBeInTheDocument()
})

it('keeps a real futures MFI value when a native live preview is unavailable', async () => {
  const lastTime = now - 900
  vi.mocked(scalpingApi.getHistory).mockResolvedValue({
    status: 'success',
    symbol: 'NIFTY_FUT',
    exchange: 'NFO',
    interval: '15m',
    date: '2026-10-27',
    candles: proxyHistory(lastTime).map((bar, i) => ({
      ...bar,
      time: lastTime - (59 - i) * 900 + 19800,
    })),
  })
  mount(['nine-mfi'], {
    embedded: true,
    result: {
      ...result,
      states: result.states.map((state) =>
        state.key === 'mfi' ? { ...state, value: null, side: 'WAIT', time: null } : state
      ),
    },
    liveValues: { mfi: null },
    liveValueTime: now,
  })
  const row = screen.getByLabelText('Money Flow Index signal')
  await waitFor(() => expect(within(row).getByText('Futures candle')).toBeInTheDocument())
  expect(within(row).queryByText('—')).not.toBeInTheDocument()
  expect(within(row).queryByText('Live unavailable')).not.toBeInTheDocument()
})

it('shows independent BUY CALL labels without fetching option data for pure price selections', () => {
  mount(['nine-rsi', 'nine-macd', 'nine-ma'])
  expect(screen.getAllByText('BUY CALL')).toHaveLength(3)
  expect(scalpingApi.getExpiry).not.toHaveBeenCalled()
  expect(webClient.get).not.toHaveBeenCalled()
})
it('retains dated price events during a history delay but counts those old events as WAIT', () => {
  mount(['nine-rsi', 'nine-macd', 'nine-ma'], { ready: false, embedded: true })
  expect(
    within(screen.getByLabelText('Relative Strength Index signal')).getByText('BUY CALL')
  ).toBeInTheDocument()
  expect(screen.getByLabelText('Overall indicator signal')).toHaveTextContent('WAIT')
  expect(screen.getByText('WAIT 3')).toBeInTheDocument()
  expect(screen.getByLabelText('Independent option signals')).not.toHaveClass('absolute')
  expect(webClient.get).not.toHaveBeenCalled()
})
it('renders dashboard values and signals in a table with green, red and yellow states', () => {
  const mixed = {
    ...result,
    states: result.states.map((state) =>
      state.key === 'bb'
        ? { ...state, side: 'PUT' as const }
        : state.key === 'ma'
          ? { ...state, side: 'WAIT' as const, time: null }
          : state
    ),
  }
  mount(['nine-rsi', 'nine-bb', 'nine-ma'], { embedded: true, result: mixed })
  const tables = screen.getAllByRole('table', { name: /Indicator values and CALL \/ PUT signals/ })
  expect(tables).toHaveLength(2)
  expect(tables.flatMap((table) => within(table).getAllByRole('row'))).toHaveLength(5)
  expect(screen.getByLabelText('Overall indicator signal')).toHaveTextContent('WAIT')
  expect(screen.getByText('Tie')).toBeInTheDocument()
  for (const [name, color] of [
    ['Relative Strength Index', 'text-emerald-700'],
    ['Bollinger Bands', 'text-red-700'],
    ['Moving Averages', 'text-yellow-700'],
  ]) {
    const row = screen.getByLabelText(`${name} signal`)
    expect(within(row).getByText('55.00')).toHaveClass(color)
    expect(
      within(row).getByText(
        name === 'Moving Averages' ? 'WAIT' : name === 'Bollinger Bands' ? 'BUY PUT' : 'BUY CALL'
      )
    ).toHaveClass(color)
  }
})
it('shows all nine dashboard indicators in three side-by-side table sections', () => {
  mount(
    INDICATORS.map((item) => item.id),
    { embedded: true, ready: false }
  )
  const tables = screen.getAllByRole('table', { name: /Indicator values and CALL \/ PUT signals/ })
  expect(tables).toHaveLength(3)
  for (const table of tables) expect(within(table).getAllByRole('row')).toHaveLength(4)
  expect(screen.getByLabelText('Dashboard indicator columns')).toHaveClass('xl:grid-cols-3')
})
it('shows an overall CALL when the independent fresh price votes have the largest count', () => {
  mount(['nine-rsi', 'nine-macd', 'nine-ma'], { embedded: true })
  expect(screen.getByLabelText('Overall indicator signal')).toHaveTextContent('BUY CALL')
  expect(screen.getByText('BUY CALL 3')).toBeInTheDocument()
  expect(screen.getByText('BUY PUT 0')).toBeInTheDocument()
  expect(screen.getByText('WAIT 0')).toBeInTheDocument()
})
it('suppresses CALL/PUT and all option-data queries on an option-premium chart', () => {
  mount(
    INDICATORS.map((s) => s.id),
    { exchange: 'NFO' }
  )
  expect(screen.queryByText('BUY CALL')).not.toBeInTheDocument()
  expect(scalpingApi.getExpiry).not.toHaveBeenCalled()
})

it.each([
  ['NIFTY03NOV2623000CE', 'underlying', 'CALL', 'BUY CE'],
  ['NIFTY03NOV2623000PE', 'underlying', 'PUT', 'BUY PE'],
  ['NIFTY03NOV2623000PE', 'premium', 'CALL', 'BUY PE'],
] as const)('enables MA on %s using %s and maps the contract action', (symbol, source, side, label) => {
  const optionResult = { ...result, states: result.states.map((s) => ({ ...s, side })) }
  mount(['nine-ma'], { symbol, exchange: 'NFO', source, result: optionResult })
  expect(within(screen.getByLabelText('Moving Averages signal')).getByText(label)).toBeVisible()
  expect(
    screen.queryByText('Choose the Nifty or Sensex index chart for option direction.')
  ).not.toBeInTheDocument()
})

it('requests PCR for the option underlying and displayed expiry, even in premium mode', async () => {
  mount(['nine-pcr'], { symbol: 'NIFTY10NOV2623000PE', exchange: 'NFO', source: 'premium' })
  await waitFor(() =>
    expect(webClient.get).toHaveBeenCalledWith(
      '/scalping/api/strikes',
      expect.objectContaining({
        params: expect.objectContaining({
          underlying: 'NIFTY',
          exchange: 'NFO',
          expiry: '10NOV26',
        }),
      })
    )
  )
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('Put / Call Ratio signal')).getByText('AVOID PE')
    ).toBeVisible()
  )
  expect(scalpingApi.futures).toHaveBeenCalledWith('NIFTY', 'NFO')
})

it('keeps missing premium volume unavailable instead of substituting futures MFI', () => {
  mount(['nine-mfi'], {
    symbol: 'NIFTY03NOV2623000PE',
    exchange: 'NFO',
    source: 'premium',
    result: {
      ...result,
      states: result.states.map((s) => (s.key === 'mfi' ? { ...s, value: null, side: 'WAIT' } : s)),
    },
  })
  expect(within(screen.getByLabelText('Money Flow Index signal')).getByText('WAIT')).toBeVisible()
  expect(scalpingApi.futures).not.toHaveBeenCalled()
})
it('does not fetch or backfill live IV/PCR/OI during replay', () => {
  mount(['nine-iv', 'nine-pcr', 'nine-oi'], { replay: true })
  expect(screen.getAllByText('WAIT')).toHaveLength(3)
  expect(scalpingApi.getExpiry).not.toHaveBeenCalled()
  expect(apiClient.post).not.toHaveBeenCalled()
})
it('loads matched IV and quoted-volume PCR, then waits for a second futures OI observation', async () => {
  const client = mount(['nine-iv', 'nine-pcr', 'nine-oi'])
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('Put / Call Ratio signal')).getByText('BUY CALL')
    ).toBeInTheDocument()
  )
  expect(
    within(screen.getByLabelText('Implied Volatility signal')).getByText('BUY CALL')
  ).toBeInTheDocument()
  expect(
    within(screen.getByLabelText('Open Interest signal')).getByText('WAIT')
  ).toBeInTheDocument()
  vi.mocked(Date.now).mockReturnValue((now + 31) * 1000)
  vi.mocked(apiClient.post).mockResolvedValue({
    data: { status: 'success', data: { ltp: 102, oi: 1100 } },
  })
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['nine-futures-oi'] })
  })
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('Open Interest signal')).getByText('BUY CALL')
    ).toBeInTheDocument()
  )
  expect(apiClient.post).toHaveBeenCalledWith(
    '/quotes',
    expect.objectContaining({ symbol: 'NIFTY_FUT' }),
    expect.anything()
  )
})
it('loads recent index history and today option history, retaining a recent comparison after a failed refresh', async () => {
  const client = mount(['nine-iv'])
  const row = screen.getByLabelText('Implied Volatility signal')
  await waitFor(() => expect(within(row).getByText('BUY CALL')).toBeInTheDocument())
  expect(scalpingApi.getHistory).toHaveBeenCalledWith(
    'NIFTY',
    'NSE_INDEX',
    '1m',
    undefined,
    expect.objectContaining({ timeoutMs: 30000 })
  )
  for (const contract of ['CE', 'PE'])
    expect(scalpingApi.getHistory).toHaveBeenCalledWith(
      contract,
      'NFO',
      '1m',
      '2026-10-27',
      expect.objectContaining({ timeoutMs: 30000 })
    )
  vi.mocked(Date.now).mockReturnValue((now + 10) * 1000)
  vi.mocked(scalpingApi.getHistory).mockRejectedValue(new Error('Broker history delayed'))
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['nine-option-signals'] })
  })
  expect(within(row).getByText('BUY CALL')).toBeInTheDocument()
  expect(within(row).queryByText('—')).not.toBeInTheDocument()
})
it('computes IV when Kotak returns no index candles for a date-only request', async () => {
  const original = vi.mocked(scalpingApi.getHistory).getMockImplementation()!
  vi.mocked(scalpingApi.getHistory).mockImplementation(async (...args) => {
    const response = await original(...args)
    return args[0] === 'NIFTY' && args[3] ? { ...response, date: null, candles: [] } : response
  })
  mount(['nine-iv'])
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('Implied Volatility signal')).getByText('BUY CALL')
    ).toBeInTheDocument()
  )
})
it('does not promote an option candle fetched before close when another history response arrives later', async () => {
  const response = (symbol: string) => ({
    status: 'success',
    symbol,
    exchange: 'NFO',
    interval: '1m',
    date: '2026-10-27',
    candles: [now - 180, now - 120, now - 60].map((time, i) => {
      const close =
        symbol === 'NIFTY'
          ? 100
          : optionPrice(
              100,
              100,
              (expiry - time - 60) / 31536000,
              0,
              0,
              symbol === 'CE' ? [0.2, 0.18, 0.15][i] : 0.2,
              symbol === 'CE'
            )
      return { time: time + 19800, open: close, high: close, low: close, close, volume: 100 }
    }),
  })
  const finish: Array<() => void> = []
  vi.mocked(Date.now).mockReturnValue((now - 10) * 1000)
  vi.mocked(scalpingApi.getHistory).mockImplementation((symbol) =>
    symbol === 'CE'
      ? Promise.resolve(response(symbol))
      : new Promise((resolve) => finish.push(() => resolve(response(symbol))))
  )
  mount(['nine-iv'])
  await waitFor(() => expect(finish).toHaveLength(2))
  await act(async () => {
    await Promise.resolve()
  })
  vi.mocked(Date.now).mockReturnValue((now + 5) * 1000)
  await act(async () => {
    finish.forEach((resolve) => resolve())
  })
  const row = screen.getByLabelText('Implied Volatility signal')
  await waitFor(() => expect(within(row).getByText('BUY CALL')).toBeInTheDocument())
  expect(within(row).getByText('18.00')).toBeInTheDocument()
})
it('calculates CE and PE IV from their latest common completed minutes when one history lags', async () => {
  vi.mocked(Date.now).mockReturnValue((now + 5) * 1000)
  vi.mocked(scalpingApi.getHistory).mockImplementation(async (symbol) => ({
    status: 'success',
    symbol,
    exchange: 'NFO',
    interval: '1m',
    date: '2026-10-27',
    candles: (symbol === 'PE' ? [now - 180, now - 120] : [now - 180, now - 120, now - 60]).map(
      (time, i) => {
        const close =
          symbol === 'NIFTY'
            ? 100
            : optionPrice(
                100,
                100,
                (expiry - time - 60) / 31536000,
                0,
                0,
                symbol === 'CE' ? [0.2, 0.18, 0.15][i] : 0.2,
                symbol === 'CE'
              )
        return { time: time + 19800, open: close, high: close, low: close, close, volume: 100 }
      }
    ),
  }))
  mount(['nine-iv'])
  const row = screen.getByLabelText('Implied Volatility signal')
  await waitFor(() => expect(within(row).getByText('BUY CALL')).toBeInTheDocument())
  expect(within(row).getByText('18.00')).toBeInTheDocument()
})

it('updates and polls futures OI while the option-chain request remains unresolved', async () => {
  let finishChain!: () => void
  vi.mocked(webClient.get).mockReturnValue(
    new Promise((resolve) => {
      finishChain = () =>
        resolve({
          data: {
            status: 'success',
            atm_strike: 100,
            chain: [
              { strike: 100, ce: { symbol: 'CE', volume: 200 }, pe: { symbol: 'PE', volume: 100 } },
            ],
          },
        })
    })
  )
  const client = mount(['nine-iv', 'nine-pcr', 'nine-oi'], { embedded: true })
  const oi = screen.getByLabelText('Open Interest signal')
  await waitFor(() => expect(within(oi).getByText('1,000')).toBeInTheDocument())
  expect(within(oi).getByText('WAIT')).toBeInTheDocument()
  expect(
    within(screen.getByLabelText('Put / Call Ratio signal')).getByText('WAIT')
  ).toBeInTheDocument()
  vi.mocked(Date.now).mockReturnValue((now + 31) * 1000)
  vi.mocked(apiClient.post).mockResolvedValue({
    data: { status: 'success', data: { ltp: 102, oi: 1100 } },
  })
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['nine-futures-oi'] })
  })
  await waitFor(() => expect(within(oi).getByText('BUY CALL')).toBeInTheDocument())
  expect(apiClient.post).toHaveBeenLastCalledWith(
    '/quotes',
    expect.objectContaining({ symbol: 'NIFTY_FUT' }),
    { timeout: 12000 }
  )
  expect(webClient.get).toHaveBeenCalledTimes(1)
  vi.mocked(Date.now).mockReturnValue((now + 40) * 1000)
  await act(async () => finishChain())
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('Put / Call Ratio signal')).getByText('BUY CALL')
    ).toBeInTheDocument()
  )
  expect(within(oi).getByText('BUY CALL')).toBeInTheDocument()
})

it('allows IV and PCR to use their own conditions even with missing or conflicting MA history', async () => {
  mount(['nine-iv', 'nine-pcr'], {
    ready: false,
    result: { ...result, bias: 'PUT', lastTime: now - 7200 },
  })
  await waitFor(() => expect(webClient.get).toHaveBeenCalled())
  await waitFor(() => expect(screen.getByText(/Option snapshot observed/)).toBeInTheDocument())
  expect(
    within(screen.getByLabelText('Put / Call Ratio signal')).getByText('BUY CALL')
  ).toBeInTheDocument()
  expect(
    within(screen.getByLabelText('Implied Volatility signal')).getByText('BUY CALL')
  ).toBeInTheDocument()
})
it('publishes PCR as soon as chain quotes arrive while IV history is still unresolved', async () => {
  vi.mocked(scalpingApi.getHistory).mockReturnValue(new Promise(() => {}))
  mount(['nine-iv', 'nine-pcr'])
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('Put / Call Ratio signal')).getByText('BUY CALL')
    ).toBeInTheDocument()
  )
  expect(
    within(screen.getByLabelText('Implied Volatility signal')).getByText('WAIT')
  ).toBeInTheDocument()
  expect(scalpingApi.getHistory).toHaveBeenCalled()
})
it('keeps futures OI independent of option expiry and index history availability', async () => {
  vi.mocked(scalpingApi.getExpiry).mockRejectedValue(new Error('Option expiry unavailable'))
  const client = mount(['nine-oi'], { ready: false })
  await waitFor(() => expect(screen.getByText(/Option snapshot observed/)).toBeInTheDocument())
  vi.mocked(Date.now).mockReturnValue((now + 31) * 1000)
  vi.mocked(apiClient.post).mockResolvedValue({
    data: { status: 'success', data: { ltp: 102, oi: 1100 } },
  })
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['nine-futures-oi'] })
  })
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('Open Interest signal')).getByText('BUY CALL')
    ).toBeInTheDocument()
  )
  expect(webClient.get).not.toHaveBeenCalled()
})

function proxyHistory(last: number) {
  return Array.from({ length: 60 }, (_, i) => {
    const close = 100 + Math.sin(i / 3) * 5
    return {
      time: last - (59 - i) * 3600 + 19800,
      open: close - 0.1,
      high: close + 0.2,
      low: close - 0.2,
      close,
      volume: 100,
    }
  })
}

it('publishes futures MFI with its own longer history timeout while option-chain requests are unresolved', async () => {
  const publish = vi.fn(),
    lastTime = now - 900
  vi.mocked(webClient.get).mockReturnValue(new Promise(() => {}))
  vi.mocked(scalpingApi.getHistory).mockResolvedValue({
    status: 'success',
    symbol: 'NIFTY_FUT',
    exchange: 'NFO',
    interval: '15m',
    date: '2026-10-27',
    candles: proxyHistory(lastTime).map((bar, i) => ({
      ...bar,
      time: lastTime - (59 - i) * 900 + 19800,
    })),
  })
  mount(['nine-iv', 'nine-pcr', 'nine-mfi'], {
    ready: false,
    result: {
      ...result,
      states: result.states.map((state) =>
        state.key === 'mfi' ? { ...state, value: null, side: 'WAIT', time: null } : state
      ),
    },
    onMfiProxy: publish,
  })
  await waitFor(() =>
    expect(publish.mock.calls.some((call) => call[0]?.lastTime === lastTime)).toBe(true)
  )
  expect(scalpingApi.getHistory).toHaveBeenCalledWith('NIFTY_FUT', 'NFO', '15m', undefined, {
    timeoutMs: 60000,
  })
  expect(
    publish.mock.lastCall?.[0].states.find((state: { key: string }) => state.key === 'mfi')?.value
  ).not.toBeNull()
})
it('does not promote cached forming futures candles when index history advances', async () => {
  const publish = vi.fn(),
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.mocked(Date.now).mockReturnValue((now - 10) * 1000)
  vi.mocked(scalpingApi.getHistory).mockResolvedValue({
    status: 'success',
    symbol: 'NIFTY_FUT',
    exchange: 'NFO',
    interval: '15m',
    date: '2026-10-27',
    candles: proxyHistory(now - 900).map((bar, i) => ({
      ...bar,
      time: now - 900 - (59 - i) * 900 + 19800,
    })),
  })
  const view = (asOf: number, lastTime: number) => (
    <QueryClientProvider client={client}>
      <NineIndicatorPanel
        enabled={['nine-mfi']}
        result={{
          ...result,
          lastTime,
          states: result.states.map((s) =>
            s.key === 'mfi' ? { ...s, value: null, side: 'WAIT', time: null } : s
          ),
        }}
        symbol="NIFTY"
        exchange="NSE_INDEX"
        interval="15m"
        seconds={900}
        asOf={asOf}
        replay={false}
        ready
        onMfiProxy={publish}
      />
    </QueryClientProvider>
  )
  const rendered = render(view(now - 10, now - 1800))
  await waitFor(() =>
    expect(publish.mock.calls.some((c) => c[0]?.lastTime === now - 1800)).toBe(true)
  )
  vi.mocked(Date.now).mockReturnValue((now + 5) * 1000)
  rendered.rerender(view(now + 5, now - 900))
  expect(publish.mock.calls.some((c) => c[0]?.lastTime === now - 900)).toBe(false)
  expect(publish.mock.lastCall?.[0].lastTime).toBe(now - 1800)
})
it('publishes a completed 1h futures candle at the IST quarter-hour boundary', async () => {
  const asOf = now + 900,
    lastTime = asOf - 3600,
    publish = vi.fn()
  vi.mocked(Date.now).mockReturnValue(asOf * 1000)
  vi.mocked(scalpingApi.getHistory).mockResolvedValue({
    status: 'success',
    symbol: 'NIFTY_FUT',
    exchange: 'NFO',
    interval: '1h',
    date: '2026-10-27',
    candles: proxyHistory(lastTime),
  })
  const emptyMfi = {
    ...result,
    lastTime,
    states: result.states.map((s) =>
      s.key === 'mfi' ? { ...s, value: null, side: 'WAIT' as const, time: null } : s
    ),
  }
  mount(['nine-mfi'], { result: emptyMfi, asOf, seconds: 3600, onMfiProxy: publish })
  await waitFor(() => expect(publish.mock.calls.some((c) => c[0] != null)).toBe(true))
  expect(publish.mock.calls.at(-1)![0].lastTime).toBe(lastTime)
})
it('calculates MFI from fresh futures candles independently of missing index history', async () => {
  const asOf = now + 900,
    lastTime = asOf - 3600,
    publish = vi.fn()
  vi.mocked(Date.now).mockReturnValue(asOf * 1000)
  vi.mocked(scalpingApi.getHistory).mockResolvedValue({
    status: 'success',
    symbol: 'NIFTY_FUT',
    exchange: 'NFO',
    interval: '1h',
    date: '2026-10-27',
    candles: proxyHistory(lastTime),
  })
  const oldIndex = {
    ...result,
    lastTime: now - 86400,
    states: result.states.map((s) =>
      s.key === 'mfi' ? { ...s, value: null, side: 'WAIT' as const, time: null } : s
    ),
  }
  mount(['nine-mfi'], { ready: false, result: oldIndex, asOf, seconds: 3600, onMfiProxy: publish })
  await waitFor(() =>
    expect(publish.mock.calls.some((c) => c[0]?.lastTime === lastTime)).toBe(true)
  )
})
it('clears an MFI proxy whose completed candle does not cover the current index interval', async () => {
  const publish = vi.fn()
  vi.mocked(scalpingApi.getHistory).mockResolvedValue({
    status: 'success',
    symbol: 'NIFTY_FUT',
    exchange: 'NFO',
    interval: '1h',
    date: '2026-10-25',
    candles: proxyHistory(now - 86400),
  })
  const emptyMfi = {
    ...result,
    states: result.states.map((s) =>
      s.key === 'mfi' ? { ...s, value: null, side: 'WAIT' as const, time: null } : s
    ),
  }
  mount(['nine-mfi'], { result: emptyMfi, onMfiProxy: publish })
  await waitFor(() => expect(screen.getByText(/Futures MFI history observed/)).toBeInTheDocument())
  expect(publish.mock.calls.every((c) => c[0] == null)).toBe(true)
})

it.each([
  ['CALL', 'LONG'],
  ['PUT', 'SHORT'],
] as const)('shows %s crypto events as %s at night/weekends and marks IV/PCR inapplicable', (side, label) => {
  const at = Date.parse('2026-11-01T23:00:00Z') / 1000
  vi.spyOn(Date, 'now').mockReturnValue(at * 1000)
  const r = {
    ...result,
    lastTime: at - 300,
    states: result.states.map((s) => ({ ...s, side, time: at - 300 })),
  }
  mount(['nine-rsi', 'nine-ma', 'nine-iv', 'nine-pcr'], {
    symbol: 'BTCUSD',
    exchange: 'DELTA',
    seconds: 300,
    asOf: at,
    result: r,
  })
  expect(
    within(screen.getByLabelText('Relative Strength Index signal')).getByText(label)
  ).toBeVisible()
  expect(within(screen.getByLabelText('Moving Averages signal')).getByText(label)).toBeVisible()
  expect(screen.getByLabelText('Implied Volatility signal')).toHaveTextContent('not applicable')
  expect(screen.getByLabelText('Put / Call Ratio signal')).toHaveTextContent('not applicable')
  expect(scalpingApi.getExpiry).not.toHaveBeenCalled()
})

it('clears crypto OI direction immediately after an explicitly failed background refresh', async () => {
  const prices = [
    { time: now - 1800, open: 100, high: 101, low: 99, close: 100 },
    { time: now - 900, open: 101, high: 103, low: 100, close: 102 },
  ]
  const read = vi
    .spyOn(cryptoOiApi, 'readDeltaOpenInterest')
    .mockResolvedValue({
      symbol: 'BTCUSD',
      interval: '15m',
      observedAt: now,
      bars: prices.map((b, i) => ({
        ...b,
        open: 1000 + i * 100,
        high: 1010 + i * 100,
        low: 990 + i * 100,
        close: 1000 + i * 100,
      })),
    })
  const client = mount(['nine-oi'], { symbol: 'BTCUSD', exchange: 'DELTA', priceBars: prices })
  const row = () => within(screen.getByLabelText('Open Interest signal'))
  await waitFor(() => expect(row().getByText('LONG')).toBeVisible())
  read.mockRejectedValue(Error('Delta unavailable'))
  await act(async () => {
    await client.refetchQueries({ predicate: (q) => q.queryKey[0] === 'delta-indicator-oi' })
  })
  await waitFor(() => expect(row().getByText('WAIT')).toBeVisible())
  expect(row().queryByText('LONG')).not.toBeInTheDocument()
  read.mockRestore()
})
