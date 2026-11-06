import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { KotakAssistant } from './KotakAssistant'
import { kotakAssistantApi } from '@/api/kotakAssistant'
import { scalpingApi } from '@/api/scalping'
import type { SymbolData } from '@/hooks/useMarketData'

const indexFeed = vi.hoisted(() => new Map<string, SymbolData>())
const optionFeed = vi.hoisted(() => new Map<string, SymbolData>())
vi.mock('./trackingStore', () => ({ loadTracking: vi.fn(async () => []), saveTracking: vi.fn() }))
vi.mock('@/hooks/useMarketData', () => ({
  useMarketData: ({ mode }: { mode: string }) => ({
    data: mode === 'Quote' ? indexFeed : optionFeed,
    isConnected: false,
  }),
}))
vi.mock('./KotakAssistantChart', () => ({ KotakAssistantChart: () => <div>Chart</div> }))
vi.mock('@/api/kotakAssistant', () => ({
  kotakAssistantApi: {
    snapshot: vi.fn(() => new Promise(() => {})),
    brokerMonitor: vi.fn(() => new Promise(() => {})),
  },
}))
vi.mock('@/api/scalping', () => ({
  scalpingApi: { getExpiry: vi.fn(() => Promise.resolve({ status: 'success', data: [] })) },
}))
function mount() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <KotakAssistant />
    </QueryClientProvider>
  )
}
describe('Kotak home desk', () => {
  afterEach(() => vi.useRealTimers())
  beforeEach(() => {
    // Contract fixtures describe the 15 October session; query timers stay real.
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-15T04:30:00Z'))
    indexFeed.clear()
    optionFeed.clear()
    vi.mocked(scalpingApi.getExpiry).mockResolvedValue({
      status: 'success',
      data: ['19OCT26'],
    } as never)
    vi.mocked(kotakAssistantApi.snapshot).mockImplementation(() => new Promise(() => {}))
    vi.mocked(kotakAssistantApi.brokerMonitor).mockImplementation(() => new Promise(() => {}))
    useThemeStore.setState({ appMode: 'live' })
    useAuthStore.setState({
      user: { username: 'u', broker: 'kotak', isLoggedIn: true, loginTime: null },
    })
  })
  it('shows live desk without an arming switch', () => {
    mount()
    expect(screen.getByText('Kotak Trading Assistant')).toBeInTheDocument()
    expect(screen.getByText('LIVE')).toBeInTheDocument()
    expect(screen.queryByRole('switch', { name: /arm/i })).not.toBeInTheDocument()
  })
  it('defaults to Confirmed trend and sends the chosen opening strategy to the snapshot', async () => {
    mount()
    expect(screen.getByLabelText('Strategy')).toHaveValue('trend')
    expect(screen.getByLabelText('Signal mode')).toHaveValue('confirmed')
    fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: 'opening_reversal' } })
    await waitFor(() =>
      expect(kotakAssistantApi.snapshot).toHaveBeenCalledWith(
        expect.objectContaining({ strategy: 'opening_reversal', signal_mode: 'confirmed' })
      )
    )
  })
  it('automatically shows actual Neo positions while the order ticket stays in Paper mode', async () => {
    useThemeStore.setState({ appMode: 'analyze' })
    vi.mocked(kotakAssistantApi.brokerMonitor).mockResolvedValue({
      scope: 'u:account:live:observer',
      mode: 'live',
      book_time: Date.now() / 1000,
      error: null,
      orders: [],
      fills: [],
      days: {},
      positions: [
        {
          symbol: 'RELIANCE',
          exchange: 'NSE',
          product: 'CNC',
          quantity: 5,
          average_entry: 1400,
          average_entry_verified: true,
          entry_basis: 'Today’s broker fills',
          ltp: 1410,
        },
      ],
    })
    mount()
    const card = await screen.findByRole('region', { name: 'Broker position RELIANCE CNC' })
    expect(within(card).getByLabelText('Broker current price')).toHaveTextContent('₹1,410.00')
    expect(screen.getByText('PAPER', { exact: true })).toBeInTheDocument()
    expect(screen.getByText('LIVE · From Kotak Neo')).toBeInTheDocument()
  })
  it('starts with the recommended five-minute charts and keeps a manual timeframe during updates', async () => {
    mount()
    expect(screen.getByLabelText('Chart timeframe')).toHaveValue('5m')
    expect(screen.getByRole('option', { name: '5m · Recommended' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Chart timeframe'), { target: { value: '15m' } })
    await screen.findByRole('option', { name: '19OCT26' })
    expect(screen.getByLabelText('Chart timeframe')).toHaveValue('15m')
  })
  it('does not show account desk for another broker', () => {
    useAuthStore.setState({
      user: { username: 'u', broker: 'fyers', isLoggedIn: true, loginTime: null },
    })
    mount()
    expect(screen.queryByText('Kotak Trading Assistant')).not.toBeInTheDocument()
  })
  it.each([
    { ltp: 23000, direction: 'NIFTY UP', points: '+200.00 pts', percent: '(+0.88%)' },
    { ltp: 22600, direction: 'NIFTY DOWN', points: '-200.00 pts', percent: '(-0.88%)' },
    { ltp: 22800, direction: 'NIFTY FLAT', points: '0.00 pts', percent: '(0.00%)' },
  ])('shows $direction with live points and percentage from the previous close', ({
    ltp,
    direction,
    points,
    percent,
  }) => {
    indexFeed.set('NSE_INDEX:NIFTY', {
      symbol: 'NIFTY',
      exchange: 'NSE_INDEX',
      lastUpdate: Date.now(),
      updateSource: 'websocket',
      data: { ltp, close: 22800 },
    })
    mount()
    const movement = screen.getByLabelText('NIFTY day movement')
    expect(movement).toHaveTextContent(direction)
    expect(movement).toHaveTextContent(points)
    expect(movement).toHaveTextContent(percent)
    expect(movement).toHaveTextContent('vs previous close')
  })
  it('does not manufacture a flat signal when the previous close is missing', () => {
    indexFeed.set('NSE_INDEX:NIFTY', {
      symbol: 'NIFTY',
      exchange: 'NSE_INDEX',
      lastUpdate: Date.now(),
      updateSource: 'websocket',
      data: { ltp: 23000, close: 0 },
    })
    mount()
    expect(screen.getByLabelText('NIFTY day movement')).toHaveTextContent('Change unavailable')
    expect(screen.queryByText('NIFTY FLAT')).not.toBeInTheDocument()
  })
  it('keeps a stale REST movement clearly labelled as the last quote', async () => {
    vi.mocked(kotakAssistantApi.snapshot).mockResolvedValue({
      scope: 'u:live',
      mode: 'live',
      settings: { cutoff: '15:15' },
      trades: [],
      underlying: 'NIFTY',
      exchange: 'NFO',
      analysis: { action: 'WAIT', reason: 'Market closed', zones: [] },
      index_quote: { ltp: 22600, prev_close: 22800, time: Date.now() / 1000 - 10 },
    } as never)
    mount()
    await waitFor(() => {
      const movement = screen.getByLabelText('NIFTY day movement')
      expect(movement).toHaveTextContent('-200.00 pts')
      expect(movement).toHaveTextContent('Last DOWN')
      expect(movement).toHaveTextContent('Last quote · stale')
    })
  })
  it('updates the open trade price from its own symbol feed and falls back to its broker quote', async () => {
    const symbol = 'NIFTY19OCT2623100CE'
    const now = Date.now()
    vi.mocked(kotakAssistantApi.snapshot).mockResolvedValue({
      scope: 'u:live',
      mode: 'live',
      settings: { cutoff: '15:15' },
      underlying: 'NIFTY',
      exchange: 'NFO',
      analysis: { action: 'WAIT', zones: [] },
      trades: [
        {
          id: 'open-monitor',
          mode: 'live',
          symbol,
          exchange: 'NFO',
          product: 'MIS',
          remaining: 65,
          entry_quantity: 65,
          lot: 65,
          tick: 0.05,
          average_entry: 70,
          sl: 64,
          current_sl: 64,
          target: 82,
          status: 'protected',
          ops: [],
          quote: { ltp: 71, bid: 70.9, ask: 71.1, time: now / 1000, source: 'Broker snapshot' },
        },
      ],
    } as never)
    optionFeed.set(`NFO:${symbol}`, {
      symbol,
      exchange: 'NFO',
      lastUpdate: now,
      updateSource: 'websocket',
      data: { ltp: 72.25, bid_price: 72.1, ask_price: 72.3 },
    })
    optionFeed.set('NFO:NIFTY19OCT2623100PE', {
      symbol: 'NIFTY19OCT2623100PE',
      exchange: 'NFO',
      lastUpdate: now,
      data: { ltp: 199, bid_price: 198.9, ask_price: 199.1 },
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const content = () => (
      <QueryClientProvider client={client}>
        <KotakAssistant />
      </QueryClientProvider>
    )
    const view = render(content())
    const trade = within(await screen.findByRole('region', { name: `Open trade ${symbol}` }))
    expect(trade.getByLabelText('Current market price')).toHaveTextContent('₹72.25')
    optionFeed.set(`NFO:${symbol}`, {
      symbol,
      exchange: 'NFO',
      lastUpdate: now,
      updateSource: 'websocket',
      data: { ltp: 73.5, bid_price: 73.4, ask_price: 73.6 },
    })
    view.rerender(content())
    await waitFor(() =>
      expect(screen.getByLabelText('Current market price')).toHaveTextContent('₹73.50')
    )
    optionFeed.set(`NFO:${symbol}`, {
      symbol,
      exchange: 'NFO',
      lastUpdate: now - 10000,
      updateSource: 'websocket',
      data: { ltp: 73.5, bid_price: 73.4, ask_price: 73.6 },
    })
    view.rerender(content())
    await waitFor(() =>
      expect(screen.getByLabelText('Current market price')).toHaveTextContent('₹71.00')
    )
    expect(screen.getByText(/Updated .* IST|Waiting for a fresh market price/)).toHaveTextContent(
      'Broker snapshot'
    )
  })
  it('updates live direction and uses the selected index reference after switching to SENSEX', () => {
    const tick = (symbol: string, exchange: string, ltp: number, close: number) => ({
      symbol,
      exchange,
      lastUpdate: Date.now(),
      updateSource: 'websocket' as const,
      data: { ltp, close },
    })
    indexFeed.set('NSE_INDEX:NIFTY', tick('NIFTY', 'NSE_INDEX', 22600, 22800))
    const view = mount()
    expect(screen.getByLabelText('NIFTY day movement')).toHaveTextContent('NIFTY DOWN')
    indexFeed.set('NSE_INDEX:NIFTY', tick('NIFTY', 'NSE_INDEX', 22900, 22800))
    view.rerender(
      <QueryClientProvider client={new QueryClient()}>
        <KotakAssistant />
      </QueryClientProvider>
    )
    expect(screen.getByLabelText('NIFTY day movement')).toHaveTextContent('NIFTY UP')
    expect(screen.getByLabelText('NIFTY day movement')).toHaveTextContent('+100.00 pts')
    indexFeed.set('BSE_INDEX:SENSEX', tick('SENSEX', 'BSE_INDEX', 72720, 72000))
    fireEvent.change(screen.getByLabelText('Index'), { target: { value: 'SENSEX' } })
    const movement = screen.getByLabelText('SENSEX day movement')
    expect(movement).toHaveTextContent('SENSEX UP')
    expect(movement).toHaveTextContent('+720.00 pts (+1.00%)')
    expect(screen.queryByLabelText('NIFTY day movement')).not.toBeInTheDocument()
  })
  it('places the recommended strike before the chart and order ticket without buying', async () => {
    vi.mocked(kotakAssistantApi.snapshot).mockResolvedValue({
      scope: 'u:live',
      mode: 'live',
      settings: { cutoff: '15:15' },
      trades: [],
      underlying: 'NIFTY',
      exchange: 'NFO',
      analysis: { action: 'WAIT', reason: 'Market closed', zones: [] },
      recommendation: {
        symbol: 'NIFTY19OCT2622600CE',
        strike: 22600,
        side: 'CE',
        reason: 'Candidate liquidity',
        plan: {},
      },
    } as never)
    mount()
    const candidate = await screen.findByText(/NIFTY 22600 CE/)
    expect(
      candidate.compareDocumentPosition(screen.getByRole('heading', { name: 'Order ticket' })) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy()
    expect(await screen.findByText(/Watchlist only · WAIT/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Inspect recommended strike' })).toBeInTheDocument()
  })
  it('shows actual strikes and CE/PE selection above the chart', async () => {
    vi.mocked(kotakAssistantApi.snapshot).mockResolvedValue({
      scope: 'u:live',
      mode: 'live',
      settings: { cutoff: '15:15' },
      trades: [],
      underlying: 'NIFTY',
      exchange: 'NFO',
      analysis: { action: 'WAIT', reason: 'Closed', zones: [] },
      chain: {
        atm_strike: 22600,
        chain: [
          {
            strike: 22600,
            ce: { symbol: 'NIFTY19OCT2622600CE', lotsize: 65, tick_size: 0.05, ltp: 100, ask: 100 },
            pe: { symbol: 'NIFTY19OCT2622600PE', lotsize: 65, tick_size: 0.05, ltp: 90, ask: 90 },
          },
        ],
      },
    } as never)
    mount()
    await screen.findByRole('option', { name: '19OCT26' })
    fireEvent.change(screen.getByLabelText('Expiry'), { target: { value: '19OCT26' } })
    const ce = await screen.findByRole('button', { name: 'Select 22600 CE' })
    expect(screen.getByRole('combobox', { name: 'Strike' })).toHaveValue('22600')
    expect(screen.getByRole('button', { name: 'Select 22600 PE' })).toBeInTheDocument()
    expect(
      ce.compareDocumentPosition(screen.getByRole('group', { name: 'Chart instrument' })) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy()
  })
  it('automatically fills the ticket on strike selection and preserves the chosen PE side', async () => {
    const leg = (strike: number, side: string, price: number) => ({
      symbol: `NIFTY19OCT26${strike}${side}`,
      lotsize: 65,
      tick_size: 0.05,
      ltp: price,
      ask: 0,
    })
    vi.mocked(kotakAssistantApi.snapshot).mockResolvedValue({
      scope: 'u:live',
      mode: 'live',
      settings: { cutoff: '15:15' },
      trades: [],
      underlying: 'NIFTY',
      exchange: 'NFO',
      analysis: { action: 'WAIT', reason: 'Closed', zones: [] },
      chain: {
        atm_strike: 22600,
        chain: [
          { strike: 22600, ce: leg(22600, 'CE', 100), pe: leg(22600, 'PE', 90) },
          { strike: 22650, ce: leg(22650, 'CE', 80), pe: leg(22650, 'PE', 120) },
        ],
      },
    } as never)
    mount()
    await screen.findByRole('option', { name: '19OCT26' })
    fireEvent.change(screen.getByLabelText('Expiry'), { target: { value: '19OCT26' } })
    await screen.findByRole('button', { name: 'Select 22600 CE' })
    await waitFor(() => expect(screen.getByLabelText('Entry limit ₹')).toHaveValue(100))
    expect(screen.getByLabelText('Lots')).toHaveValue(1)
    expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(90)
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(120)
    fireEvent.click(screen.getByRole('button', { name: 'Risk reward 1:5' }))
    fireEvent.click(screen.getByRole('button', { name: 'Select 22600 PE' }))
    fireEvent.change(screen.getByLabelText('Strike'), { target: { value: '22650' } })
    await waitFor(() => expect(screen.getByLabelText('Entry limit ₹')).toHaveValue(120))
    expect(screen.getByLabelText('Entry limit ₹')).toHaveValue(120)
    expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(108)
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(180)
    expect(screen.getByText(/NIFTY19OCT2622650PE ·/)).toBeInTheDocument()
  })
  it('automatically selects the nearest valid expiry from an unsorted response', async () => {
    vi.mocked(scalpingApi.getExpiry).mockResolvedValue({
      status: 'success',
      data: ['27OCT99', 'bad', '01JAN20', '19OCT99', '19OCT99'],
    } as never)
    mount()
    await waitFor(() => expect(screen.getByLabelText('Expiry')).toHaveValue('19OCT99'))
    expect(screen.queryByRole('option', { name: '01JAN20' })).not.toBeInTheDocument()
    await waitFor(() =>
      expect(kotakAssistantApi.snapshot).toHaveBeenCalledWith(
        expect.objectContaining({ expiry: '19OCT99' })
      )
    )
  })
  it('keeps a selected CE when the index setup favours PE', async () => {
    const now = Date.now() / 1000
    const leg = (side: string, ask: number) => ({
      symbol: `NIFTY19OCT2622600${side}`,
      lotsize: 65,
      tick_size: 0.05,
      ltp: ask,
      bid: ask - 0.1,
      ask,
    })
    vi.mocked(kotakAssistantApi.snapshot).mockImplementation(
      async (params) =>
        ({
          scope: 'u:live',
          mode: 'live',
          settings: { cutoff: '15:15' },
          trades: [],
          underlying: 'NIFTY',
          exchange: 'NFO',
          chain_time: now,
          analysis: { action: 'PUT', reason: 'ready', zones: [] },
          setup: {
            strategy: 'trend',
            version: '1.0',
            mode: 'confirmed',
            stage: 'ready',
            direction: 'PE',
            reason: 'ready',
            evidence: [],
            eligible: true,
            expires: now + 120,
          },
          chain: {
            atm_strike: 22600,
            chain: [{ strike: 22600, ce: leg('CE', 100), pe: leg('PE', 90) }],
          },
          selected_plan: String(params.symbol).endsWith('CE')
            ? { entry: 100, sl: 80, target: 140, fits: true }
            : undefined,
        }) as never
    )
    mount()
    await waitFor(() => expect(screen.getByLabelText('Entry limit ₹')).toHaveValue(100))
    expect(screen.getByRole('button', { name: 'Use setup' })).toBeDisabled()
    expect(
      within(screen.getByLabelText('Chart setup assistant')).getByText(
        /Selected CE.*index setup favours PE/i
      )
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Entry limit ₹')).toHaveValue(100)
  })
  it('uses the exact selected strike even when the recommendation is a different strike', async () => {
    const now = Date.now() / 1000
    const ce = (strike: number, ask: number) => ({
      symbol: `NIFTY19OCT262${strike}CE`,
      lotsize: 65,
      tick_size: 0.05,
      ltp: ask,
      bid: ask - 0.1,
      ask,
    })
    const plan = (entry: number) => ({ entry, sl: entry - 10, target: entry + 20, fits: true })
    const first = ce(2600, 100),
      chosen = ce(2650, 80)
    vi.mocked(kotakAssistantApi.snapshot).mockImplementation(
      async (params) =>
        ({
          scope: 'u:live',
          mode: 'live',
          settings: { cutoff: '15:15' },
          trades: [],
          underlying: 'NIFTY',
          exchange: 'NFO',
          chain_time: now,
          analysis: { action: 'CALL', reason: 'ready', zones: [] },
          setup: {
            strategy: 'trend',
            version: '1.0',
            mode: 'confirmed',
            stage: 'ready',
            direction: 'CE',
            reason: 'ready',
            evidence: [],
            eligible: true,
            expires: now + 120,
          },
          chain: {
            atm_strike: 22600,
            chain: [
              { strike: 22600, ce: first },
              { strike: 22650, ce: chosen },
            ],
          },
          recommendation: { symbol: first.symbol, strike: 22600, side: 'CALL', plan: plan(100) },
          selected_plan: plan(params.symbol === chosen.symbol ? 80 : 100),
        }) as never
    )
    mount()
    await screen.findByRole('option', { name: '22650' })
    fireEvent.change(screen.getByLabelText('Strike'), { target: { value: '22650' } })
    await waitFor(() => expect(screen.getByLabelText('Entry limit ₹')).toHaveValue(80))
    fireEvent.click(screen.getByRole('button', { name: 'Use setup' }))
    await screen.findByText(/Setup adopted ·/)
    expect(screen.getByLabelText('Strike')).toHaveValue('22650')
    expect(screen.getByLabelText('Entry limit ₹')).toHaveValue(80)
    expect(
      within(screen.getByLabelText('Chart setup assistant')).getByText(chosen.symbol)
    ).toBeInTheDocument()
  })
  it('preserves a later expiry selected manually', async () => {
    vi.mocked(scalpingApi.getExpiry).mockResolvedValue({
      status: 'success',
      data: ['27OCT99', '19OCT99'],
    } as never)
    mount()
    await waitFor(() => expect(screen.getByLabelText('Expiry')).toHaveValue('19OCT99'))
    fireEvent.change(screen.getByLabelText('Expiry'), { target: { value: '27OCT99' } })
    await waitFor(() =>
      expect(kotakAssistantApi.snapshot).toHaveBeenCalledWith(
        expect.objectContaining({ expiry: '27OCT99' })
      )
    )
    expect(screen.getByLabelText('Expiry')).toHaveValue('27OCT99')
  })
  it('selects the first expiry for the new index when switching to SENSEX', async () => {
    vi.mocked(scalpingApi.getExpiry).mockImplementation(
      (symbol) =>
        Promise.resolve({
          status: 'success',
          data: symbol === 'SENSEX' ? ['23OCT99', '16OCT99'] : ['19OCT99'],
        }) as never
    )
    mount()
    await waitFor(() => expect(screen.getByLabelText('Expiry')).toHaveValue('19OCT99'))
    fireEvent.change(screen.getByLabelText('Index'), { target: { value: 'SENSEX' } })
    await waitFor(() => expect(screen.getByLabelText('Expiry')).toHaveValue('16OCT99'))
  })

  it('shows loading while the new index expiry lookup is pending', async () => {
    let completeSensex!: (value: { status: string; data: string[] }) => void
    vi.mocked(scalpingApi.getExpiry).mockImplementation((symbol) =>
      symbol === 'SENSEX'
        ? new Promise((resolve) => {
            completeSensex = resolve
          })
        : Promise.resolve({ status: 'success', data: ['19OCT99'] })
    )
    mount()
    await waitFor(() => expect(screen.getByLabelText('Expiry')).toHaveValue('19OCT99'))
    fireEvent.change(screen.getByLabelText('Index'), { target: { value: 'SENSEX' } })
    expect(screen.getByLabelText('Expiry')).toBeDisabled()
    expect(screen.getByRole('option', { name: 'Loading expiries…' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: '19OCT99' })).not.toBeInTheDocument()
    await act(async () => completeSensex({ status: 'success', data: ['22OCT99'] }))
    await waitFor(() => expect(screen.getByLabelText('Expiry')).toHaveValue('22OCT99'))
    expect(screen.getByLabelText('Expiry')).toBeEnabled()
  })

  it('loads BANKNIFTY expiries, strikes and ticket using NSE rather than BSE', async () => {
    vi.mocked(scalpingApi.getExpiry).mockImplementation(async (symbol) => ({
      status: 'success',
      data: symbol === 'BANKNIFTY' ? ['27NOV99', '27OCT99'] : ['19OCT99'],
    }))
    vi.mocked(kotakAssistantApi.snapshot).mockImplementation(
      async ({ underlying }) =>
        ({
          scope: 'u:live',
          mode: 'live',
          settings: { cutoff: '15:15' },
          trades: [],
          underlying,
          exchange: 'NFO',
          analysis: { action: 'WAIT', zones: [] },
          chain:
            underlying === 'BANKNIFTY'
              ? {
                  atm_strike: 50000,
                  chain: [
                    {
                      strike: 50000,
                      ce: {
                        symbol: 'BANKNIFTY27OCT9950000CE',
                        lotsize: 35,
                        tick_size: 0.05,
                        ltp: 150,
                      },
                      pe: {
                        symbol: 'BANKNIFTY27OCT9950000PE',
                        lotsize: 35,
                        tick_size: 0.05,
                        ltp: 170,
                      },
                    },
                  ],
                }
              : undefined,
        }) as never
    )
    indexFeed.set('NSE_INDEX:BANKNIFTY', {
      symbol: 'BANKNIFTY',
      exchange: 'NSE_INDEX',
      lastUpdate: Date.now(),
      updateSource: 'websocket',
      data: { ltp: 50010, close: 50000 },
    })
    mount()
    await waitFor(() => expect(screen.getByLabelText('Expiry')).toHaveValue('19OCT99'))
    fireEvent.change(screen.getByLabelText('Index'), { target: { value: 'BANKNIFTY' } })
    await waitFor(() => expect(screen.getByLabelText('Expiry')).toHaveValue('27OCT99'))
    expect(scalpingApi.getExpiry).toHaveBeenCalledWith('BANKNIFTY', 'NFO')
    expect(screen.getByLabelText('BANKNIFTY day movement')).toHaveTextContent('+10.00 pts')
    await waitFor(() => expect(screen.getByLabelText('Strike')).toHaveValue('50000'))
    await waitFor(() => expect(screen.getByLabelText('Entry limit ₹')).toHaveValue(150))
    expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(135)
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(180)
    expect(screen.getByRole('button', { name: 'Buy 1 lot · 35 units LIVE' })).toBeInTheDocument()
  })

  it('refresh reloads an empty expiry list and selects its nearest contract', async () => {
    vi.mocked(scalpingApi.getExpiry).mockResolvedValue({ status: 'success', data: [] })
    mount()
    await screen.findByRole('option', { name: 'No active expiries' })
    vi.mocked(scalpingApi.getExpiry).mockResolvedValue({
      status: 'success',
      data: ['29OCT99', '22OCT99'],
    })
    fireEvent.click(screen.getByRole('button', { name: 'Refresh', exact: true }))
    await waitFor(() => expect(screen.getByLabelText('Expiry')).toHaveValue('22OCT99'))
  })

  it.each([
    'network',
    'response',
  ])('explains a failed %s expiry lookup and lets the user retry without changing index', async (failure) => {
    if (failure === 'network')
      vi.mocked(scalpingApi.getExpiry).mockRejectedValue(new Error('Temporary lookup failure'))
    else
      vi.mocked(scalpingApi.getExpiry).mockResolvedValue({
        status: 'error',
        data: [],
        message: 'Temporary lookup failure',
      })
    mount()
    await screen.findByRole('option', { name: 'Expiry unavailable' })
    expect(screen.getByLabelText('Expiry')).toBeDisabled()
    expect(screen.getByText(/NIFTY expiries unavailable/)).toBeInTheDocument()
    vi.mocked(scalpingApi.getExpiry).mockResolvedValue({ status: 'success', data: ['19OCT99'] })
    fireEvent.click(screen.getByRole('button', { name: 'Retry expiries' }))
    await waitFor(() => expect(screen.getByLabelText('Expiry')).toHaveValue('19OCT99'))
    expect(screen.queryByRole('button', { name: 'Retry expiries' })).not.toBeInTheDocument()
  })

  it('automatically recovers when contracts arrive after an empty expiry response', async () => {
    vi.useFakeTimers()
    vi.mocked(scalpingApi.getExpiry).mockResolvedValue({ status: 'success', data: [] })
    const view = mount()
    try {
      await act(async () => vi.advanceTimersByTimeAsync(100))
      expect(screen.getByLabelText('Expiry')).toBeDisabled()
      expect(screen.getByText(/No active NIFTY expiries found/)).toBeInTheDocument()
      vi.mocked(scalpingApi.getExpiry).mockResolvedValue({ status: 'success', data: ['19OCT99'] })
      await act(async () => vi.advanceTimersByTimeAsync(5000))
      expect(screen.getByLabelText('Expiry')).toHaveValue('19OCT99')
      expect(screen.getByLabelText('Expiry')).toBeEnabled()
    } finally {
      view.unmount()
      vi.useRealTimers()
    }
  })

  it('refreshes account and quote values each second while preserving ticket edits and focus', async () => {
    vi.useFakeTimers()
    vi.mocked(scalpingApi.getExpiry).mockResolvedValue({
      status: 'success',
      data: ['19OCT99', '27OCT99'],
    } as never)
    let net = 10
    let premium = 100
    vi.mocked(kotakAssistantApi.snapshot).mockImplementation(
      async () =>
        ({
          scope: 'u:live',
          mode: 'live',
          settings: { cutoff: '15:15' },
          trades: [],
          underlying: 'NIFTY',
          exchange: 'NFO',
          book_time: Date.now() / 1000,
          day: { net },
          analysis: { action: 'WAIT', reason: 'Market closed', zones: [] },
          chain: {
            atm_strike: 22600,
            chain: [
              {
                strike: 22600,
                ce: { symbol: 'NIFTY19OCT9922600CE', lotsize: 65, tick_size: 0.05, ltp: premium },
                pe: { symbol: 'NIFTY19OCT9922600PE', lotsize: 65, tick_size: 0.05, ltp: 90 },
              },
            ],
          },
        }) as never
    )
    const view = mount()
    try {
      await act(async () => vi.advanceTimersByTimeAsync(50))
      await act(async () => vi.advanceTimersByTimeAsync(50))
      await act(async () => vi.advanceTimersByTimeAsync(50))
      expect(screen.getByLabelText('Expiry')).toHaveValue('19OCT99')
      expect(screen.getByText('₹10.00')).toBeInTheDocument()
      fireEvent.change(screen.getByLabelText('Chart timeframe'), { target: { value: '15m' } })
      fireEvent.change(screen.getByLabelText('Lots'), { target: { value: '3' } })
      const entry = screen.getByLabelText('Entry limit ₹')
      fireEvent.change(entry, { target: { value: '102' } })
      fireEvent.change(screen.getByLabelText('Stop loss trigger ₹'), { target: { value: '91' } })
      fireEvent.change(screen.getByLabelText('Profit target ₹'), { target: { value: '140' } })
      entry.focus()
      net = 42.25
      premium = 110
      await act(async () => vi.advanceTimersByTimeAsync(1000))
      expect(screen.getByText('₹42.25')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Select 22600 CE' })).toHaveTextContent('₹110.00')
      expect(screen.getByLabelText('Entry limit ₹')).toBe(entry)
      expect(entry).toHaveFocus()
      expect(entry).toHaveValue(102)
      expect(screen.getByLabelText('Lots')).toHaveValue(3)
      expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(91)
      expect(screen.getByLabelText('Profit target ₹')).toHaveValue(140)
      expect(screen.getByLabelText('Strike')).toHaveValue('22600')
      expect(screen.getByLabelText('Expiry')).toHaveValue('19OCT99')
      expect(screen.getByLabelText('Chart timeframe')).toHaveValue('15m')
    } finally {
      view.unmount()
      vi.useRealTimers()
    }
  })
})
