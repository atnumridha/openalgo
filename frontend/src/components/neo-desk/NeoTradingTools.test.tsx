import { useEffect } from 'react'
import { optionChainApi } from '@/api/option-chain'
import { useAuthStore } from '@/stores/authStore'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NeoTradingTools } from './NeoTradingTools'
import { scalpingApi } from '@/api/scalping'
vi.mock('./StrikeRsiData', () => ({StrikeRsiData: (p: {scope:string;active:boolean;onSnapshot:(snapshot:unknown)=>void}) => {
 useEffect(()=>{if(p.active)p.onSnapshot({scope:p.scope,values:{FARCE:{value:61.25,source:'live',time:Date.now()/1000},FARPE:{value:38.7,source:'closed',time:Date.now()/1000}},attempted:2,total:8})},[p.scope,p.active,p.onSnapshot]);return null
}}))
vi.mock('@/api/option-chain', () => ({optionChainApi:{getOptionChain:vi.fn()}}))
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
async function strikeOptions(side: string) {
  fireEvent.click(screen.getByLabelText(`${side} strike`))
  const list = await screen.findByRole('listbox', {name:`${side} strike choices`})
  const options = within(list).getAllByRole('option').map(option => ({
    value: option.getAttribute('data-value'), textContent: option.getAttribute('aria-label'),
  }))
  fireEvent.keyDown(screen.getByRole('combobox',{name:`Search ${side} strikes`}), {key:'Escape'})
  await waitFor(()=>expect(screen.queryByRole('listbox',{name:`${side} strike choices`})).not.toBeInTheDocument())
  return options
}
async function chooseStrike(side: string, value: string) {
  const trigger = screen.getByLabelText(`${side} strike`)
  await waitFor(()=>expect(trigger).toBeEnabled())
  fireEvent.click(trigger)
  const list = await screen.findByRole('listbox', {name:`${side} strike choices`})
  fireEvent.click(within(list).getByRole('option', {name:new RegExp(`^${value} ·`)}))
  await waitFor(()=>expect(trigger).toHaveAttribute('aria-expanded','false'))
  await waitFor(()=>expect(trigger).toBeEnabled())
}
it('allows a new contract selection while a previous contract history request is slow',async()=>{
 let finishFirst:()=>void=()=>{}
 const loadSymbol=vi.fn().mockImplementationOnce(()=>new Promise<void>(resolve=>{finishFirst=resolve})).mockResolvedValue(undefined)
 const target=()=>({loadSymbol,listIndicators:()=>[],addIndicatorById:async()=>{},removeIndicatorById:()=>{},dataUnavailable:()=>false,replayActive:()=>false,replayPickingBar:()=>false})
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><NeoTradingTools target={target} revision={0} initialize={false}/></QueryClientProvider>)
 await waitFor(()=>expect(screen.getByLabelText('CE strike')).toBeEnabled())
 fireEvent.click(screen.getByRole('button',{name:'Chart CE'}))
 await waitFor(()=>expect(loadSymbol).toHaveBeenCalledTimes(1))
 expect(screen.getByLabelText('PE strike')).toBeEnabled()
 await chooseStrike('PE','22650')
 expect(loadSymbol).toHaveBeenLastCalledWith({symbol:'NIFTY19OCT2622650PE',exchange:'NFO'})
 await act(async()=>finishFirst())
 expect(screen.getByRole('button',{name:'Chart PE'})).toHaveAttribute('aria-pressed','true')
})
it('opens readable strike data columns instead of a clipped native option label', async () => {
  const target = () => ({loadSymbol: vi.fn(async()=>{}), listIndicators:()=>[], addIndicatorById:async()=>{}, dataUnavailable:()=>false, replayActive:()=>false, replayPickingBar:()=>false})
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><NeoTradingTools target={target as never} revision={0} initialize={false}/></QueryClientProvider>)
  await waitFor(()=>expect(screen.getByLabelText('CE strike')).toBeEnabled())
  fireEvent.click(screen.getByLabelText('CE strike'))
  const list = await screen.findByRole('listbox', {name:'CE strike choices'})
  expect(within(list).getAllByRole('option')).toHaveLength(3)
  for (const label of ['Strike', 'Premium', 'RSI 14', 'Volume', 'OI'])
    expect(within(screen.getByLabelText('Strike data columns')).getByText(label)).toBeVisible()
  expect(screen.getByRole('combobox',{name:'Search CE strikes'})).toHaveFocus()
})
it('loads NIFTY with our indicators and automatically charts the exact selected CE/PE strike', async () => {
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
  await chooseStrike('PE', '22650')
  await waitFor(() =>
    expect(loadSymbol).toHaveBeenLastCalledWith({ symbol: 'NIFTY19OCT2622650PE', exchange: 'NFO' })
  )
  await waitFor(() => expect(screen.getByRole('button', { name: 'Chart CE' })).toBeEnabled())
  await chooseStrike('CE', '22750')
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
  useAuthStore.setState({apiKey:null,user:null})
  vi.mocked(optionChainApi.getOptionChain).mockReset()
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
  const labels = async (side: string) => (await strikeOptions(side)).map(option => option.textContent)
  expect(await labels('CE')).toEqual(['22700 · ATM · — · RSI — · Vol — · OI —', '22650 · ITM · — · RSI — · Vol — · OI —', '22750 · OTM · — · RSI — · Vol — · OI —'])
  expect(await labels('PE')).toEqual(['22700 · ATM · — · RSI — · Vol — · OI —', '22650 · OTM · — · RSI — · Vol — · OI —', '22750 · ITM · — · RSI — · Vol — · OI —'])
  await chooseStrike('CE', '22750')
  await chooseStrike('PE', '22650')
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
  expect((await strikeOptions('CE'))[0].textContent).toBe(
    `${f.expectedCE} · — · RSI — · Vol — · OI —`
  )
  expect((await strikeOptions('PE'))[0].textContent).toBe(
    `${f.expectedPE} · — · RSI — · Vol — · OI —`
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
  await chooseStrike('CE', '22750')
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
  const target = () => ({
    loadSymbol: async () => {},
    listIndicators: () => ids.map((id) => ({ id, indicatorId: id })),
    addIndicatorById: async (id: string) => {
      ids.push(id)
    },
    removeIndicatorById: (id: string) => {
      ids = ids.filter((x) => x !== id)
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
  for (const short of ['RSI', 'BB', 'IV', 'IMI', 'MFI', 'PCR', 'OI', 'MACD', 'MA']) {
    const checkbox = screen.getByRole('checkbox', { name: `${short} · CALL / PUT` })
    expect(checkbox).not.toBeChecked()
    fireEvent.click(checkbox)
    await waitFor(() => expect(checkbox).toBeChecked())
  }
  expect(ids.filter((id) => id.startsWith('nine-'))).toHaveLength(9)
  expect(screen.getByRole('checkbox', { name: 'BB + Chikou · BULL / BEAR' })).not.toBeChecked()
  fireEvent.click(screen.getByRole('checkbox', { name: 'RSI · CALL / PUT' }))
  await waitFor(() =>
    expect(screen.getByRole('checkbox', { name: 'RSI · CALL / PUT' })).not.toBeChecked()
  )
  expect(screen.getByRole('checkbox', { name: 'MACD · CALL / PUT' })).toBeChecked()
})

it('lets the candlestick study be enabled on its own while leaving other studies disabled', async () => {
  localStorage.setItem('neo.chart.toolkit.version', '2')
  localStorage.setItem('neo.native.chart.indicators', '[]')
  let applied: string[] = []
  const target = () => ({
    loadSymbol: async () => {},
    listIndicators: () => applied.map((id) => ({ id, indicatorId: id, name: id })),
    addIndicatorById: async (id: string) => {
      applied.push(id)
    },
    removeIndicatorById: (id: string) => {
      applied = applied.filter((value) => value !== id)
    },
    dataUnavailable: () => false,
    replayActive: () => false,
    replayPickingBar: () => false,
  })
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NeoTradingTools
        target={target}
        revision={1}
        toolkit
        initialize={false}
        active={false}
        shownSymbol="NIFTY"
      />
    </QueryClientProvider>
  )
  const choice = screen.getByRole('checkbox', { name: 'Candlestick probability · 2R / 10 candles' })
  expect(choice).not.toBeChecked()
  fireEvent.click(choice)
  await waitFor(() => expect(choice).toBeChecked())
  expect(applied).toEqual(['candle-probability'])
  expect(JSON.parse(localStorage.getItem('neo.native.chart.indicators')!)).toEqual([
    'candle-probability',
  ])
})


it('shows every strike in overall traded-volume order and keeps the chosen contract', async () => {
 useAuthStore.setState({apiKey:'key',user:{username:'test',broker:'test',isLoggedIn:true,loginTime:null}})
 let resolveFull: (data: unknown) => void = () => {}
 vi.mocked(optionChainApi.getOptionChain).mockImplementationOnce(() => new Promise(resolve=>{resolveFull=resolve as never}))
 const loadSymbol=vi.fn(async()=>{})
 const target=()=>({loadSymbol,listIndicators:()=>[],addIndicatorById:async()=>{},removeIndicatorById:()=>{},dataUnavailable:()=>false,replayActive:()=>false,replayPickingBar:()=>false})
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 render(<QueryClientProvider client={client}><NeoTradingTools target={target} revision={0} initialize={false} shownSymbol="NIFTY"/></QueryClientProvider>)
 await waitFor(()=>expect(screen.getByRole('button',{name:'Chart CE'})).toBeEnabled())
 await chooseStrike('CE', '22750')
 await act(async()=>resolveFull({status:'success',underlying:'NIFTY',expiry_date:'19OCT26',atm_strike:22700,chain:[
  {strike:18000,ce:{symbol:'FARCE',ltp:23.45,oi:100,volume:200},pe:{symbol:'FARPE',ltp:121.8,oi:5,volume:1}},
  {strike:22650,ce:{symbol:'LOWCE',ltp:0,oi:30,volume:10},pe:{symbol:'LOWPE',oi:50,volume:100}},
  {strike:22700,ce:{symbol:'ATMCE',oi:1,volume:1},pe:{symbol:'ATMPE',oi:1,volume:1}},
  {strike:22750,ce:{symbol:'HIGHCE',oi:30,volume:20},pe:{symbol:'HIGHPE',oi:10,volume:10}},
 ]}))
 await screen.findByText(/4 strikes.*most traded first/)
 const ceOptions=await strikeOptions('CE'), peOptions=await strikeOptions('PE')
 expect(ceOptions.map(o=>o.value)).toEqual(['18000','22650','22750','22700'])
 expect(peOptions.map(o=>o.value)).toEqual(['18000','22650','22750','22700'])
 expect(ceOptions[0].textContent).toContain('OI 105')
 expect(ceOptions[0].textContent).toContain('Vol 201')
 expect(ceOptions[0].textContent).toContain('₹23.45')
 expect(peOptions[0].textContent).toContain('₹121.80')
 expect(ceOptions[0].textContent).toContain('RSI 61.3 Live')
 expect(peOptions[0].textContent).toContain('RSI 38.7 Closed')
 expect(ceOptions[1].textContent).toContain('· — ·')
 expect(ceOptions[1].textContent).not.toContain('₹0.00')
 expect(screen.getByLabelText('CE strike')).toHaveTextContent('22750')
 expect(loadSymbol).toHaveBeenCalledTimes(1)
 expect(optionChainApi.getOptionChain).toHaveBeenCalledWith('key','NIFTY','NFO','19OCT26',null,{withGreeks:true})
 expect(screen.getByText(/4 strikes.*most traded first/)).toBeVisible()
 await chooseStrike('CE', '18000')
 await waitFor(()=>expect(loadSymbol).toHaveBeenLastCalledWith({symbol:'FARCE',exchange:'NFO'}))
})


it('automatically reloads the selected premium when its expiry changes', async () => {
 const loadSymbol=vi.fn(async()=>{})
 const target=()=>({loadSymbol,listIndicators:()=>[],addIndicatorById:async()=>{},removeIndicatorById:()=>{},dataUnavailable:()=>false,replayActive:()=>false,replayPickingBar:()=>false})
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><NeoTradingTools target={target} revision={0} initialize={false} shownSymbol="NIFTY"/></QueryClientProvider>)
 await waitFor(()=>expect(screen.getByRole('button',{name:'Chart CE'})).toBeEnabled())
 await chooseStrike('CE', '22750')
 await waitFor(()=>expect(loadSymbol).toHaveBeenLastCalledWith({symbol:'NIFTY19OCT2622750CE',exchange:'NFO'}))
 await waitFor(()=>expect(screen.getByLabelText('NIFTY expiry')).toBeEnabled())
 fireEvent.change(screen.getByLabelText('NIFTY expiry'),{target:{value:'27OCT26'}})
 await waitFor(()=>expect(loadSymbol).toHaveBeenLastCalledWith({symbol:'NIFTY27OCT2622750CE',exchange:'NFO'}))
 expect(screen.getByLabelText('CE strike')).toHaveTextContent('22750')
})
