import { expect, it } from 'vitest'
import { scalperReview, scalperSeconds } from './deltaScalperReview'
import type { DeltaChartState, DeltaManagedPlan } from '@/api/deltaChart'
import type { DeltaRiskContext } from './deltaRisk'
const state = {
  symbol: 'BTCUSD',
  product: { tick_size: 0.5, contract_value: 1 },
  position: { size: 1, entry: 100 },
  orders: [
    {
      id: 'sl',
      kind: 'sl',
      type: 'market_order',
      reduce_only: true,
      side: 'sell',
      state: 'open',
      unfilled: 1,
      price: 103,
    },
  ],
  accounting: {
    fee_status: 'verified',
    exit_fee_basis: 'taker',
    position_entry_fees: 1,
    estimated_exit_fee: 1,
    position_net_after_fees: 10,
  },
} as unknown as DeltaChartState
const plan = { first_fill_at: 100, stop: 103, stop_order_id: 'sl' } as DeltaManagedPlan
const context = { direction: 'up', entryAligned: true } as DeltaRiskContext
it('reviews 30 seconds before the window, retains protected profitable aligned trends, and exits otherwise', () => {
  expect(scalperReview(state, plan, context, 1869)).toBeNull()
  expect(scalperReview(state, plan, context, 1870)).toBe('hold')
  expect(scalperReview(state, plan, { ...context, direction: 'sideways' }, 1870)).toBe('exit')
  expect(
    scalperReview(
      { ...state, accounting: { ...state.accounting!, position_net_after_fees: -1 } },
      plan,
      context,
      1870
    )
  ).toBe('exit')
  expect(
    scalperReview({ ...state, orders: [{ ...state.orders[0], price: 99 }] }, plan, context, 1870)
  ).toBe('exit')
  expect(scalperReview(state, { ...plan, first_fill_at: null }, context, 4000)).toBeNull()
})
it('never promises the offer on excluded contracts and uses the official futures windows', () => {
  expect(scalperSeconds('BTCUSD')).toBe(1800)
  expect(scalperSeconds('ETHUSD')).toBe(1800)
  expect(scalperSeconds('SOLUSD')).toBe(900)
  expect(scalperSeconds('XAUTUSD')).toBeNull()
  expect(scalperReview({ ...state, symbol: 'XAUTUSD' }, plan, context, 5000)).toBeNull()
})

it.each([
  { orders: [] },
  ...[
    { id: 'foreign' },
    { unfilled: 0 },
    { state: 'cancelled' },
    { reduce_only: false },
    { type: 'limit_order' },
    { side: 'buy' },
  ].map((change) => ({ orders: [{ ...state.orders[0], ...change }] })),
])('cannot HOLD a winner without a verified full protective stop: %j', ({ orders }) => {
  expect(scalperReview({ ...state, orders } as DeltaChartState, plan, context, 1870)).toBe('exit')
})
