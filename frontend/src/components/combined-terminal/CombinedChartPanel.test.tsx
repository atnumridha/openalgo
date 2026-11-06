import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { combinedTerminalApi } from '@/api/combinedTerminal'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { CombinedChartPanel, combinedChartContext } from './CombinedChartPanel'

vi.mock('@/api/combinedTerminal', async (load) => ({
  ...(await load<typeof import('@/api/combinedTerminal')>()),
  combinedTerminalApi: {
    config: vi.fn(),
    snapshot: vi.fn(),
    market: vi.fn(),
    configure: vi.fn(),
    preview: vi.fn(),
    enter: vi.fn(),
    mutateTrade: vi.fn(),
    select: vi.fn(),
  },
}))
const symbol = 'NIFTY03NOV2623300CE'
const now = () => Date.now() / 1000
const ref = (id: string) => ({
  id,
  owner: 'neo',
  broker: id === 'flat' ? 'flattrade' : 'kotak',
  account: `${id}-account`,
  mode: 'live',
})
const state = () => ({
  mode: 'live',
  updated_at: now(),
  setup_required: false,
  settings: { reminder_seconds: 120 },
  connections: ['kotak', 'flat'].map((id) => ({
    connection: ref(id),
    entry_ready: true,
    books_complete: true,
    quotes_fresh: true,
    captured_at: now(),
    funds: { availablecash: 8000 },
    error: null,
  })),
  day: {
    date: new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date()),
    entry_allowed: true,
    entries: 0,
    max_entries: 3,
    remaining_entries: 3,
    count_verified: true,
    loss_reached: false,
    profit_reached: false,
    net: 0,
    updated_at: now(),
  },
  summary: { complete: true, realized_net: 0, estimated_open_net: 0, estimated_total_net: 0 },
  positions: [
    {
      trade_id: '["flattrade","flat-account","live","trade","one"]',
      connection_id: 'flat',
      broker: 'flattrade',
      symbol,
      exchange: 'NFO',
      product: 'MIS',
      managed: true,
      quantity: 65,
      entry: 80,
      average_entry: 80,
      current_sl: 74,
      target: 92,
      status: 'protected',
      data_fresh: true,
    },
  ],
  history: [],
  fills: [],
  orders: [{connection_id:'flat',broker:'flattrade',orderid:'sl-flat',symbol,exchange:'NFO',action:'SELL',quantity:65,filled_quantity:0,pricetype:'SL',trigger_price:74,price:73.95,order_status:'open',data_fresh:true}],
})
const market = () => ({
  underlying: 'NIFTY',
  exchange: 'NFO',
  symbol,
  expiry: '03NOV26',
  expiries: ['03NOV26'],
  metadata: { lot: 65, tick: 0.05, freeze: 1800 },
  quote: { ltp: 80, bid: 79.95, ask: 80, time: now(), source: 'Flattrade' },
  template: { entry: 80, sl: 74, target: 92 },
  quotes: {},
})
function mount(symbolValue = symbol, exchange = 'NFO', onLevels = vi.fn()) {
  return {
    onLevels,
    ...render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <CombinedChartPanel symbol={symbolValue} exchange={exchange} onLevels={onLevels} />
      </QueryClientProvider>
    ),
  }
}
beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  useAuthStore.setState({
    user: { username: 'neo', broker: 'kotak', isLoggedIn: true, loginTime: null },
  })
  useThemeStore.setState({ appMode: 'live' })
  vi.mocked(combinedTerminalApi.config).mockResolvedValue({ enabled: true })
  vi.mocked(combinedTerminalApi.snapshot).mockImplementation(async () => state() as never)
  vi.mocked(combinedTerminalApi.market).mockImplementation(async () => market() as never)
  vi.mocked(combinedTerminalApi.select).mockResolvedValue({} as never)
})

