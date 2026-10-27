import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NeoTradingTools } from './NeoTradingTools'
import { scalpingApi } from '@/api/scalping'
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
  const target = () => ({
    loadSymbol,
    listIndicators: () => [],
    addIndicatorById: async () => {},
    dataUnavailable: () => unavailable,
    replayActive: () => false,
    replayPickingBar: () => false,
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <NeoTradingTools target={target as never} revision={1} />
    </QueryClientProvider>
  )
  await screen.findAllByLabelText('NIFTY expiry')
  expect(loadSymbol).not.toHaveBeenCalled()
  unavailable = false
  // Native boot can finish without another workspace revision.

  await waitFor(() =>
    expect(loadSymbol).toHaveBeenCalledWith({ symbol: 'NIFTY', exchange: 'NSE_INDEX' })
  )
})

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-10-13T10:00:00+05:30'))
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  localStorage.removeItem('neo.native.chart.indicators')
})

it('labels the same strike oppositely for calls and puts and shows the selected moneyness', async () => {
  const target = () => ({
    loadSymbol: async () => {},
    listIndicators: () => [],
    addIndicatorById: async () => {},
    dataUnavailable: () => false,
    replayActive: () => false,
    replayPickingBar: () => false,
  })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoTradingTools target={target as never} revision={1} />
    </QueryClientProvider>
  )
  await waitFor(() => expect(screen.getByRole('button', { name: 'Chart PE' })).toBeEnabled())
  const labels = (side: string) =>
    Array.from((screen.getByLabelText(`${side} strike`) as HTMLSelectElement).options).map(
      (o) => o.textContent
    )
  expect(labels('CE')).toEqual(['22650 · ITM', '22700 · ATM', '22750 · OTM'])
  expect(labels('PE')).toEqual(['22650 · OTM', '22700 · ATM', '22750 · ITM'])
  fireEvent.change(screen.getByLabelText('CE strike'), { target: { value: '22750' } })
  fireEvent.change(screen.getByLabelText('PE strike'), { target: { value: '22650' } })
  expect(screen.getByLabelText('Selected option moneyness')).toHaveTextContent('CE 22750 · OTM')
  expect(screen.getByLabelText('Selected option moneyness')).toHaveTextContent('PE 22650 · OTM')
})

it.each([
  {
    atm: 22700,
    ceLabel: 'ITM1',
    peLabel: 'OTM1',
    expectedCE: '22650 · ITM1',
    expectedPE: '22650 · OTM1',
  },
  {
    atm: undefined,
    ceLabel: '',
    peLabel: '',
    expectedCE: '22650 · Unclassified',
    expectedPE: '22650 · Unclassified',
  },
])('preserves broker strike-distance labels and never invents a classification without ATM ($expectedCE)', async (f) => {
  vi.spyOn(scalpingApi, 'getStrikes').mockResolvedValue({
    status: 'success',
    underlying: 'NIFTY',
    fo_exchange: 'NFO',
    expiry_date: '19OCT26',
    atm_strike: f.atm,
    chain: [
      {
        strike: 22650,
        ce: { symbol: 'NIFTY19OCT2622650CE', label: f.ceLabel },
        pe: { symbol: 'NIFTY19OCT2622650PE', label: f.peLabel },
      },
    ],
  })
  const target = () => ({
    loadSymbol: async () => {},
    listIndicators: () => [],
    addIndicatorById: async () => {},
    dataUnavailable: () => false,
    replayActive: () => false,
    replayPickingBar: () => false,
  })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoTradingTools target={target as never} revision={1} />
    </QueryClientProvider>
  )
  await waitFor(() => expect(screen.getByRole('button', { name: 'Chart PE' })).toBeEnabled())
  expect((screen.getByLabelText('CE strike') as HTMLSelectElement).options[0].textContent).toBe(
    f.expectedCE
  )
  expect((screen.getByLabelText('PE strike') as HTMLSelectElement).options[0].textContent).toBe(
    f.expectedPE
  )
})

it('never lets delayed default initialization replace a manual option selection after failed restoration', async () => {
  vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
  vi.setSystemTime(new Date('2026-10-13T10:00:00+05:30'))
  let unavailable = true
  const loadSymbol = vi.fn(async () => {
    unavailable = false
  })
  const target = () => ({
    loadSymbol,
    listIndicators: () => [],
    addIndicatorById: async () => {},
    dataUnavailable: () => unavailable,
    replayActive: () => false,
    replayPickingBar: () => false,
  })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoTradingTools target={target as never} revision={1} />
    </QueryClientProvider>
  )
  await waitFor(() => expect(screen.getByRole('button', { name: 'Chart CE' })).toBeEnabled())
  fireEvent.change(screen.getByLabelText('CE strike'), { target: { value: '22750' } })
  fireEvent.click(screen.getByRole('button', { name: 'Chart CE' }))
  await screen.findByText(/NIFTY19OCT2622750CE · nearest/)
  act(() => vi.advanceTimersByTime(500))
  await waitFor(() => expect(loadSymbol).toHaveBeenCalledTimes(1))
  expect(loadSymbol).toHaveBeenLastCalledWith({ symbol: 'NIFTY19OCT2622750CE', exchange: 'NFO' })
})

