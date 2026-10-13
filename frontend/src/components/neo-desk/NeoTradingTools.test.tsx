import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NeoTradingTools } from './NeoTradingTools'
vi.mock('@/api/scalping', () => ({
  scalpingApi: {
    getExpiry: async () => ({ status: 'success', data: ['27OCT26', '19OCT26'] }),
    getStrikes: async (_u: string, _e: string, expiry: string) => ({
      status: 'success',
      expiry_date: expiry,
      atm_strike: 22700,
      chain: [22650, 22700, 22750].map((strike) => ({
        strike,
        ce: { symbol: `NIFTY${expiry}${strike}CE` },
        pe: { symbol: `NIFTY${expiry}${strike}PE` },
      })),
    }),
  },
}))
it('loads NIFTY with our indicators and charts the exact CE/PE selected strike without an order route', async () => {
  const applied: string[] = []
  const loadSymbol = vi.fn(async () => {})
  const target = () => ({
    loadSymbol,
    listIndicators: () => applied.map((indicatorId) => ({ indicatorId })),
    addIndicatorById: async (id: string) => {
      applied.push(id)
    },
    dataUnavailable: () => false,
    replayActive: () => false,
    replayPickingBar: () => false,
    currentInterval: () => '15m',
  })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoTradingTools target={target as never} revision={1} />
    </QueryClientProvider>
  )
  await waitFor(() =>
    expect(loadSymbol).toHaveBeenCalledWith({ symbol: 'NIFTY', exchange: 'NSE_INDEX' })
  )
  await waitFor(() => expect(applied).toEqual(['neo-donchian', 'neo-structure', 'rsi']))
  expect((screen.getByLabelText('NIFTY expiry') as HTMLSelectElement).value).toBe('19OCT26')
  expect(
    Array.from((screen.getByLabelText('NIFTY expiry') as HTMLSelectElement).options).map(
      (o) => o.value
    )
  ).toEqual(['27OCT26', '19OCT26'])
  await waitFor(() => expect(screen.getByRole('button', { name: 'Chart PE' })).toBeEnabled())
  fireEvent.change(screen.getByLabelText('PE strike'), { target: { value: '22650' } })
  fireEvent.click(screen.getByRole('button', { name: 'Chart PE' }))
  await waitFor(() =>
    expect(loadSymbol).toHaveBeenLastCalledWith({ symbol: 'NIFTY19OCT2622650PE', exchange: 'NFO' })
  )
  fireEvent.change(screen.getByLabelText('CE strike'), { target: { value: '22750' } })
  fireEvent.click(screen.getByRole('button', { name: 'Chart CE' }))
  await waitFor(() =>
    expect(loadSymbol).toHaveBeenLastCalledWith({ symbol: 'NIFTY19OCT2622750CE', exchange: 'NFO' })
  )
  expect(applied).toHaveLength(3)
})


it('waits for the restored native chart to finish before applying the default NIFTY chart', async () => {
  let unavailable = true
  const loadSymbol = vi.fn(async () => true)
  const target = () => ({loadSymbol, listIndicators: () => [], addIndicatorById: async () => {}, dataUnavailable: () => unavailable, replayActive: () => false, replayPickingBar: () => false})
  const client = new QueryClient({defaultOptions: {queries: {retry:false}}})
  render(<QueryClientProvider client={client}><NeoTradingTools target={target as never} revision={1} /></QueryClientProvider>)
  await screen.findAllByLabelText('NIFTY expiry')
  expect(loadSymbol).not.toHaveBeenCalled()
  unavailable = false
  // Native boot can finish without another workspace revision.

  await waitFor(() => expect(loadSymbol).toHaveBeenCalledWith({symbol:'NIFTY',exchange:'NSE_INDEX'}))
})


beforeEach(() => {
  vi.useFakeTimers({toFake:['Date']})
  vi.setSystemTime(new Date('2026-10-13T10:00:00+05:30'))
})
afterEach(() => vi.useRealTimers())
