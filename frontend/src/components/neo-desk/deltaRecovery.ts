import type { DeltaChartState } from '@/api/deltaChart'
import type { DeltaTradeDefaults } from './deltaTradeDefaults'
export interface AutoRecovery {
  version: 1
  strategy?: string
  generation: string
  account: string
  symbol: string
  seconds: number
  settings: DeltaTradeDefaults
}
export const autoRecoveryKey = (
  account: string,
  symbol: string,
  seconds: number,
  strategy?: string
) =>
  `delta-chart:auto-resume:v1:${encodeURIComponent(account)}:${encodeURIComponent(symbol)}:${seconds}${strategy ? `:${encodeURIComponent(strategy)}` : ''}`
export function saveAutoRecovery(value: AutoRecovery): boolean {
  try {
    const text = JSON.stringify(value)
    localStorage.setItem(
      autoRecoveryKey(value.account, value.symbol, value.seconds, value.strategy),
      text
    )
    return (
      localStorage.getItem(
        autoRecoveryKey(value.account, value.symbol, value.seconds, value.strategy)
      ) === text
    )
  } catch {
    return false
  }
}
export function clearAutoRecovery(
  account: string,
  symbol: string,
  seconds: number,
  strategy?: string
): boolean {
  try {
    const k = autoRecoveryKey(account, symbol, seconds, strategy)
    try {
      localStorage.removeItem(k)
    } catch {
      localStorage.setItem(k, JSON.stringify({ revoked: true }))
    }
    const remaining = localStorage.getItem(k)
    return remaining === null || JSON.parse(remaining).revoked === true
  } catch {
    return false
  }
}
export function readAutoRecovery(
  account: string,
  symbol: string,
  seconds: number,
  strategy?: string
): AutoRecovery | null {
  const text = localStorage.getItem(autoRecoveryKey(account, symbol, seconds, strategy))
  if (text === null) return null
  const v = JSON.parse(text) as AutoRecovery & { revoked?: boolean }
  if (v?.revoked === true) return null
  if (
    !v ||
    typeof v.generation !== 'string' ||
    !v.generation ||
    v.version !== 1 ||
    v.account !== account ||
    v.symbol !== symbol ||
    v.seconds !== seconds ||
    v.strategy !== strategy ||
    !v.settings ||
    !Number.isInteger(v.settings.leverage) ||
    v.settings.leverage < 1 ||
    v.settings.leverage > 200 ||
    !(
      v.settings.balanceFraction === null ||
      [0.1, 0.25, 0.5, 0.75, 1].includes(v.settings.balanceFraction)
    ) ||
    typeof v.settings.manualQuantity !== 'string' ||
    !Number.isSafeInteger(Number(v.settings.manualQuantity)) ||
    Number(v.settings.manualQuantity) <= 0
  )
    throw Error('Invalid recovery settings')
  return v
}
/** The caller also verifies session, metadata, freshness and its durable intent ledger. */
export function recoveryPauseReason(state: DeltaChartState, seconds: number): string | null {
  if (state.pending?.length) return 'Waiting for pending Delta requests to reconcile.'
  if (!Array.isArray(state.managed_plans)) return 'Waiting for the managed-trade journal.'
  const active = state.managed_plans.filter(
    (p) => !['completed', 'cancelled', 'rejected'].includes(p.status)
  )
  if (state.position && state.position.size !== 0) {
    const pos = state.position
    const plan = active.find(
      (p) =>
        p.status === 'active' &&
        p.interval_seconds === seconds &&
        p.side === (pos.size > 0 ? 'buy' : 'sell') &&
        p.entry_price !== null &&
        Math.abs(p.entry_price - pos.entry) <= state.product.tick_size
    )
    if (!plan) return 'Waiting for verified ownership of the open trade.'
    const opposite = pos.size > 0 ? 'sell' : 'buy'
    const stop = state.orders.find(
      (o) =>
        o.id === plan.stop_order_id &&
        o.kind === 'sl' &&
        o.type === 'market_order' &&
        o.reduce_only &&
        o.side === opposite &&
        ['open', 'pending'].includes(o.state) &&
        o.unfilled >= Math.abs(pos.size) &&
        o.price !== null &&
        Math.abs(o.price - plan.stop) < state.product.tick_size / 2
    )
    const target = state.orders.find(
      (o) =>
        o.id === plan.target_order_id &&
        o.reduce_only &&
        o.post_only &&
        o.side === opposite &&
        ['open', 'pending'].includes(o.state) &&
        o.unfilled >= Math.abs(pos.size) &&
        o.price !== null &&
        Math.abs(o.price - plan.target) < state.product.tick_size / 2
    )
    if (!stop || !target) return 'Waiting for Delta to acknowledge the full SL and target.'
    if (active.length !== 1 || state.orders.some((o) => o.id !== stop.id && o.id !== target.id))
      return 'Waiting for remaining orders to reconcile.'
    return null
  }
  if (
    active.length ||
    state.orders.some((o) => !['closed', 'cancelled', 'canceled', 'filled'].includes(o.state))
  )
    return 'Waiting for existing orders and protection to reconcile.'
  return null
}

export function autoRecoveryAuthorized(
  account: string,
  symbol: string,
  seconds: number,
  generation: string,
  strategy?: string
): boolean {
  try {
    return readAutoRecovery(account, symbol, seconds, strategy)?.generation === generation
  } catch {
    return false
  }
}
