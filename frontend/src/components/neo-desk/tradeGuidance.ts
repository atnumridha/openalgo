import type { TrendDirection } from '../chart-toolkit/trendAnalysis'

export interface GuidePlan {
  entry: number
  stop: number | null
  target: number | null
  side: 'buy' | 'sell'
  asOf: number
  label: string
  protection: 'planned' | 'broker' | 'missing'
}
export interface GuideBrokerContext {
  symbol: string
  exchange: string
  broker: 'kotak' | 'flattrade' | 'delta'
  asOf: number
  quantity: number | null
  inPosition?: boolean
  lotSize: number | null
  plan: GuidePlan | null
  quote: { price: number; time: number } | null
  balance?: { amount: number; currency: 'USD' | 'INR'; label: string } | null
  recentExitAt?: number | null
  historyVerified: boolean
  execution?: { message: string; summary: string; checkedAt: number | null } | null
  deltaFees?: { contractValue: number; maker: number; taker: number; tax: number; entryPaid?: number | null } | null
}
export interface GuideTrend {
  direction: TrendDirection
  reason: string
  time: number | null
}
export const guideFresh = (time: number | null | undefined, now: number, age = 10) =>
  typeof time === 'number' && Number.isFinite(time) && time > 0 && time <= now + 5 && now - time <= age
const positive = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n) && n > 0

/** Display evidence only. No eligibility flags or order actions are produced. */
export function readTradeGuidance(input: {
  live: boolean; now: number; seconds: number; current: GuideTrend; higher: GuideTrend | null
  plan: GuidePlan | null; quote: { price: number; time: number } | null; tick: number
}) {
  const { live, current, higher, plan, quote, now, seconds } = input
  let headline = current.direction === 'up' ? 'Upward bias' : current.direction === 'down' ? 'Downward bias' : 'Mixed direction'
  let reason = current.reason
  if (!live) { headline = 'Historical review'; reason = 'Reviewing chart history. This is not a current entry reading.' }
  else if (!guideFresh(current.time == null ? null : current.time + seconds, now, seconds * 2 + 10) || current.direction === 'unavailable') {
    headline = 'Check live data'; reason = 'Waiting for a fresh completed candle. Last-known levels are for reference.'
  } else if (higher && higher.direction !== current.direction) {
    headline = 'Mixed direction'; reason = 'The chart timeframes do not agree. Check both readings before choosing a direction.'
  }
  const warnings: string[] = []
  if (live && (!quote || !positive(quote.price) || !guideFresh(quote.time, now))) {
    warnings.push('Live quote unavailable. Plan prices are estimates, not a current fill price.')
  } else if (live && quote && plan) {
    const sign = plan.side === 'buy' ? 1 : -1
    if (positive(plan.stop) && (quote.price - plan.stop) * sign <= 0)
      warnings.push('SL has been crossed by the latest quote. Check the actual broker position and exit status.')
    else if (positive(plan.target) && (quote.price - plan.target) * sign >= 0)
      warnings.push('Planned target has been crossed by the latest quote. Check for a fresh setup.')
    else if (plan.protection === 'planned' && (quote.price - plan.entry) * sign > Math.max(input.tick, 0))
      warnings.push('Price is beyond the planned entry. Recheck the fill price and rupee risk before entering.')
  }
  if (plan?.protection === 'missing') warnings.push('No accepted broker SL is visible. Check protection in the order panel.')
  return { headline, reason, warnings }
}

export interface GuideCash {
  atStop: number
  atTarget: number | null
  feesAtStop: number
  feesAtTarget: number | null
}
/** Conservative display estimate: maker entry, market/taker exit, no fee discount assumed. */
export function deltaGuideCash(plan: GuidePlan, quantity: number, contractValue: number,
  fees: { maker: number; taker: number; tax: number; entryPaid?: number | null }): GuideCash | null {
  if (!positive(plan.entry) || !positive(plan.stop) || !Number.isSafeInteger(quantity) || quantity <= 0 || !positive(contractValue) ||
    ![fees.maker, fees.taker, fees.tax].every(n => Number.isFinite(n) && n >= 0 && n <= 1) ||
    (fees.entryPaid !== undefined && fees.entryPaid !== null && (!Number.isFinite(fees.entryPaid) || fees.entryPaid < 0))) return null
  const units = quantity * contractValue, sign = plan.side === 'buy' ? 1 : -1
  const paid = fees.entryPaid ?? plan.entry * units * fees.maker * (1 + fees.tax)
  const cost = (exit: number) => paid + exit * units * fees.taker * (1 + fees.tax)
  const net = (exit: number) => ((exit - plan.entry) * sign * units - cost(exit)) * 85
  const result = { atStop: net(plan.stop), atTarget: positive(plan.target) ? net(plan.target) : null,
    feesAtStop: cost(plan.stop) * 85, feesAtTarget: positive(plan.target) ? cost(plan.target) * 85 : null }
  return Object.values(result).every(n => n === null || Number.isFinite(n)) ? result : null
}
