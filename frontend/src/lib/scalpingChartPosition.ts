import type { SLState } from '@/hooks/useTrailingSL'
import type { Position } from '@/types/trading'

export interface ChartPosition {
  status: 'unavailable' | 'flat' | 'open'
  currency: 'USD' | 'INR'
  entry?: number
  quantity?: number
  gross: number | null
  sl: number | null
  target: number | null
  slGross: number | null
  targetGross: number | null
  protectionAvailable: boolean
}

export function chartPosition(
  positions: Position[], stop: SLState | undefined,
  symbol: string, exchange: string, product: string, ltp: number | undefined,
  positionAvailable: boolean, protectionAvailable: boolean, emptyIsConfirmed = true
): ChartPosition {
  const base: ChartPosition = { status: 'unavailable', currency: exchange === 'CRYPTO' ? 'USD' : 'INR', gross: null, sl: null, target: null, slGross: null, targetGross: null, protectionAvailable }
  if (!positionAvailable) return base
  const matching = positions.filter((p) => p.symbol === symbol && p.exchange === exchange && p.product === product && Number(p.quantity) !== 0)
  if (!matching.length) return { ...base, status: emptyIsConfirmed ? 'flat' : 'unavailable' }
  if (matching.length !== 1) return base
  const position = matching[0]
  const entry = Number(position.average_price), quantity = Number(position.quantity)
  if (!(Number.isFinite(entry) && entry > 0 && Number.isFinite(quantity) && quantity !== 0)) return base
  const multiplier = exchange === 'CRYPTO' ? Number(position.lot_size) : 1
  const grossAt = (price: number | null | undefined) => {
    if (!(price != null && Number.isFinite(price) && price > 0 && Number.isFinite(multiplier) && multiplier > 0)) return null
    return Number(((price - entry) * quantity * multiplier).toFixed(10))
  }
  const confirmed = protectionAvailable && stop?.active && stop.symbol === symbol && stop.exchange === exchange && stop.product === product && stop.side === (quantity > 0 ? 'BUY' : 'SELL')
  const sl = confirmed && Number.isFinite(stop.currentSl) && stop.currentSl > 0 ? stop.currentSl : null
  const target = confirmed && Number.isFinite(stop.target) && stop.target > 0 ? stop.target : null
  return { ...base, status: 'open', entry, quantity, gross: grossAt(ltp), sl, target, slGross: grossAt(sl), targetGross: grossAt(target) }
}

export function grossLabel(value: number | null, currency: 'USD' | 'INR'): string {
  if (value == null) return 'unavailable'
  const number = (n: number) => `${n >= 0 ? '+' : '−'}${Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false })}`
  return currency === 'USD' ? `$${number(value)} / ₹${number(value * 85)}` : `₹${number(value)}`
}
