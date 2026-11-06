import { expect, it, vi } from 'vitest'
import { StrikeRsiCalculator } from './strikeRsi'
import { closeTime, ToolkitEngine } from '../chart-toolkit/model'
import { chartBars } from './tradingViewStudies'
const at = Date.parse('2026-10-30T13:15:00+05:30') / 1000
const observed = at + 10
const history = (symbol='TESTCE', length=30) => ({status:'success',symbol,exchange:'NFO',interval:'1m',candles:Array.from({length},(_,i)=>({time:at-(length-1-i)*60+19800,open:100,high:101,low:99,close:100,volume:10}))})
const quote = (symbol:string, price:number, time=(observed+1)*1000) => ({symbol,exchange:'NFO',data:{ltp:price,timestamp:new Date(time).toISOString()},lastUpdate:time,updateSource:'websocket' as const,connectionEpoch:1})
it('shows independent CE and PE RSI previews using the shared chart rule',()=>{
 const ce=new StrikeRsiCalculator('TESTCE','NFO','1m')
 const pe=new StrikeRsiCalculator('TESTPE','NFO','1m')
 expect(ce.load(history(),observed)).toBe(true)
 expect(pe.load(history('TESTPE'),observed)).toBe(true)
 expect(ce.value(quote('TESTCE',110),(observed+1)*1000,true,1)).toMatchObject({value:100,source:'live'})
 expect(pe.value(quote('TESTPE',90),(observed+1)*1000,true,1)).toMatchObject({value:0,source:'live'})
 expect(ce.value(undefined,(observed+1)*1000,false,1)).toMatchObject({value:50,source:'closed'})
})
it('requires matching history, enough candles, and fresh authenticated quotes',()=>{
 const r=new StrikeRsiCalculator('TESTCE','NFO','1m')
 expect(r.load(history('WRONG'),observed)).toBe(false)
 expect(r.value(quote('TESTCE',110),(observed+1)*1000,true,1).value).toBeNull()
 r.load(history('TESTCE',10),observed)
 expect(r.value(quote('TESTCE',110),(observed+1)*1000,true,1).value).toBeNull()
 r.load(history(),observed)
 for(const q of [quote('TESTPE',110),quote('TESTCE',110,(observed-20)*1000),{...quote('TESTCE',110),connectionEpoch:0}])
  expect(r.value(q,(observed+1)*1000,true,1).source).toBe('closed')
 expect(r.value(quote('TESTCE',110),(observed+1)*1000,false,1).source).toBe('closed')
})
it.each([14,15,30,250])('matches the chart Wilder RSI with %s history bars and fresh premium changes',length=>{
 const h=history('TESTCE',length)
 h.candles=h.candles.map((b,i)=>({...b,open:100+Math.sin(i)*5,close:100+Math.sin(i)*5,high:106,low:94}))
 const r=new StrikeRsiCalculator('TESTCE','NFO','1m');r.load(h,observed)
 const closed=chartBars(h.candles).filter(b=>closeTime(b,60,true)<=observed)
 const reference=new ToolkitEngine()
 const expected=reference.update(closed,{seconds:60,asOf:observed,indian:true}).current.rsi
 const closedValue=r.value(undefined,(observed+1)*1000,false,1).value
 if(expected==null)expect(closedValue).toBeNull();else expect(closedValue).toBeCloseTo(expected,9)
 for(const price of [99,104,96,102]){
  const forming={...chartBars(h.candles).at(-1)!,high:Math.max(106,price),low:Math.min(94,price),close:price}
  const expectedLive=reference.update([...closed,forming],{seconds:60,asOf:observed+1,indian:true}).current.rsi
  const liveValue=r.value(quote('TESTCE',price),(observed+1)*1000,true,1).value
  if(expectedLive==null)expect(liveValue).toBeNull();else expect(liveValue).toBeCloseTo(expectedLive,9)
 }
})
it('calculates strike RSI without running the strategy/structure engine for each contract',()=>{
 const engine=vi.spyOn(ToolkitEngine.prototype,'update')
 const r=new StrikeRsiCalculator('TESTCE','NFO','1m')
 r.load(history(),observed)
 for(let i=0;i<1000;i++)r.value(quote('TESTCE',100+i/1000),(observed+1)*1000,true,1)
 expect(engine).not.toHaveBeenCalled()
 engine.mockRestore()
})
