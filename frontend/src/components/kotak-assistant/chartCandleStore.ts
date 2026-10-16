import { useSyncExternalStore } from 'react'
import type { IndicatorCandle } from './tradeIndicatorsModel'

const EMPTY: IndicatorCandle[] = []
const candles = new Map<string, IndicatorCandle[]>()
const listeners = new Set<() => void>()
export const candleKey = (
  user: string | undefined,
  mode: string,
  symbol: string,
  exchange: string,
  interval: string
) => JSON.stringify([user, mode, symbol, exchange, interval])
export function publishChartCandles(key: string, bars: IndicatorCandle[]) {
  candles.delete(key)
  candles.set(key, [...bars])
  if (candles.size > 40) candles.delete(candles.keys().next().value!)
  for (const notify of listeners) notify()
}
const subscribe = (notify: () => void) => {
  listeners.add(notify)
  return () => {
    listeners.delete(notify)
  }
}
export function useChartCandles(key: string) {
  return useSyncExternalStore(
    subscribe,
    () => candles.get(key) || EMPTY,
    () => EMPTY
  )
}
