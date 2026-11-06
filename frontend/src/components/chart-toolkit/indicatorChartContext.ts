import { expiryDate, underlyingPriceExchange } from '@/lib/neoOptionSelection'
import type { IndicatorKey, TradeSide } from './nineIndicators'
import type { OptionReference } from './ToolkitPanel'

export type IndicatorSource = 'underlying' | 'premium'
export interface IndicatorChartContext {
  kind: 'index' | 'option' | 'price'
  symbol: string
  exchange: string
  optionSide?: 'CE' | 'PE'
  underlying?: { symbol: string; exchange: string }
  expiry?: string
  reference?: OptionReference
}

export function resolveIndicatorChart(
  symbol: string,
  exchange: string,
  reference?: OptionReference
): IndicatorChartContext {
  const base = { symbol, exchange }
  if (['NSE_INDEX', 'BSE_INDEX'].includes(exchange))
    return {
      ...base,
      kind: 'index',
      underlying: base,
      reference:
        reference?.underlying === symbol && reference.exchange === exchange ? reference : undefined,
    }
  const optionSide = /(?:CE|PE)$/.exec(symbol)?.[0] as 'CE' | 'PE' | undefined
  if (!['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCO'].includes(exchange) || !optionSide)
    return { ...base, kind: 'price' }
  // OpenAlgo canonical option symbols carry an explicit DDMMMYY expiry.
  const match = /^([A-Z][A-Z0-9&-]*?)(\d{2}[A-Z]{3}\d{2})(\d+(?:\.\d+)?)(CE|PE)$/.exec(symbol)
  const parsed = match && expiryDate(match[2]) ? match : undefined
  const candidate =
    reference?.optionExchange === exchange &&
    (reference.ce?.symbol === symbol || reference.pe?.symbol === symbol)
      ? reference
      : undefined
  const ref =
    candidate && (!parsed || (candidate.underlying === parsed[1] && candidate.expiry === parsed[2]))
      ? candidate
      : undefined
  const root = parsed?.[1] ?? ref?.underlying
  const venue =
    root && ['NFO', 'BFO'].includes(exchange)
      ? underlyingPriceExchange(root, exchange) || (exchange === 'NFO' ? 'NSE' : 'BSE')
      : undefined
  return {
    ...base,
    kind: 'option',
    optionSide,
    underlying: root && venue ? { symbol: root, exchange: venue } : undefined,
    expiry: parsed?.[2] ?? ref?.expiry,
    reference: ref,
  }
}

/** CALL/PUT inside the engine means directional bias; actions depend on its source. */
export function indicatorAction(
  side: TradeSide,
  chart: IndicatorChartContext,
  source: IndicatorSource,
  key?: IndicatorKey
): { label: string; side: TradeSide } {
  if (side === 'WAIT') return { label: 'WAIT', side }
  if (chart.kind === 'option') {
    const context = key != null && ['iv', 'pcr', 'oi'].includes(key)
    const buy =
      source === 'premium' && !context
        ? side === 'CALL'
        : side === (chart.optionSide === 'CE' ? 'CALL' : 'PUT')
    return { label: `${buy ? 'BUY' : 'AVOID'} ${chart.optionSide}`, side: buy ? 'CALL' : 'PUT' }
  }
  if (chart.exchange === 'DELTA') return { label: side === 'CALL' ? 'LONG' : 'SHORT', side }
  return { label: chart.kind === 'index' ? `BUY ${side}` : side === 'CALL' ? 'BULL' : 'BEAR', side }
}
