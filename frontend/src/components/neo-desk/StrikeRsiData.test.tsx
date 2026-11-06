import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { scalpingApi } from '@/api/scalping'
import type { SymbolData } from '@/lib/MarketDataManager'
import { StrikeRsiData } from './StrikeRsiData'
const feed = vi.hoisted(() => ({
 subscribe: vi.fn((_symbol: string, _exchange: string, _mode: string, _onQuote: (quote: SymbolData) => void) => vi.fn()), getCachedData: vi.fn(),
 getState: () => ({isAuthenticated:true,isConnected:true,isPaused:false,connectionEpoch:1}),
 connect: vi.fn(async()=>{}),
}))
vi.mock('@/api/scalping',()=>({scalpingApi:{getHistory:vi.fn()}}))
vi.mock('@/contexts/MarketDataContext',()=>({useMarketDataContextOptional:()=>({manager:feed})}))
it('loads selected contracts first with at most two outstanding requests and cancels on close',async()=>{
 const pending: Array<{symbol:string;signal:AbortSignal;resolve:(value:unknown)=>void}>=[]
 vi.mocked(scalpingApi.getHistory).mockImplementation((symbol,_exchange,_interval,_date,request)=>new Promise(resolve=>pending.push({symbol,signal:request!.signal!,resolve:resolve as never})))
 const snapshot=vi.fn()
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 const view=render(<QueryClientProvider client={client}><StrikeRsiData scope="test" exchange="NFO" interval="1m" symbols={['FIRSTCE','FIRSTPE','NEXTCE','NEXTPE']} active loadPaused={false} onSnapshot={snapshot}/></QueryClientProvider>)
 await waitFor(()=>expect(pending).toHaveLength(2))
 expect(pending.map(p=>p.symbol)).toEqual(['FIRSTCE','FIRSTPE'])
 expect(feed.subscribe).not.toHaveBeenCalled()
 const now=Math.floor(Date.now()/60000)*60
 const candles=Array.from({length:30},(_,i)=>({time:now-(30-i)*60+19800,open:100,high:101,low:99,close:100,volume:10}))
 await act(async()=>pending[0].resolve({status:'success',symbol:'FIRSTCE',exchange:'NFO',interval:'1m',candles}))
 await waitFor(()=>expect(pending).toHaveLength(3))
 expect(pending[2].symbol).toBe('NEXTCE')
 expect(feed.subscribe).toHaveBeenCalledTimes(1)
 expect(feed.subscribe).toHaveBeenCalledWith('FIRSTCE','NFO','Quote',expect.any(Function))
 view.unmount()
 expect(feed.subscribe.mock.results[0].value).toHaveBeenCalledTimes(1)
 expect(pending[1].signal.aborted).toBe(true)
 expect(pending[2].signal.aborted).toBe(true)
})
it('coalesces a thousand quote events into one scheduled RSI update', async () => {
 vi.useFakeTimers()
 vi.clearAllMocks()
 const at=Date.parse('2026-10-30T13:15:10+05:30')
 vi.setSystemTime(at)
 const start=Math.floor(at/60000)*60
 const candles=Array.from({length:30},(_,i)=>({time:start-(29-i)*60+19800,open:100,high:101,low:99,close:100,volume:10}))
 vi.mocked(scalpingApi.getHistory).mockResolvedValue({status:'success',symbol:'FIRSTCE',exchange:'NFO',interval:'1m',date:null,candles})
 const snapshot=vi.fn()
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 const view=render(<QueryClientProvider client={client}><StrikeRsiData scope="burst" exchange="NFO" interval="1m" symbols={['FIRSTCE']} active loadPaused={false} onSnapshot={snapshot}/></QueryClientProvider>)
 try {
  await act(async()=>{await vi.advanceTimersByTimeAsync(0)})
  expect(feed.subscribe).toHaveBeenCalledTimes(1)
  const receive=feed.subscribe.mock.calls[0][3]
  vi.setSystemTime(at+1)
  for(let i=0;i<1000;i++) receive({symbol:'FIRSTCE',exchange:'NFO',lastUpdate:at+1,updateSource:'websocket',connectionEpoch:1,data:{ltp:110,timestamp:new Date(at+1).toISOString()}})
  expect(snapshot).toHaveBeenCalledTimes(1)
  await act(async()=>{await vi.advanceTimersByTimeAsync(1000)})
  expect(snapshot).toHaveBeenCalledTimes(2)
  expect(snapshot.mock.lastCall?.[0].values.FIRSTCE).toMatchObject({source:'live',value:100})
 } finally {view.unmount();client.clear();vi.useRealTimers()}
})
it('backs off the whole RSI queue when the broker fails instead of moving through every strike', async () => {
 vi.useFakeTimers()
 vi.mocked(scalpingApi.getHistory).mockReset().mockRejectedValue(new Error('Server disconnected'))
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 const view=render(<QueryClientProvider client={client}><StrikeRsiData scope="outage" exchange="NFO" interval="1m" symbols={['FIRSTCE','FIRSTPE','NEXTCE','NEXTPE']} active loadPaused={false} onSnapshot={vi.fn()}/></QueryClientProvider>)
 try {
  await act(async()=>{await vi.advanceTimersByTimeAsync(59000)})
  expect(scalpingApi.getHistory).toHaveBeenCalledTimes(2)
 } finally {view.unmount();client.clear();vi.useRealTimers()}
})
it('does not start RSI history requests while the selected chart is loading', async () => {
 vi.useFakeTimers()
 vi.mocked(scalpingApi.getHistory).mockReset().mockImplementation(()=>new Promise(()=>{}))
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 const snapshot=vi.fn()
 const content=(paused:boolean)=><QueryClientProvider client={client}><StrikeRsiData scope="primary-first" exchange="NFO" interval="1m" symbols={['FIRSTCE','FIRSTPE']} active loadPaused={paused} onSnapshot={snapshot}/></QueryClientProvider>
 const view=render(content(true))
 try {
  await act(async()=>{await vi.advanceTimersByTimeAsync(10000)})
  expect(scalpingApi.getHistory).not.toHaveBeenCalled()
  view.rerender(content(false))
  await act(async()=>{await vi.advanceTimersByTimeAsync(500)})
  expect(scalpingApi.getHistory).toHaveBeenCalledTimes(2)
  expect(vi.mocked(scalpingApi.getHistory).mock.calls[0][4]).toMatchObject({timeoutMs:65000})
 } finally {view.unmount();client.clear();vi.useRealTimers()}
})