it('keeps a hidden context overlay off when changing option charts', async () => {
  let ids: string[] = []
  const target = () => ({
    loadSymbol: async () => {},
    listIndicators: () => ids.map((id) => ({ id, indicatorId: id })),
    addIndicatorById: async (id: string) => {
      ids.push(id)
    },
    removeIndicatorById: (id: string) => {
      ids = ids.filter((value) => value !== id)
    },
    dataUnavailable: () => false,
    replayActive: () => false,
    replayPickingBar: () => false,
  })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoTradingTools target={target as never} revision={1} />
    </QueryClientProvider>
  )
  const control = await screen.findByRole('checkbox', { name: 'Fair Value Gaps / levels' })
  await waitFor(() => expect(control).toBeEnabled())
  fireEvent.click(control)
  await waitFor(() => expect(control).not.toBeChecked())
  fireEvent.click(screen.getByRole('button', { name: 'Chart PE' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Chart PE' })).toBeEnabled())
  expect(ids).toEqual(['neo-donchian', 'rsi'])
})

it('does not request option expiries or the chain while the options panel is inactive', async () => {
  const expiry = vi.spyOn(scalpingApi, 'getExpiry')
  const strikes = vi.spyOn(scalpingApi, 'getStrikes')
  const target = () => null
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = (active: boolean) => (
    <QueryClientProvider client={client}>
      <NeoTradingTools target={target} revision={0} initialize={false} active={active} />
    </QueryClientProvider>
  )
  const view = render(content(false))
  expect(expiry).not.toHaveBeenCalled()
  expect(strikes).not.toHaveBeenCalled()
  view.rerender(content(true))
  await waitFor(() => expect(expiry).toHaveBeenCalled())
  await waitFor(() => expect(strikes).toHaveBeenCalled())
})

it('offers BB + Chikou separately and persists enabling and disabling it', async () => {
  let ids: string[] = ['neo-toolkit']
  const target = () => ({
    loadSymbol: async () => {},
    listIndicators: () => ids.map((id) => ({ id, indicatorId: id })),
    addIndicatorById: async (id: string) => {
      ids.push(id)
    },
    removeIndicatorById: (id: string) => {
      ids = ids.filter((value) => value !== id)
    },
    dataUnavailable: () => false,
    replayActive: () => false,
    replayPickingBar: () => false,
  })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoTradingTools
        target={target}
        revision={1}
        toolkit
        initialize={false}
        shownSymbol="NIFTY"
      />
    </QueryClientProvider>
  )
  const checkbox = await screen.findByRole('checkbox', { name: 'BB + Chikou · BULL / BEAR' })
  expect(screen.getByRole('checkbox', { name: 'Option buying · RSI + MACD' })).toBeChecked()
  expect(checkbox).not.toBeChecked()
  fireEvent.click(checkbox)
  await waitFor(() => expect(checkbox).toBeChecked())
  expect(ids).toEqual(['neo-toolkit', 'bb-chikou'])
  expect(JSON.parse(localStorage.getItem('neo.native.chart.indicators')!)).toContain('bb-chikou')
  fireEvent.click(checkbox)
  await waitFor(() => expect(checkbox).not.toBeChecked())
  expect(ids).toEqual(['neo-toolkit'])
})


it('offers all nine CALL/PUT controls independently without merging BB + Chikou', async () => {
  let ids: string[] = ['neo-toolkit']
  const target = () => ({ loadSymbol: async () => {}, listIndicators: () => ids.map(id => ({ id, indicatorId: id })),
    addIndicatorById: async (id: string) => { ids.push(id) }, removeIndicatorById: (id: string) => { ids = ids.filter(x => x !== id) },
    dataUnavailable: () => false, replayActive: () => false, replayPickingBar: () => false })
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <NeoTradingTools target={target} revision={1} toolkit initialize={false} shownSymbol="NIFTY" />
  </QueryClientProvider>)
  for (const short of ['RSI', 'BB', 'IV', 'IMI', 'MFI', 'PCR', 'OI', 'MACD', 'MA']) {
    const checkbox = screen.getByRole('checkbox', { name: `${short} · CALL / PUT` })
    expect(checkbox).not.toBeChecked()
    fireEvent.click(checkbox)
    await waitFor(() => expect(checkbox).toBeChecked())
  }
  expect(ids.filter(id => id.startsWith('nine-'))).toHaveLength(9)
  expect(screen.getByRole('checkbox', { name: 'BB + Chikou · BULL / BEAR' })).not.toBeChecked()
  fireEvent.click(screen.getByRole('checkbox', { name: 'RSI · CALL / PUT' }))
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'RSI · CALL / PUT' })).not.toBeChecked())
  expect(screen.getByRole('checkbox', { name: 'MACD · CALL / PUT' })).toBeChecked()
})
