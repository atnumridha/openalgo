import { expect, it } from 'vitest'
import type { SymbolData } from '@/lib/MarketDataManager'
import { mergeStrikeQuotes } from './useStrikeQuotes'
const rows = [{ strike: 23300, ce: { symbol: 'CALL', ltp: 80, prev_close: 40, bid: 79, ask: 80, volume: 200, oi: 100 }, pe: { symbol: 'PUT', ltp: 90 } }]
const tick = (data: SymbolData['data'], lastUpdate = 200): SymbolData => ({ symbol: 'CALL', exchange: 'NFO', lastUpdate, data })
it('keeps a newer full snapshot rather than rolling it back to cached tick data', () => {
  const result = mergeStrikeQuotes(rows, new Map([['CALL', tick({ ltp: 50, volume: 10 })]]), 250)
  expect(result[0].ce).toMatchObject({ ltp: 80, volume: 200, oi: 100, prev_close: 40 })
})
it('merges only the exact contract and leaves the source snapshot immutable', () => {
  const result = mergeStrikeQuotes(rows, new Map([['CALL', tick({ ltp: 88, volume: 450, bid_price: 87.95, ask_price: 88.05 })]]), 100)
  expect(result[0].ce).toMatchObject({ ltp: 88, volume: 200, bid: 79, ask: 80, oi: 100, prev_close: 40 })
  expect(result[0].pe?.ltp).toBe(90)
  expect(rows[0].ce.ltp).toBe(80)
})
it('ignores invalid prices, crossed books and negative volume instead of erasing valid snapshot values', () => {
  const result = mergeStrikeQuotes(rows, new Map([['CALL', tick({ ltp: NaN, volume: -1, bid_price: 90, ask_price: 80 })]]), 100)
  expect(result[0].ce).toMatchObject({ ltp: 80, volume: 200, bid: 79, ask: 80 })
})
it('preserves the snapshot book when a fresh quote carries cached depth and bid/ask', () => {
  const result = mergeStrikeQuotes(rows, new Map([['CALL', tick({ ltp: 88, bid_price: 87.95, ask_price: 88.05,
    depth: { buy: [{ price: 70, quantity: 1, orders: 1 }], sell: [{ price: 71, quantity: 1, orders: 1 }] } })]]), 100)
  expect(result[0].ce).toMatchObject({ ltp: 88, bid: 79, ask: 80 })
})
