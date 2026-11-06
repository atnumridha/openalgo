import { describe, expect, it } from 'vitest'
import { optionQuality, previewLevels } from './optionQuality'
import type { OptionData } from '@/types/option-chain'

const leg = {symbol:'NIFTY03NOV2623050PE',ltp:100,bid:99.5,ask:100.5,bid_qty:130,ask_qty:65,lotsize:65,tick_size:0.05} as OptionData
const now = Date.parse('2026-10-30T09:00:00Z')
const feed = {connected:true,epoch:2}
const quote = {symbol:leg.symbol,exchange:'NFO',updateSource:'websocket' as const,connectionEpoch:2,lastUpdate:now,data:{ltp:101,timestamp:now/1000,bid_price:100,ask_price:102,bid_size:195,ask_size:130}}
describe('exact-contract liquidity', () => {
  it('uses own bid/ask, midpoint spread percent and depth in lots', () => {
    const q=optionQuality(leg,'NFO',undefined,now,feed)
    expect(q.spread).toBeCloseTo(1)
    expect(q.spreadPercent).toBeCloseTo(1)
    expect(q.bidLots).toBe(2); expect(q.askLots).toBe(1)
    expect(q.source).toBe('snapshot'); expect(q.ageSeconds).toBeNull()
  })
  it('uses exact-contract stream age only for the stream and never promotes merged cached depth', () => {
    const q=optionQuality(leg,'NFO',quote,now,feed)
    expect(q.source).toBe('snapshot');expect(q.ageSeconds).toBeNull();expect(q.streamAgeSeconds).toBe(0)
    expect(q.premium).toBe(101)
    expect(q.bidLots).toBe(2);expect(q.askLots).toBe(1)
    for(const changed of [{symbol:'OTHERCE'},{exchange:'BFO'},{connectionEpoch:1},{lastUpdate:now-16000},{data:{...quote.data,timestamp:(now-16000)/1000}}]) {
      expect(optionQuality(leg,'NFO',{...quote,...changed},now,feed).streamAgeSeconds).toBeNull()
    }
    const noDepth=optionQuality(leg,'NFO',{...quote,data:{ltp:101,timestamp:now/1000}},now,feed)
    expect(noDepth.bidLots).toBe(2);expect(noDepth.spread).toBe(1)
    expect(noDepth.source).toBe('snapshot')
  })
  it('does not call crossed or missing quotes liquid', () => {
    expect(optionQuality({...leg,bid:102,ask:100},'NFO',undefined,now,feed).spreadPercent).toBeNull()
    expect(optionQuality({...leg,lotsize:0},'NFO',undefined,now,feed).bidLots).toBeNull()
  })
})
describe('long CE and PE premium levels', () => {
  it('prefers ask for entry and a valid chart stop with a 2R target', () => {
    expect(previewLevels(100.03,0.05,[{price:90.03,source:'Support'}])).toEqual({entry:100.05,stop:90, target:120.15,source:'Support'})
  })
  it('skips a bearish stop above entry and does not invent a percentage SL', () => {
    expect(previewLevels(100,0.05,[{price:110,source:'Bearish BB'}])).toEqual({entry:100,stop:null,target:null,source:null})
  })
})
