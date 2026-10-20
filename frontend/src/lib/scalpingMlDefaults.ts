import type { MLPlan } from '@/api/scalping'
import type { ProtectionConfig } from '@/lib/scalpingRisk'
import type { ScalpingAction } from '@/types/scalping'

export interface MLTicketStamp {
  model_version: string
  signal_time: number
  entry: number
  stop: number
  target: number
}
export interface MLTicketContext { symbol: string; quantity: number; leverage: number; previewSide?: ScalpingAction }

/** A preview may show HOLD proposals, but missing/stale/mismatched data clears it. */
export function mlDefaultsTicket(data: MLPlan | undefined, action: ScalpingAction,
  context: MLTicketContext, now = Date.now() / 1000) {
  if (!data || data.symbol !== context.symbol || data.quantity !== context.quantity || data.leverage !== context.leverage)
    return null
  for (const [stamp, maxAge] of [[data.updated_at, 15], [data.signal_time, 90], [data.quote_time, 10]] as const) {
    if (stamp == null || !Number.isFinite(stamp) || now - stamp < 0 || now - stamp > maxAge) return null
  }
  if (!data.model_version) return null
  const plan = data.plans.find(p => p.side === (action === 'BUY' ? 'LONG' : 'SHORT'))
  if (!plan || ![plan.entry, plan.stop, plan.target].every(v => v != null && Number.isFinite(v) && v > 0)) return null
  const entry = plan.entry!, stop = plan.stop!, target = plan.target!
  const sign = action === 'BUY' ? 1 : -1
  if (sign * (entry - stop) <= 0 || sign * (target - entry) <= 0) return null
  const config: ProtectionConfig = {
    slOn: true, slValue: String(Number(Math.abs(entry - stop).toFixed(10))), slUnit: 'PTS',
    tgtOn: true, tgtValue: String(Number(Math.abs(target - entry).toFixed(10))), tgtUnit: 'PTS',
    slAsOf: data.signal_time,
  }
  const stamp: MLTicketStamp = {model_version: data.model_version, signal_time: data.signal_time!, entry, stop, target}
  return {entry, stop, target, config, stamp, plan}
}

export function mlEntryBlock(data: MLPlan | undefined, action: ScalpingAction,
  context: MLTicketContext, mode: string, now = Date.now() / 1000): string | null {
  const ticket = mlDefaultsTicket(data, action, context, now)
  if (!ticket) return 'Waiting for a fresh ML plan matching this contract, quantity and leverage.'
  if (!data!.research_qualified || data!.action === 'HOLD') return `ML HOLD — ${data!.reason}`
  if (mode === 'live') return 'ML defaults are research-only; live execution qualification is still required.'
  const side = action === 'BUY' ? 'LONG' : 'SHORT'
  if (data!.action !== side || !ticket.plan.eligible) return `ML has not approved the ${side} entry.`
  if (context.previewSide && context.previewSide !== action) return `Select the ${side} preview before submitting its ticket.`
  return null
}

/** Manual buttons use ML prices as defaults; the model does not authorize a click. */
export function mlManualEntryBlock(data: MLPlan | undefined, action: ScalpingAction,
  context: MLTicketContext, now = Date.now() / 1000): string | null {
  const ticket = mlDefaultsTicket(data, action, context, now)
  if (!ticket) return data?.plans.length === 0 && data.reason
    ? data.reason : 'Waiting for fresh defaults matching this contract, quantity and leverage.'
  if (ticket.plan.fits_risk !== true) return 'This side has no defaults within the risk limits.'
  return null
}
