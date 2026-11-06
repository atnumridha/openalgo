import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { optionChainApi } from '@/api/option-chain'
import type { SymbolData } from '@/lib/MarketDataManager'
import { useAuthStore } from '@/stores/authStore'
import { NeoTradingTools } from './NeoTradingTools'
const feed = vi.hoisted(() => ({
  callbacks: new Map<string, (quote: SymbolData) => void>(),
  state: { isConnected: true, isAuthenticated: true, isPaused: false, connectionEpoch: 1 },
  manager: {
    getState: () => feed.state, getCachedData: () => undefined, connect: async () => {},
    subscribe: (symbol: string, _exchange: string, _mode: string, callback: (quote: SymbolData) => void) => {
      feed.callbacks.set(symbol, callback)
      return () => { feed.callbacks.delete(symbol) }
    },
  },
}))
vi.mock('@/contexts/MarketDataContext', () => ({ useMarketDataContextOptional: () => ({ manager: feed.manager }) }))
vi.mock('./StrikeRsiData', () => ({ StrikeRsiData: () => null }))
vi.mock('@/api/option-chain', () => ({ optionChainApi: { getOptionChain: vi.fn() } }))
vi.mock('@/api/scalping', () => ({ scalpingApi: {
  getExpiry: async () => ({ status: 'success', data: ['03NOV26'] }),
  getStrikes: async () => ({ status: 'success', expiry_date: '03NOV26', atm_strike: 23300, chain: [] }),
} }))
const chain = (oi = 100, ltp = 80) => ({
  status: 'success' as const, underlying: 'NIFTY', underlying_symbol: 'NIFTY', underlying_exchange: 'NSE_INDEX',
  underlying_ltp: 23300, underlying_prev_close: 23200, expiry_date: '03NOV26', atm_strike: 23300,
  chain: [{ strike: 23300, ce: { symbol: 'CALL', label: 'ATM', ltp, bid: 79, ask: 80, bid_qty: 1, ask_qty: 1,
    open: 50, high: 90, low: 40, prev_close: 40, volume: 200, oi, lotsize: 65, tick_size: 0.05 }, pe: null }],
})
const target = () => ({ loadSymbol: async () => {}, listIndicators: () => [], addIndicatorById: async () => {},
  removeIndicatorById: () => {}, dataUnavailable: () => false, replayActive: () => false, replayPickingBar: () => false })
let client: QueryClient
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-11-02T12:46:00+05:30'))
  feed.callbacks.clear()
  feed.state = { isConnected: true, isAuthenticated: true, isPaused: false, connectionEpoch: 1 }
  useAuthStore.setState({ apiKey: 'test', user: { username: 'test', broker: 'kotak', isLoggedIn: true, loginTime: null } })
  vi.mocked(optionChainApi.getOptionChain).mockReset().mockResolvedValue(chain())
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
})
afterEach(() => { client.clear(); vi.useRealTimers() })
const content = (active = true) => <QueryClientProvider client={client}><NeoTradingTools target={target} revision={0} initialize={false} active={active}/></QueryClientProvider>
const settle = async (ms = 10) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms) }) }
const quote = (ltp: number, epoch = 1): SymbolData => ({ symbol: 'CALL', exchange: 'NFO', updateSource: 'websocket',
  connectionEpoch: epoch, lastUpdate: Date.now(), data: { ltp, volume: 450, bid_price: ltp - 0.05, ask_price: ltp + 0.05, timestamp: new Date().toISOString() } })
it('updates the open strike menu from live quotes without losing search or selection', async () => {
  render(content())
  await settle(100)
  await settle(100)
  expect(screen.getByRole('combobox', { name: 'CE strike' })).toHaveTextContent('₹80.00')
  fireEvent.click(screen.getByRole('combobox', { name: 'CE strike' }))
  const search = screen.getByRole('combobox', { name: 'Search CE strikes' })
  fireEvent.change(search, { target: { value: '23300' } })
  await settle(100)
  act(() => feed.callbacks.get('CALL')?.(quote(88)))
  await settle(1000)
  const row = within(screen.getByRole('listbox', { name: 'CE strike choices' })).getByRole('option')
  expect(row).toHaveTextContent('₹88.00')
  expect(row).toHaveTextContent('+120.00%')
  expect(row).toHaveTextContent('200')
  expect(search).toHaveValue('23300')
  expect(screen.getByRole('combobox', { name: 'CE strike' })).toHaveTextContent('23300 · ATM')
})
it('refreshes OI and snapshot prices within 15 seconds and stops when the panel is closed', async () => {
  const view = render(content())
  await settle(100)
  await settle(100)
  vi.mocked(optionChainApi.getOptionChain).mockResolvedValue(chain(175, 82))
  await settle(15000)
  expect(screen.getByRole('combobox', { name: 'CE strike' })).toHaveTextContent('₹82.00')
  fireEvent.click(screen.getByRole('combobox', { name: 'CE strike' }))
  expect(within(screen.getByRole('listbox')).getByRole('option')).toHaveTextContent('175')
  view.rerender(content(false))
  const count = vi.mocked(optionChainApi.getOptionChain).mock.calls.length
  await settle(30000)
  expect(optionChainApi.getOptionChain).toHaveBeenCalledTimes(count)
  expect(feed.callbacks.size).toBe(0)
})
it('rejects ticks from an earlier connection and drops streaming prices on disconnect', async () => {
  render(content())
  await settle(100)
  act(() => feed.callbacks.get('CALL')?.(quote(999, 0)))
  await settle(1000)
  expect(screen.getByRole('combobox', { name: 'CE strike' })).toHaveTextContent('₹80.00')
  act(() => feed.callbacks.get('CALL')?.(quote(88)))
  await settle(1000)
  expect(screen.getByRole('combobox', { name: 'CE strike' })).toHaveTextContent('₹88.00')
  feed.state.isConnected = false
  await settle(1000)
  expect(screen.getByRole('combobox', { name: 'CE strike' })).toHaveTextContent('₹80.00')
})
