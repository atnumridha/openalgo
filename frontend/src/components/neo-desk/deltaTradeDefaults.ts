import type { BalanceFraction } from './deltaSizing'
export interface DeltaTradeDefaults {
  leverage: number
  balanceFraction: BalanceFraction | null
  manualQuantity: string
}
export const DELTA_TRADE_DEFAULTS_KEY = 'neo.delta.trade.defaults'
const initial = (): DeltaTradeDefaults => ({
  leverage: 50,
  balanceFraction: 1,
  manualQuantity: '1',
})
function valid(v: DeltaTradeDefaults) {
  return (
    !!v &&
    Number.isInteger(v.leverage) &&
    v.leverage >= 1 &&
    v.leverage <= 200 &&
    (v.balanceFraction === null || [0.1, 0.25, 0.5, 0.75, 1].includes(v.balanceFraction)) &&
    typeof v.manualQuantity === 'string' &&
    Number.isSafeInteger(Number(v.manualQuantity)) &&
    Number(v.manualQuantity) > 0
  )
}
export function readDeltaTradeDefaults(): DeltaTradeDefaults {
  try {
    const saved = JSON.parse(localStorage.getItem(DELTA_TRADE_DEFAULTS_KEY) || 'null')
    return valid(saved) ? saved : initial()
  } catch {
    return initial()
  }
}
export function saveDeltaTradeDefaults(value: DeltaTradeDefaults): boolean {
  if (!valid(value)) return false
  try {
    const text = JSON.stringify(value)
    localStorage.setItem(DELTA_TRADE_DEFAULTS_KEY, text)
    return localStorage.getItem(DELTA_TRADE_DEFAULTS_KEY) === text
  } catch {
    return false
  }
}
