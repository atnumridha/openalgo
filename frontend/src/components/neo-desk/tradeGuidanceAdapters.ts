import { brokerChartOrders } from '../combined-terminal/brokerChartOrders'
import type { DeltaChartState, DeltaAutoProtection } from '@/api/deltaChart'
import type { CombinedSnapshot, MarketSnapshot } from '@/api/combinedTerminal'
import type { GuideBrokerContext, GuidePlan } from './tradeGuidance'
const positive = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n) && n > 0

/** Copies display evidence only; never reviews, places or modifies an order. */
export function deltaBrokerGuide(state: DeltaChartState | null, selection: {
  quantity: number; side: 'buy' | 'sell'; plan: DeltaAutoProtection | null; sourceTime: number; source?: 'auto' | 'manual'
}): GuideBrokerContext | null {
  if (!state?.connected || !state.product || !state.symbol || state.product.symbol !== state.symbol) return null
  const position = state.position, inPosition = !!position && position.size !== 0
  const side = inPosition ? position!.size > 0 ? 'buy' : 'sell' : selection.side
  const opposite = side === 'buy' ? 'sell' : 'buy'
  // A single displayed level must cover the entire remaining position. Partial or
  // split-price protection is deliberately left unvalued instead of overstated.
  const coversPosition = (o: NonNullable<DeltaChartState['orders']>[number]) =>
    inPosition && o.reduce_only && o.side === opposite && ['open', 'pending'].includes(o.state) &&
    Number.isFinite(o.unfilled) && o.unfilled >= Math.abs(position!.size)
  const stop = state.orders?.find(o => o.kind === 'sl' && coversPosition(o))
  const target = state.orders?.find(o => o.kind === 'target' && coversPosition(o))
  const entry = side === 'buy' ? state.ticker?.bid : state.ticker?.ask
  let plan: GuidePlan | null = null
  if (inPosition && positive(position!.entry)) plan = { entry: position!.entry, stop: positive(stop?.price) ? stop.price : null,
    target: positive(target?.price) ? target.price : null, side, asOf: state.asof, label: 'Open Delta position', protection: positive(stop?.price) ? 'broker' : 'missing' }
  else if (selection.plan && positive(entry)) plan = { entry, stop: selection.plan.stop, target: selection.plan.target, side,
    asOf: selection.plan.source_time, label: selection.source === 'manual' ? 'Manual order planning levels' : 'Auto timeframe plan', protection: 'planned' }
  const accounting = state.accounting, sizing = state.sizing
  const balance = accounting?.currency === 'USD' && positive(accounting.balance)
    ? { amount: accounting.balance, currency: 'USD' as const, label: 'Delta wallet balance' } : null
  const rates = sizing?.currency === 'USD' && [sizing.maker_fee_rate, sizing.taker_fee_rate, sizing.fee_tax_rate].every(n => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 1)
  const paidVerified = !inPosition || accounting?.fee_status === 'verified' && typeof accounting.position_entry_fees === 'number' && Number.isFinite(accounting.position_entry_fees) && accounting.position_entry_fees >= 0
  const automation = state.automation
  const mark = state.ticker?.mark ?? state.ticker?.last
  return { symbol: state.symbol, exchange: 'DELTA', broker: 'delta', asOf: state.asof,
    quantity: inPosition ? Math.abs(position!.size) : selection.quantity, inPosition, lotSize: null, plan,
    quote: positive(mark) ? { price: mark, time: state.asof } : null, balance,
    historyVerified: false, // This endpoint returns recent fills, not a complete daily tradebook.
    execution: automation ? { summary: automation.context?.trend_summary ?? `1m: ${automation.context?.direction ?? 'checking'} · 5m: ${automation.context?.higher_direction ?? 'checking'}`,
      message: automation.message, checkedAt: automation.checked_at } : null,
    deltaFees: rates && paidVerified ? { contractValue: state.product.contract_value, maker: sizing!.maker_fee_rate,
      taker: sizing!.taker_fee_rate!, tax: sizing!.fee_tax_rate,
      entryPaid: inPosition ? accounting!.position_entry_fees : undefined } : null }
}

export function combinedBrokerGuide(snapshot: CombinedSnapshot | undefined, selected: string, symbol: string, exchange: string,
  market: MarketSnapshot | null | undefined, lots: number, values: { entry: number; sl: number; target: number } | null): GuideBrokerContext | null {
  const account = snapshot?.connections.find(c => c.connection.id === selected)
  if (!snapshot || !account) return null
  const p = snapshot.positions.find(p => p.connection_id === selected && p.symbol === symbol && p.exchange === exchange && p.quantity !== 0)
  const template = values ?? market?.template
  // Normal managed trades populate average_entry from reconciled fills. Adopted
  // positions explicitly mark an uncertain basis false; a ticket entry is never a fallback.
  const entry = p ? p.average_entry_verified !== false ? p.average_entry : null : template?.entry
  // Confirm current broker coverage as well as saved controller status: a direct
  // cancellation can arrive before the controller has reconciled its old SL.
  const stopOrder = p ? brokerChartOrders(snapshot, symbol, exchange, snapshot.updated_at).orders.find(o =>
    o.connectionId === selected && o.confirmed && o.kind === 'SL' &&
    o.side === (p.quantity > 0 ? 'SELL' : 'BUY') && o.remaining != null && o.remaining >= Math.abs(p.quantity)) : null
  const protectedPosition = p?.managed && p.status === 'protected' && p.data_fresh && !!stopOrder
  const stop = p ? protectedPosition ? stopOrder?.price : null : template?.sl
  const target = p ? p.target : template?.target
  const q = market?.quote
  const exits = snapshot.fills.filter(f => f.connection_id === selected && f.symbol === symbol && f.exchange === exchange && f.action === 'SELL' && positive(f.timestamp)).map(f => Number(f.timestamp))
  return { symbol, exchange, broker: account.connection.broker,
    asOf: account.books_complete && !account.error ? Math.min(snapshot.updated_at, account.captured_at) : 0,
    quantity: p ? Math.abs(p.quantity) : market?.metadata ? lots * market.metadata.lot : null,
    inPosition: !!p, lotSize: market?.metadata?.lot ?? null,
    plan: positive(entry) ? { entry, stop: positive(stop) ? stop : null, target: positive(target) ? target : null,
      side: p && p.quantity < 0 ? 'sell' : 'buy', asOf: snapshot.updated_at,
      label: p ? 'Selected broker position' : 'Selected order ticket', protection: p ? positive(stop) && protectedPosition ? 'broker' : 'missing' : 'planned' } : null,
    quote: q && positive(q.ltp) ? { price: q.ltp, time: q.time } : null,
    balance: null, // availablecash is margin; the snapshot does not provide a wallet/opening balance.
    historyVerified: account.books_complete && !account.error,
    recentExitAt: exits.length ? Math.max(...exits) : null }
}
