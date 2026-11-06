import { scalperReview } from './deltaScalperReview'
import { useEffect, useRef, useState } from 'react'
import {
  deltaChartApi,
  type DeltaChartState,
  type DeltaManageAction,
  type DeltaAutoProtection,
  type DeltaOrderReference,
} from '@/api/deltaChart'
import {
  buildDeltaProtection,
  deltaRiskAtr,
  deltaTrailingStop,
  deltaRiskReductionStop,
  type DeltaRiskContext,
} from './deltaRisk'
const eligible = new Set([
  'awaiting_entry',
  'partial_fill',
  'placing_protection',
  'active',
  'closing',
  'cleanup',
  'pending',
])
const positive = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0
export function buildDeltaAdoption(
  state: DeltaChartState | null,
  context: DeltaRiskContext | null,
  anchorMark?: number,
  now = Date.now() / 1000
): {
  protection: DeltaAutoProtection
  existingStop: DeltaOrderReference | null
  existingTarget: DeltaOrderReference | null
} | null {
  if (
    !state?.connected ||
    state.environment !== 'india_prod' ||
    typeof state.account !== 'string' ||
    !state.account ||
    state.product?.symbol !== state.symbol ||
    !Number.isFinite(state.asof) ||
    !state.position ||
    state.symbol !== context?.symbol ||
    typeof state.position.version !== 'string' ||
    !state.position.version ||
    !Number.isFinite(state.position.size) ||
    now - state.asof > 10 ||
    now - state.asof < -5
  )
    return null
  const side = state.position.size > 0 ? 'buy' : 'sell'
  const mark = anchorMark ?? state.position.mark
  if (
    !positive(mark) ||
    !positive(state.position.mark) ||
    !positive(state.position.entry) ||
    state.position.size === 0
  )
    return null
  const protection = buildDeltaProtection(
    context,
    side,
    mark,
    state.product.tick_size,
    now,
    'position'
  )
  if (!protection) return null
  const legs = state.orders.filter(
    (order) =>
      (order.kind === 'sl' || order.kind === 'target') && ['open', 'pending'].includes(order.state)
  )
  if (legs.some((order) => !order.reduce_only || order.side === side || !order.version)) return null
  const stops = legs.filter((order) => order.kind === 'sl'),
    targets = legs.filter((order) => order.kind === 'target')
  if (stops.length > 1 || targets.length > 1) return null
  const existing = stops[0]
  if (existing && !positive(existing.price)) return null
  const stop = existing
    ? side === 'buy'
      ? Math.max(protection.stop, existing.price!)
      : Math.min(protection.stop, existing.price!)
    : protection.stop
  if (
    !positive(stop) ||
    (side === 'buy'
      ? stop >= state.position.mark ||
        protection.target <= Math.max(state.position.entry, state.position.mark)
      : stop <= state.position.mark ||
        protection.target >= Math.min(state.position.entry, state.position.mark))
  )
    return null
  return {
    protection: { ...protection, stop },
    existingStop: existing ? { id: existing.id, version: existing.version } : null,
    existingTarget: targets[0] ? { id: targets[0].id, version: targets[0].version } : null,
  }
}
export function chooseDeltaManagement(
  state: DeltaChartState | null,
  context: DeltaRiskContext | null,
  now = Date.now() / 1000,
  reconcileOnly = false
): DeltaManageAction | null {
  if (
    !state?.connected ||
    state.environment !== 'india_prod' ||
    !state.account ||
    !context ||
    state.symbol !== context.symbol ||
    now - state.asof > 10 ||
    now - state.asof < -5 ||
    deltaRiskAtr(context, now) === null ||
    context.sourceTime > now - context.intervalSeconds ||
    now - context.sourceTime > 2 * context.intervalSeconds + 10 ||
    !Array.isArray(state.managed_plans)
  )
    return null
  const plan = state.managed_plans.find(
    (item) =>
      item &&
      eligible.has(item.status) &&
      typeof item.id === 'string' &&
      item.id &&
      item.interval_seconds === context.intervalSeconds &&
      context.sourceTime >= item.source_time
  )
  if (!plan) return null
  const sync: DeltaManageAction = {
    plan_id: plan.id,
    decision: 'sync',
    source_time: context.sourceTime,
  }
  if (reconcileOnly || plan.status === 'pending') return sync
  if (state.pending?.length) return null
  if (plan.status !== 'active' && plan.status !== 'awaiting_entry') return sync
  const opposite =
    !plan.manual_entry &&
    context.sourceTime > plan.source_time &&
    context.direction === (plan.side === 'buy' ? 'down' : 'up')
  const entry = state.orders.find(
    (order) => order.id === plan.entry_order_id && order.side === plan.side && !order.reduce_only
  )
  if (opposite && entry && entry.unfilled === entry.size && entry.unfilled > 0)
    return { ...sync, decision: 'cancel_entry' }
  const position = state.position
  const ownedPosition =
    plan.status === 'active' &&
    positive(plan.entry_price) &&
    position &&
    positive(Math.abs(position.size)) &&
    position.size > 0 === (plan.side === 'buy') &&
    Math.abs(position.entry - plan.entry_price) <= state.product.tick_size
  if (opposite && ownedPosition) return { ...sync, decision: 'exit' }
  // The server owns the durable profit peak and can protect it with the browser closed.
  if (ownedPosition && plan.smart_profit_tracking) return sync
  if (ownedPosition && scalperReview(state, plan, context, now) === 'exit')
    return { ...sync, decision: 'exit' }
  if (
    !ownedPosition ||
    state.accounting?.fee_status !== 'verified' ||
    state.accounting.exit_fee_basis !== 'taker'
  )
    return sync
  const fees = [state.accounting.position_entry_fees, state.accounting.estimated_exit_fee]
  if (
    fees.some((fee) => typeof fee !== 'number' || !Number.isFinite(fee) || fee < 0) ||
    !positive(state.product.contract_value)
  )
    return sync
  const feePerCoin =
    ((fees[0] as number) + (fees[1] as number)) /
    (Math.abs(position.size) * state.product.contract_value)
  const stop = deltaTrailingStop(
    context,
    plan.side,
    plan.entry_price!,
    plan.initial_stop,
    plan.stop,
    position.mark,
    state.product.tick_size,
    feePerCoin,
    now,
    plan.manual_entry === true,
    10 / (85 * Math.abs(position.size) * state.product.contract_value)
  )
  if (stop !== null) return { ...sync, decision: 'trail', stop }
  const reduced = deltaRiskReductionStop(context, plan.side, plan.entry_price!, plan.initial_stop, plan.stop, position.mark, state.product.tick_size, now)
  return reduced === null ? sync : { ...sync, decision: 'reduce_risk', stop: reduced }
}
const storageKey = (state: DeltaChartState, planId: string) =>
  `delta-chart:manage:v1:${encodeURIComponent(state.account)}:${encodeURIComponent(state.symbol)}:${encodeURIComponent(planId)}`
