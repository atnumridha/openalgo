import type { IndicatorState } from '../chart-toolkit/nineIndicators'
import { deltaSeconds } from '../chart-toolkit/deltaFeed'
import type { PlanBar } from './chartTradePlan'
export interface DeltaOiHistory {
  symbol: string
  interval: string
  observedAt: number
  bars: PlanBar[]
}
export async function readDeltaOpenInterest(
  symbol: string,
  interval: string,
  signal: AbortSignal
): Promise<DeltaOiHistory> {
  const seconds = deltaSeconds[interval]
  if (!['BTCUSD', 'ETHUSD'].includes(symbol) || !seconds)
    throw Error('Unsupported crypto OI source')
  const observedAt = Date.now() / 1000,
    end = Math.floor(observedAt),
    params = new URLSearchParams({
      symbol: `OI:${symbol}`,
      resolution: interval,
      start: String(end - seconds * 200),
      end: String(end),
    })
  const response = await fetch(`https://api.india.delta.exchange/v2/history/candles?${params}`, {
    credentials: 'omit',
    signal: AbortSignal.any([signal, AbortSignal.timeout(10000)]),
  })
  if (!response.ok) throw Error('Delta OI history unavailable')
  const payload = await response.json()
  if (!payload.success || !Array.isArray(payload.result))
    throw Error('Delta OI history unavailable')
  const bars: PlanBar[] = payload.result
    .map((b: Record<string, unknown>) => ({
      time: Number(b.time),
      open: Number(b.open),
      high: Number(b.high),
      low: Number(b.low),
      close: Number(b.close),
    }))
    .filter(
      (b: PlanBar) =>
        [b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) &&
        b.time > 0 &&
        Math.min(b.open, b.high, b.low, b.close) >= 0 &&
        b.high >= Math.max(b.open, b.close) &&
        b.low <= Math.min(b.open, b.close)
    )
  return {
    symbol,
    interval,
    observedAt,
    bars: [...new Map(bars.map((b) => [b.time, b])).values()].sort((a, b) => a.time - b.time),
  }
}
/** OI expansion confirms price direction; contraction is unwinding, not a new entry. */
export function deltaOiSignal(
  source: DeltaOiHistory | undefined,
  prices: readonly PlanBar[],
  seconds: number,
  asOf: number,
  now: number
): IndicatorState {
  const wait = (reason: string, value: number | null = null): IndicatorState => ({
    key: 'oi',
    side: 'WAIT',
    time: null,
    value,
    reason,
  })
  if (!source || now < source.observedAt || now - source.observedAt > 90)
    return wait('Waiting for fresh Delta open-interest history')
  const cutoff = Math.min(asOf, source.observedAt),
    byTime = new Map(prices.filter((b) => b.time + seconds <= cutoff).map((b) => [b.time, b]))
  const common = source.bars
    .filter((b) => b.time + seconds <= cutoff && byTime.has(b.time))
    .slice(-2)
  const previous = common[0],
    current = common[1]
  if (
    !previous ||
    !current ||
    current.time - previous.time !== seconds ||
    now - current.time - seconds > seconds + 90
  )
    return wait('Waiting for two matched, completed price and OI candles')
  const oi = current.close,
    change = oi - previous.close,
    priceChange = byTime.get(current.time)!.close - byTime.get(previous.time)!.close
  if (!(oi > 0 && previous.close > 0) || change <= 0 || priceChange === 0)
    return wait('OI contraction / unchanged: no new directional build-up', oi)
  return {
    key: 'oi',
    value: oi,
    time: current.time,
    side: priceChange > 0 ? 'CALL' : 'PUT',
    reason: `Delta confirmed ${priceChange > 0 ? 'LONG' : 'SHORT'} build-up · OI +${((100 * change) / previous.close).toFixed(2)}% with ${priceChange > 0 ? 'rising' : 'falling'} price`,
  }
}
