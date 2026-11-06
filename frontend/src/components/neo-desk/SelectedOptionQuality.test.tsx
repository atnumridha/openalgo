import { fireEvent, render, screen, within, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { OptionChainResponse, OptionData } from '@/types/option-chain'
import { SelectedOptionQuality } from './SelectedOptionQuality'
const subscribe=vi.fn(()=>vi.fn())
vi.mock('@/contexts/MarketDataContext',()=>({useMarketDataContextOptional:()=>({manager:{subscribe,
  getCachedData:()=>undefined,getState:()=>({isConnected:true,isAuthenticated:true,isPaused:false,connectionEpoch:2})}})}))
const leg=(side:string,bid:number,ask:number)=>({symbol:`NIFTY03NOV2623050${side}`,ltp:100,bid,ask,bid_qty:130,ask_qty:65,lotsize:65,
  volume:1234,oi:5678,implied_volatility:16.5,delta:side==='CE'?0.5:-0.5,theta:-5,vega:10} as OptionData)
it('joins only shared Quote streams while open and shows snapshot book data separately for each leg',async()=>{
 const data={expiry_date:'03NOV26',expiry_ts:Date.now()/1000+86400,server_ts:Date.now()/1000} as OptionChainResponse
 const view=render(<SelectedOptionQuality data={data} ce={leg('CE',99,101)} pe={leg('PE',98,102)} exchange="NFO" receivedAt={Date.now()}/> )
 expect(subscribe).not.toHaveBeenCalled()
 fireEvent.click(screen.getByText('Spread, depth & Greeks'))
 await waitFor(()=>expect(subscribe).toHaveBeenCalledTimes(2))
 expect(subscribe.mock.calls.every(call=>call[2]==='Quote')).toBe(true)
 for(const side of ['CE','PE']) {
  const card=screen.getByLabelText(`${side} contract quality`)
  expect(within(card).getByText(side==='CE'?'2.00%':'4.00%')).toBeVisible()
  expect(within(card).getByText('2.00 / 1.00 lots')).toBeVisible()
  expect(within(card).getByText('16.50%')).toBeVisible()
  expect(within(card).getByText('Chain snapshot · quote age unavailable')).toBeVisible()
 }
 view.unmount()
 for(const subscription of subscribe.mock.results)expect(subscription.value).toHaveBeenCalledOnce()
})
