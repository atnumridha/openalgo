import { expect, it } from 'vitest'
import type { DeltaChartState } from '@/api/deltaChart'
import type { CombinedSnapshot } from '@/api/combinedTerminal'
import { deltaBrokerGuide, combinedBrokerGuide } from './tradeGuidanceAdapters'
const now = Date.now() / 1000
it('uses actual Delta position size and accepted stop, not entry ticket size', () => {
  const state = { connected: true, symbol: 'BTCUSD', asof: now, product: { symbol: 'BTCUSD', contract_value: 0.001 }, ticker: { mark: 110 },
    position: { size: 2, entry: 100 }, orders: [{ kind: 'sl', side: 'sell', reduce_only: true, state: 'open', price: 105, size: 2, unfilled: 2 }],
    sizing: { currency: 'USD', maker_fee_rate: 0.0002, taker_fee_rate: 0.0005, fee_tax_rate: 0.18 },
    accounting: { currency: 'USD', balance: 9, position_entry_fees: 0.001, fee_status: 'verified' } } as unknown as DeltaChartState
  const result = deltaBrokerGuide(state, { quantity: 40, side: 'buy', plan: null, sourceTime: now })!
  expect(result.quantity).toBe(2)
  expect(result.plan?.stop).toBe(105)
  expect(result.plan?.protection).toBe('broker')
  expect(result.deltaFees?.entryPaid).toBe(0.001)
  expect(result.historyVerified).toBe(false)
})
it('does not estimate open-position paid fees when accounting is incomplete', () => {
  const state = { connected: true, symbol: 'BTCUSD', asof: now, product: { symbol: 'BTCUSD', contract_value: 0.001 }, ticker: {},
    position: { size: -2, entry: 100 }, orders: [], sizing: {}, accounting: { currency: 'USD', balance: null, fee_status: 'incomplete' } } as unknown as DeltaChartState
  const result = deltaBrokerGuide(state, { quantity: 1, side: 'sell', plan: null, sourceTime: now })!
  expect(result.deltaFees).toBeNull()
  expect(result.balance).toBeNull()
  expect(result.plan?.protection).toBe('missing')
})
it('scopes combined fills to the selected broker and never treats margin as balance', () => {
  const snapshot = { updated_at: now, connections: [{ connection: { id: 'flat', broker: 'flattrade' }, captured_at: now, books_complete: true, funds: { availablecash: 9999 } }], positions: [],
    fills: [{ connection_id: 'other', symbol: 'NIFTYPE', exchange: 'NFO', action: 'SELL', timestamp: now }, { connection_id: 'flat', symbol: 'NIFTYPE', exchange: 'NFO', action: 'SELL', timestamp: now - 5 }] } as unknown as CombinedSnapshot
  const result = combinedBrokerGuide(snapshot, 'flat', 'NIFTYPE', 'NFO', null, 1, null)!
  expect(result.broker).toBe('flattrade')
  expect(result.recentExitAt).toBe(now - 5)
  expect(result.balance).toBeNull()
})


it('marks incomplete combined account books unavailable even with a new capture time', () => {
 const snapshot = {updated_at:now,connections:[{connection:{id:'flat',broker:'flattrade'},captured_at:now,books_complete:false,error:'Book fetch failed'}],positions:[],fills:[]} as unknown as CombinedSnapshot
 expect(combinedBrokerGuide(snapshot,'flat','NIFTYPE','NFO',null,1,null)?.asOf).toBe(0)
})

it('rejects mismatched Delta contract metadata', () => {
 const state={connected:true,symbol:'BTCUSD',asof:now,product:{symbol:'ETHUSD'}} as unknown as DeltaChartState
 expect(deltaBrokerGuide(state,{quantity:1,side:'buy',plan:null,sourceTime:now})).toBeNull()
})


