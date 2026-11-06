import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
const io=vi.hoisted(()=>({subscribe:vi.fn((_symbol:string,_exchange:string,_mode:string,_callback:unknown)=>vi.fn()),getCachedData:vi.fn(),setAutoReconnect:vi.fn(),addStateListener:vi.fn(()=>vi.fn()),getState:vi.fn(()=>({connectionEpoch:1})),connect:vi.fn(),disconnect:vi.fn()}))
vi.mock('@/contexts/MarketDataContext',()=>({useMarketDataContextOptional:()=>({manager:io,isConnected:true,isAuthenticated:true,isPaused:false,isFallbackMode:false,connectionEpoch:1,error:null})}))
vi.mock('@/lib/MarketDataManager',()=>({MarketDataManager:{getInstance:()=>io}}))
import {useMarketData} from './useMarketData'
beforeEach(()=>vi.clearAllMocks())
it('subscribes once per instrument even when chart and trades repeat it',()=>{
 const symbol={symbol:'NIFTY',exchange:'NSE_INDEX'}
 const view=renderHook(({symbols})=>useMarketData({symbols}),{initialProps:{symbols:[symbol,symbol]}})
 expect(io.subscribe).toHaveBeenCalledTimes(1)
 view.rerender({symbols:[symbol]})
 expect(io.subscribe).toHaveBeenCalledTimes(1)
})
it('keeps independent subscription modes and unsubscribes on unmount',()=>{
 const view=renderHook(({mode})=>useMarketData({symbols:[{symbol:'NIFTY',exchange:'NSE_INDEX'}],mode}),{initialProps:{mode:'LTP' as 'LTP'|'Depth'}})
 const cleanup=io.subscribe.mock.results[0].value
 view.rerender({mode:'Depth'})
 expect(cleanup).toHaveBeenCalledOnce()
 expect(io.subscribe.mock.calls.at(-1)?.[2]).toBe('Depth')
 view.unmount()
 expect(io.subscribe.mock.results[1].value).toHaveBeenCalledOnce()
})

it('delivers consecutive ticks immediately without a polling timer',()=>{
 const view=renderHook(()=>useMarketData({symbols:[{symbol:'NIFTY',exchange:'NSE_INDEX'}]}))
 const callback=io.subscribe.mock.calls[0][3] as (value: unknown)=>void
 act(()=>callback({symbol:'NIFTY',exchange:'NSE_INDEX',data:{ltp:100},lastUpdate:1000,updateSource:'websocket'}))
 expect(view.result.current.data.get('NSE_INDEX:NIFTY')?.data.ltp).toBe(100)
 act(()=>callback({symbol:'NIFTY',exchange:'NSE_INDEX',data:{ltp:101},lastUpdate:1001,updateSource:'websocket'}))
 expect(view.result.current.data.get('NSE_INDEX:NIFTY')?.data.ltp).toBe(101)
})
