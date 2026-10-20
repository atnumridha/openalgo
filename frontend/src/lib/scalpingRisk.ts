import type { SLState } from '@/hooks/useTrailingSL'
import type { ScalpingAction, ScalpingProduct, SelectedLeg } from '@/types/scalping'

export interface ProtectionConfig {
  slOn: boolean
  slValue: string
  slUnit: 'PTS' | 'PCT'
  tgtOn: boolean
  tgtValue: string
  tgtUnit: 'PTS' | 'PCT' | 'RR'
  slAsOf?: number
}

function tickPrice(price: number, tick: number, up: boolean): number {
  if (!(Number.isFinite(tick) && tick > 0)) return Number(price.toFixed(10))
  const ticks = up ? Math.ceil(price / tick - 1e-8) : Math.floor(price / tick + 1e-8)
  return Number((ticks * tick).toFixed(10))
}

/** A suggestion needs a real instrument tick; never guess contract metadata. */
export function atrStopDistance(atr: number | undefined, tick: number): number | null {
  if (!(atr != null && Number.isFinite(atr) && atr > 0 && Number.isFinite(tick) && tick > 0)) return null
  return tickPrice(Math.max(atr, tick * 2), tick, true)
}

/** Initial price R excludes fees. Never recalculate from a trailed stop. */
export function initialTarget(side: ScalpingAction, entry: number, stop: number, tick = 0): number {
  const risk = side === 'BUY' ? entry - stop : stop - entry
  if (![entry, stop, risk].every(Number.isFinite) || entry <= 0 || stop <= 0 || risk <= 0) {
    throw new Error('A valid initial stop-loss on the loss side of entry is required for 1:3.')
  }
  const target = tickPrice(entry + (side === 'BUY' ? 3 : -3) * risk, tick, side === 'BUY')
  if (target <= 0 || !Number.isFinite(target))
    throw new Error('The initial 1:3 target price must be positive.')
  return target
}

/** Send explicit distances to the existing REST policy. It anchors these at
 * the submitted maker price, independent of legacy server-side RR defaults.
 */
export function executionProtection(config: ProtectionConfig, plan: SLState | null): ProtectionConfig {
  if (!plan || !config.tgtOn || config.tgtUnit !== 'RR') return config
  const risk = Number(Math.abs(plan.entry - plan.initialSl).toFixed(10))
  return { ...config, slUnit: 'PTS', slValue: String(risk), tgtUnit: 'PTS', tgtValue: String(Number((risk * 3).toFixed(10))) }
}

/** Validate before placing an order; retain this exact snapshot during submission. */
export function predefinedProtection(
  leg: SelectedLeg,
  side: ScalpingAction,
  quantity: number,
  product: ScalpingProduct,
  entry: number | undefined,
  config: ProtectionConfig
): SLState | null {
  if (!config.slOn && !config.tgtOn) return null
  if (config.slOn && config.slAsOf != null && (!Number.isFinite(config.slAsOf) || Date.now() / 1000 - config.slAsOf > 90 || config.slAsOf > Date.now() / 1000 + 5))
    throw new Error('Waiting for a fresh completed candle for the automatic SL suggestion.')
  if (entry == null || !Number.isFinite(entry) || entry <= 0)
    throw new Error('A current price is required to apply SL and target.')
  const distance = (raw: string, unit: 'PTS' | 'PCT' | 'RR', label: string) => {
    const value = Number(raw)
    if (!Number.isFinite(value) || value <= 0)
      throw new Error(`Enter a positive ${label} distance.`)
    return unit === 'PCT' ? (entry * value) / 100 : value
  }
  let stop = 0
  if (config.slOn) {
    const pts = distance(config.slValue, config.slUnit, 'stop-loss')
    stop = tickPrice(entry + (side === 'BUY' ? -pts : pts), leg.tickSize, side === 'BUY')
    if (stop <= 0 || (side === 'BUY' ? stop >= entry : stop <= entry))
      throw new Error('Stop-loss distance must produce a valid price beyond one tick.')
  }
  let target = 0
  if (config.tgtOn) {
    if (config.tgtUnit === 'RR') target = initialTarget(side, entry, stop, leg.tickSize)
    else {
      const pts = distance(config.tgtValue, config.tgtUnit, 'target')
      target = tickPrice(entry + (side === 'BUY' ? pts : -pts), leg.tickSize, side === 'BUY')
      if (target <= 0) throw new Error('Target price must be positive.')
    }
  }
  return {
    symbol: leg.symbol,
    exchange: leg.exchange,
    product,
    side,
    quantity,
    entry,
    initialSl: stop,
    currentSl: stop,
    target,
    trailingEnabled: false,
    trailingStep: 0,
    highestPrice: entry,
    lowestPrice: entry,
    active: true,
  }
}