it('shows combined accounts without placing or previewing any order', async () => {
  mount()
  expect(await screen.findByRole('combobox', { name: 'Order broker' })).toHaveValue('kotak')
  expect(screen.getByText('₹8,000.00')).toBeInTheDocument()
  expect(combinedTerminalApi.enter).not.toHaveBeenCalled()
  expect(combinedTerminalApi.preview).not.toHaveBeenCalled()
})
it('uses the selected broker and exact option for the ticket and levels', async () => {
  const { onLevels } = mount()
  fireEvent.change(await screen.findByRole('combobox', { name: 'Order broker' }), {
    target: { value: 'flat' },
  })
  await waitFor(() =>
    expect(combinedTerminalApi.market).toHaveBeenCalledWith(
      'flat',
      expect.objectContaining({ symbol, underlying: 'NIFTY', expiry: '03NOV26' })
    )
  )
  await waitFor(() =>
    expect(onLevels).toHaveBeenLastCalledWith(
      expect.objectContaining({
        symbol,
        exchange: 'NFO',
        levels: expect.arrayContaining([
          expect.objectContaining({ title: 'Flattrade SL SELL 65', price: 74 }),
        ]),
      })
    )
  )
  expect(combinedTerminalApi.enter).not.toHaveBeenCalled()
})
it('does not put option prices on an index chart', async () => {
  const { onLevels } = mount('NIFTY', 'NSE_INDEX')
  await screen.findByRole('combobox', { name: 'Order broker' })
  expect(screen.getByText(/Choose a CE or PE contract in chart Options/)).toBeInTheDocument()
  expect(combinedTerminalApi.market).not.toHaveBeenCalled()
  expect(onLevels).not.toHaveBeenCalledWith(
    expect.objectContaining({
      levels: expect.arrayContaining([expect.objectContaining({ price: 74 })]),
    })
  )
})
it('shows disconnected Flattrade with a blocked ticket and no Kotak fallback', async () => {
  const snapshot = state()
  snapshot.connections[1].entry_ready = false
  snapshot.connections[1].books_complete = false
  snapshot.connections[1].funds = null as never
  snapshot.connections[1].error = 'Flattrade login required'
  vi.mocked(combinedTerminalApi.snapshot).mockResolvedValue(snapshot as never)
  mount()
  fireEvent.change(await screen.findByRole('combobox', { name: 'Order broker' }), {
    target: { value: 'flat' },
  })
  expect((await screen.findAllByText('Flattrade login required')).length).toBeGreaterThan(0)
  expect(screen.getByRole('button', { name: 'Review Flattrade order' })).toBeDisabled()
  expect(combinedTerminalApi.enter).not.toHaveBeenCalled()
})
it('keeps a zero-fill pending entry visible with a coordinated cancel action', async () => {
  const snapshot = state()
  snapshot.positions[0].quantity = 0
  snapshot.positions[0].status = 'entry_pending'
  vi.mocked(combinedTerminalApi.snapshot).mockResolvedValue(snapshot as never)
  vi.mocked(combinedTerminalApi.mutateTrade).mockResolvedValue({ state: 'accepted' })
  mount()
  fireEvent.click(
    await screen.findByRole('button', { name: `Cancel entry ${symbol} on Flattrade` })
  )
  await waitFor(() =>
    expect(combinedTerminalApi.mutateTrade).toHaveBeenCalledWith(
      snapshot.positions[0].trade_id,
      'exit',
      expect.objectContaining({ request_id: expect.any(String) })
    )
  )
})
it('collapses without hiding the chart or triggering an order', async () => {
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Collapse combined orders' }))
  expect(screen.getByRole('button', { name: 'Expand combined orders' })).toBeVisible()
  expect(screen.queryByRole('combobox', { name: 'Order broker' })).not.toBeInTheDocument()
  expect(combinedTerminalApi.enter).not.toHaveBeenCalled()
})
it('keeps crypto and unsupported equities outside the combined option ticket', () => {
  expect(combinedChartContext('BTCUSD', 'DELTA')).toBeNull()
  expect(combinedChartContext('RELIANCE', 'NSE')).toBeNull()
  expect(combinedChartContext(symbol, 'NFO')).toEqual({
    underlying: 'NIFTY',
    expiry: '03NOV26',
    option: true,
  })
  expect(combinedChartContext('NIFTY', 'NSE_INDEX')).toEqual({
    underlying: 'NIFTY',
    expiry: '',
    option: false,
  })
})

it('preserves manual ticket prices while lots refresh and when a quote read fails', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <CombinedChartPanel symbol={symbol} exchange="NFO" />
    </QueryClientProvider>
  )
  await waitFor(() => expect(screen.getByLabelText('Entry price ₹')).toHaveValue(80))
  fireEvent.change(screen.getByLabelText('Entry price ₹'), { target: { value: '81' } })
  fireEvent.change(screen.getByLabelText('Stop loss trigger ₹'), { target: { value: '75' } })
  let resolve!: (value: never) => void
  vi.mocked(combinedTerminalApi.market).mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r
      })
  )
  fireEvent.change(screen.getByLabelText('Lots'), { target: { value: '2' } })
  expect(screen.getByLabelText('Entry price ₹')).toHaveValue(81)
  expect(screen.getByRole('button', { name: 'Review Kotak Neo order' })).toBeDisabled()
  resolve(market() as never)
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Review Kotak Neo order' })).toBeEnabled()
  )
  expect(screen.getByLabelText('Entry price ₹')).toHaveValue(81)
  vi.mocked(combinedTerminalApi.market).mockRejectedValueOnce(
    new Error('Quote temporarily unavailable')
  )
  await qc.invalidateQueries({ queryKey: ['combined-chart-market'] })
  await screen.findByText('Quote temporarily unavailable')
  expect(screen.getByLabelText('Entry price ₹')).toHaveValue(81)
  expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(75)
  expect(screen.getByRole('button', { name: 'Review Kotak Neo order' })).toBeDisabled()
})

