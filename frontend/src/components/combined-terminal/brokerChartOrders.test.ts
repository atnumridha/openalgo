import { expect, it } from 'vitest'
import type { CombinedSnapshot } from '@/api/combinedTerminal'
import { brokerChartOrders } from './brokerChartOrders'
const now = 1793730000
const symbol = 'NIFTY03NOV2623600CE'
const order = (extra: Record<string,unknown> = {}) => ({ connection_id:'neo', broker:'kotak', orderid:'42', symbol, exchange:'NFO', action:'BUY', quantity:130, filled_quantity:65, price:100, pricetype:'LIMIT', order_status:'open', data_fresh:true, ...extra })
const snapshot = (orders: Record<string,unknown>[], positions: unknown[] = []) => ({mode:'live',updated_at:now,connections:[{connection:{id:'neo',broker:'kotak',mode:'live'},captured_at:now,books_complete:true,quotes_fresh:true,error:null}],orders,positions}) as unknown as CombinedSnapshot
it('draws externally placed pending Kotak orders at their broker limit with remaining units',()=>{
 const data=brokerChartOrders(snapshot([order()]),symbol,'NFO',now)
 expect(data.orders).toHaveLength(1)
 expect(data.orders[0]).toMatchObject({remaining:65,side:'BUY',kind:'Limit',price:100})
 expect(data.levels).toContainEqual(expect.objectContaining({price:100,title:expect.stringMatching(/Kotak Neo.*BUY 65/)}))
})
it('draws SL at its trigger, not at its protected limit',()=>{
 const data=brokerChartOrders(snapshot([order({pricetype:'SL',trigger_price:95,price:94,action:'SELL'})]),symbol,'NFO',now)
 expect(data.levels).toContainEqual(expect.objectContaining({price:95,title:expect.stringContaining('SL')}))
 expect(data.levels.some(l=>l.price===94)).toBe(false)
})
it.each(['complete','completed','cancelled','canceled','rejected'])('removes %s orders from active lines',status=>{
 expect(brokerChartOrders(snapshot([order({order_status:status})]),symbol,'NFO',now).orders).toEqual([])
})
it('does not put another option, exchange, account mode or stale orders on this chart',()=>{
 const s=snapshot([order({symbol:'NIFTY03NOV2623600PE'}),order({exchange:'NSE'}),order({connection_id:'other'}),order({data_fresh:false})])
 expect(brokerChartOrders(s,symbol,'NFO',now).levels).toEqual([])
 expect(brokerChartOrders(snapshot([order()]),symbol,'NFO',now+11).levels).toEqual([])
 s.connections[0].connection.mode='analyze'
 expect(brokerChartOrders(s,symbol,'NFO',now).levels).toEqual([])
})
it('deduplicates account-scoped order IDs while allowing the same ID at another broker',()=>{
 const s=snapshot([order(),order(),order({connection_id:'flat',broker:'flattrade'})])
 s.connections.push({...s.connections[0],connection:{id:'flat',broker:'flattrade',mode:'live'} as never})
 expect(brokerChartOrders(s,symbol,'NFO',now).orders).toHaveLength(2)
})
it('uses no imaginary limit for a pending market order or unknown fill quantity',()=>{
 const data=brokerChartOrders(snapshot([order({pricetype:'MARKET',price:0}),order({orderid:'43',filled_quantity:undefined})]),symbol,'NFO',now)
 expect(data.orders).toHaveLength(2)
 expect(data.levels).toEqual([])
})
it('shows a broker position average even without a live mark and never labels a planned SL as accepted',()=>{
 const s=snapshot([], [{connection_id:'neo',broker:'kotak',symbol,exchange:'NFO',quantity:65,average_entry:100,managed:true,status:'protection_pending',current_sl:95,target:110,data_fresh:false}])
 expect(brokerChartOrders(s,symbol,'NFO',now).levels).toEqual(expect.arrayContaining([expect.objectContaining({price:100,title:expect.stringContaining('position avg')})]))
 expect(brokerChartOrders(s,symbol,'NFO',now).levels.some(l=>l.price===95)).toBe(false)
})


it('does not recreate a cancelled broker SL from lagging controller status', () => {
 const s=snapshot([order({action:'SELL',pricetype:'SL',trigger_price:95,price:94,order_status:'cancelled'})], [{connection_id:'neo',broker:'kotak',symbol,exchange:'NFO',quantity:65,average_entry:100,managed:true,status:'protected',current_sl:95,target:110,data_fresh:true}])
 expect(brokerChartOrders(s,symbol,'NFO',now).levels.some(l=>l.price===95)).toBe(false)
})
it('omits explicitly unverified broker position averages', () => {
 const s=snapshot([], [{connection_id:'neo',broker:'kotak',symbol,exchange:'NFO',quantity:65,average_entry:100,average_entry_verified:false,managed:true,status:'protected',data_fresh:true}])
 expect(brokerChartOrders(s,symbol,'NFO',now).levels).toEqual([])
})