export function useDeltaAutoManagement(
  enabled: boolean,
  state: DeltaChartState | null,
  context: DeltaRiskContext | null
) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const inFlight = useRef(false)
  const lastSnapshot = useRef('')
  const mounted = useRef(true)
  const scope = state ? `${state.account}:${state.symbol}:${context?.intervalSeconds}` : ''
  const liveScope = useRef(scope)
  liveScope.current = scope
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  useEffect(() => {
    setBusy(false)
    setMessage('')
  }, [scope])
  useEffect(() => {
    if (!enabled || !state || inFlight.current) return
    const action = chooseDeltaManagement(state, context)
    if (!action) return
    const snapshotKey = `${scope}:${state.asof}`
    if (lastSnapshot.current === snapshotKey) return
    lastSnapshot.current = snapshotKey
    const key = storageKey(state, action.plan_id)
    let body = action
    let record = ''
    try {
      const prior = sessionStorage.getItem(key)
      if (prior !== null) {
        const saved = JSON.parse(prior)
        if (
          saved?.plan_id !== action.plan_id ||
          saved?.account !== state.account ||
          saved?.symbol !== state.symbol
        )
          throw new Error('Invalid management intent')
        body = { plan_id: action.plan_id, decision: 'sync', source_time: action.source_time }
      }
      record = JSON.stringify({
        plan_id: action.plan_id,
        account: state.account,
        symbol: state.symbol,
        nonce: crypto.randomUUID(),
      })
      sessionStorage.setItem(key, record)
      if (sessionStorage.getItem(key) !== record) throw new Error('Management intent was not saved')
    } catch {
      setMessage('Automatic checks paused: intent storage unavailable.')
      return
    }
    inFlight.current = true
    setBusy(true)
    const submittedScope = scope
    void deltaChartApi
      .manage(body)
      .then((result) => {
        if (
          result.plan_id !== body.plan_id ||
          !['confirmed', 'pending', 'rejected'].includes(result.status)
        )
          throw new Error('Unmatched management acknowledgement')
        if (result.status !== 'pending' && sessionStorage.getItem(key) === record)
          sessionStorage.removeItem(key)
        if (mounted.current && liveScope.current === submittedScope) setMessage(result.message)
      })
      .catch(() => {
        if (mounted.current && liveScope.current === submittedScope)
          setMessage(
            'Automatic check outcome unknown; reconciling with the server before another decision.'
          )
      })
      .finally(() => {
        inFlight.current = false
        if (mounted.current && liveScope.current === submittedScope) setBusy(false)
      })
  }, [enabled, state, context, scope])
  return { busy, message }
}