it('shows the existing combined risk policy and profit milestone reminder', async () => {
  const snapshot = state()
  snapshot.day.profit_reached = true
  snapshot.day.net = 2100
  vi.mocked(combinedTerminalApi.snapshot).mockResolvedValue(snapshot as never)
  mount()
  expect(await screen.findByText(/Daily policy ·/)).toBeVisible()
  expect(await screen.findByRole('alert', { name: 'Daily limit warning' })).toBeVisible()
})

it('preserves edited ticket values when the panel is collapsed and reopened', async () => {
  mount()
  await waitFor(() => expect(screen.getByLabelText('Entry price ₹')).toHaveValue(80))
  fireEvent.change(screen.getByLabelText('Entry price ₹'), { target: { value: '81' } })
  fireEvent.click(screen.getByRole('button', { name: 'Collapse combined orders' }))
  fireEvent.click(screen.getByRole('button', { name: 'Expand combined orders' }))
  expect(screen.getByLabelText('Entry price ₹')).toHaveValue(81)
})

it('does not display an unverified combined entry count as zero', async () => {
  const snapshot = state()
  snapshot.day.count_verified = false
  snapshot.day.entry_allowed = false
  vi.mocked(combinedTerminalApi.snapshot).mockResolvedValue(snapshot as never)
  mount()
  expect(await screen.findByText(/Daily entry count pending/)).toBeVisible()
})


it('detects pending Kotak Neo orders even while Flattrade is selected for the ticket', async () => {
 const snapshot=state()
 snapshot.orders=[{connection_id:'kotak',broker:'kotak',orderid:'external42',symbol,exchange:'NFO',action:'BUY',quantity:130,filled_quantity:65,pricetype:'LIMIT',price:80,order_status:'open',data_fresh:true}] as never
 vi.mocked(combinedTerminalApi.snapshot).mockResolvedValue(snapshot as never)
 localStorage.setItem('combined-broker:neo:live','flat')
 const {onLevels}=mount()
 await screen.findByText(/1 open broker order/)
 await waitFor(()=>expect(onLevels).toHaveBeenLastCalledWith(expect.objectContaining({levels:expect.arrayContaining([expect.objectContaining({price:80,title:expect.stringMatching(/Kotak Neo.*BUY 65/)})])})))
 expect(combinedTerminalApi.enter).not.toHaveBeenCalled()
 expect(combinedTerminalApi.mutateTrade).not.toHaveBeenCalled()
})

it('supports a read-only broker order overlay on equity charts without an option ticket', async () => {
 const snapshot=state()
 snapshot.orders=[{connection_id:'kotak',broker:'kotak',orderid:'equity',symbol:'RELIANCE',exchange:'NSE',action:'BUY',quantity:10,filled_quantity:0,pricetype:'LIMIT',price:1300,order_status:'open',data_fresh:true}] as never
 vi.mocked(combinedTerminalApi.snapshot).mockResolvedValue(snapshot as never)
 const {onLevels}=mount('RELIANCE','NSE')
 await screen.findByText(/1 open broker order/)
 expect(screen.queryByRole('heading',{name:/Order ticket/})).not.toBeInTheDocument()
 await waitFor(()=>expect(onLevels).toHaveBeenLastCalledWith(expect.objectContaining({levels:expect.arrayContaining([expect.objectContaining({price:1300})])})))
 expect(combinedTerminalApi.market).not.toHaveBeenCalled()
})


it('shows unavailable broker books as unverified instead of zero live orders', async () => {
 const snapshot=state()
 for (const connection of snapshot.connections) { connection.books_complete=false; connection.captured_at=now()-60; connection.error='Unavailable' }
 vi.mocked(combinedTerminalApi.snapshot).mockResolvedValue(snapshot as never)
 const {onLevels}=mount()
 expect(await screen.findByText('Broker orders not verified')).toBeVisible()
 expect(screen.queryByText('0 open broker orders on this chart')).not.toBeInTheDocument()
 await waitFor(()=>expect(onLevels).toHaveBeenLastCalledWith(expect.objectContaining({levels:[]})))
})
