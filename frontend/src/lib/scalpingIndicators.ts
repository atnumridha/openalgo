import type { Candle } from './scalpingSignal'

export interface ChartIndicatorValues {
  time: number
  ema9?: number
  ema20?: number
  ema50?: number
  rsi14?: number
  atr14?: number
}

/** Same seeds and Wilder smoothing as the recommendation, on the chart timeframe.
 * Includes the forming candle for display only; it does not drive trade signals.
 */
export function chartIndicators(candles: Candle[]): ChartIndicatorValues[] {
  const periods = [9, 20, 50] as const
  const averages = new Map<number, number>()
  let sum = 0
  let gain = 0
  let loss = 0
  let atr = 0
  return candles.map((bar, i) => {
    const values: ChartIndicatorValues = { time: bar.time }
    sum += bar.close
    for (const period of periods) {
      if (i < period - 1) continue
      const previous = averages.get(period)
      const value = previous == null ? sum / period : previous + (bar.close - previous) * 2 / (period + 1)
      averages.set(period, value)
      if (Number.isFinite(value)) values[`ema${period}`] = value
    }
    if (i > 0) {
      const delta = bar.close - candles[i - 1].close
      const tr = Math.max(bar.high - bar.low, Math.abs(bar.high - candles[i - 1].close), Math.abs(bar.low - candles[i - 1].close))
      if (i <= 14) {
        gain += Math.max(0, delta) / 14
        loss += Math.max(0, -delta) / 14
        atr += tr / 14
      } else {
        gain = (gain * 13 + Math.max(0, delta)) / 14
        loss = (loss * 13 + Math.max(0, -delta)) / 14
        atr = (atr * 13 + tr) / 14
      }
      if (i >= 14) {
        const rsi = gain === 0 && loss === 0 ? 50 : loss === 0 ? 100 : 100 - 100 / (1 + gain / loss)
        if (Number.isFinite(rsi)) values.rsi14 = rsi
        if (Number.isFinite(atr)) values.atr14 = atr
      }
    }
    return values
  })
}