it('does not claim whole-position protection from a partial Delta stop or target', () => {
  const state = { connected: true, symbol: 'BTCUSD', asof: now, product: { symbol: 'BTCUSD', contract_value: 0.001 }, ticker: { mark: 110 },
    position: { size: 10, entry: 100 }, orders: [
      { kind: 'sl', side: 'sell', reduce_only: true, state: 'open', price: 105, size: 10, unfilled: 1 },
      { kind: 'target', side: 'sell', reduce_only: true, state: 'open', price: 120, size: 10, unfilled: 1 },
    ], sizing: {}, accounting: {} } as unknown as DeltaChartState
  const result = deltaBrokerGuide(state, { quantity: 10, side: 'buy', plan: null, sourceTime: now })!
  expect(result.plan?.stop).toBeNull()
  expect(result.plan?.target).toBeNull()
  expect(result.plan?.protection).toBe('missing')
})

it.each(['unprotected', 'protection_pending', 'unknown', 'closing'])('does not treat a %s combined position as broker protected', status => {
  const snapshot = { updated_at: now, connections: [{ connection: { id: 'flat', broker: 'flattrade' }, captured_at: now, books_complete: true }], fills: [],
    positions: [{ connection_id: 'flat', symbol: 'NIFTYPE', exchange: 'NFO', quantity: 65, remaining: 65, average_entry: 100, average_entry_verified: true, current_sl: 95, target: 110, managed: true, data_fresh: true, status }] } as unknown as CombinedSnapshot
  const result = combinedBrokerGuide(snapshot, 'flat', 'NIFTYPE', 'NFO', null, 1, null)!
  expect(result.plan?.protection).toBe('missing')
  expect(result.plan?.stop).toBeNull()
})

it('does not calculate outcomes from an explicitly unverified combined cost basis', () => {
  const snapshot = { updated_at: now, connections: [{ connection: { id: 'flat', broker: 'flattrade' }, captured_at: now, books_complete: true }], fills: [],
    positions: [{ connection_id: 'flat', symbol: 'NIFTYPE', exchange: 'NFO', quantity: 65, average_entry: 100, average_entry_verified: false, current_sl: 95, target: 110, managed: true, data_fresh: true, status: 'protected' }] } as unknown as CombinedSnapshot
  expect(combinedBrokerGuide(snapshot, 'flat', 'NIFTYPE', 'NFO', null, 1, null)?.plan).toBeNull()
})


it('accepts an actual fill-derived managed average while rejecting a planned-entry fallback', () => {
  const snapshot = { updated_at: now, connections: [{ connection: { id: 'flat', broker: 'flattrade' }, captured_at: now, books_complete: true }], fills: [],
    positions: [{ connection_id: 'flat', symbol: 'NIFTYPE', exchange: 'NFO', quantity: 65, average_entry: 101, entry: 100, current_sl: 95, target: 110, managed: true, data_fresh: true, status: 'protected' }] } as unknown as CombinedSnapshot
  expect(combinedBrokerGuide(snapshot, 'flat', 'NIFTYPE', 'NFO', null, 1, null)?.plan?.entry).toBe(101)
  delete snapshot.positions[0].average_entry
  expect(combinedBrokerGuide(snapshot, 'flat', 'NIFTYPE', 'NFO', null, 1, null)?.plan).toBeNull()
})


it('requires an actual full-quantity broker SL even when a managed position still says protected', () => {
 const snapshot={mode:'live',updated_at:now,connections:[{connection:{id:'flat',broker:'flattrade',mode:'live'},captured_at:now,books_complete:true}],fills:[],orders:[],positions:[{connection_id:'flat',symbol:'NIFTYPE',exchange:'NFO',quantity:65,average_entry:100,average_entry_verified:true,current_sl:95,target:110,managed:true,data_fresh:true,status:'protected'}]} as unknown as CombinedSnapshot
 expect(combinedBrokerGuide(snapshot,'flat','NIFTYPE','NFO',null,1,null)?.plan?.protection).toBe('missing')
 snapshot.orders=[{connection_id:'flat',orderid:'stop',symbol:'NIFTYPE',exchange:'NFO',action:'SELL',quantity:65,filled_quantity:0,trigger_price:95,price:94,pricetype:'SL',order_status:'open',data_fresh:true}]
 expect(combinedBrokerGuide(snapshot,'flat','NIFTYPE','NFO',null,1,null)?.plan).toMatchObject({stop:95,protection:'broker'})
 snapshot.orders[0].filled_quantity=1
 expect(combinedBrokerGuide(snapshot,'flat','NIFTYPE','NFO',null,1,null)?.plan?.protection).toBe('missing')
})
