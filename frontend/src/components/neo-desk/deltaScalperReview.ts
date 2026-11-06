import type { DeltaChartState, DeltaManagedPlan } from '@/api/deltaChart'
import type { DeltaRiskContext } from './deltaRisk'
/** Official Delta windows; excluded contracts never receive a discount-based exit. */
export function scalperSeconds(symbol: string): number | null {
  if (['XAUTUSD', 'PAXGUSD', 'SLVONUSD'].includes(symbol)) return null
  return ['BTCUSD', 'ETHUSD'].includes(symbol) ? 1800 : 900
}
export function scalperReview(
  state: DeltaChartState,
  plan: DeltaManagedPlan,
  context: DeltaRiskContext,
  now: number
): 'exit' | 'hold' | null {
  const window = scalperSeconds(state.symbol),
    start = plan.first_fill_at
  if (
    window === null ||
    typeof start !== 'number' ||
    !Number.isFinite(start) ||
    start <= 0 ||
    start > now ||
    now - start < window - 30 ||
    !state.position
  )
    return null
  const p = state.position,
    a = state.accounting,
    coin = Math.abs(p.size) * state.product.contract_value
  const fees = (a?.position_entry_fees ?? NaN) + (a?.estimated_exit_fee ?? NaN)
  const net = a?.position_net_after_fees ?? NaN
  const stop = state.orders.find(
    (o) =>
      o.id === plan.stop_order_id &&
      o.kind === 'sl' &&
      o.type === 'market_order' &&
      o.reduce_only === true &&
      o.side === (p.size > 0 ? 'sell' : 'buy') &&
      ['open', 'pending'].includes(o.state) &&
      o.unfilled >= Math.abs(p.size) &&
      typeof o.price === 'number' &&
      Number.isFinite(o.price) &&
      o.price > 0
  )
  const locked = stop?.price ? (stop.price - p.entry) * (p.size > 0 ? 1 : -1) * coin : NaN
  const strong =
    context.direction === (p.size > 0 ? 'up' : 'down') && context.entryAligned !== false
  const earning =
    a?.fee_status === 'verified' &&
    a.exit_fee_basis === 'taker' &&
    Number.isFinite(fees) &&
    fees >= 0 &&
    Number.isFinite(net) &&
    net > 0 &&
    net >= Math.max(fees, state.product.tick_size * coin) &&
    locked >= fees
  return strong && earning ? 'hold' : 'exit'
}
