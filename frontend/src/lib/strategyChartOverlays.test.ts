import { describe, expect, it } from 'vitest'
import {
  bollingerSeries,
  emaSeries,
  isPlausibleLivePrice,
  lastBarBiasMarker,
  plausibleHistoryTail,
  type OverlayBar,
  smaSeries,
} from './strategyChartOverlays'

function bars(closes: number[]): OverlayBar[] {
  return closes.map((close, i) => ({
    time: i * 300,
    open: close,
    high: close,
    low: close,
    close,
  }))
}

describe('strategyChartOverlays', () => {
  it('keeps EMA 9/15 null until min_periods, then matches pandas ewm(adjust=False)', () => {
    const closes = Array.from({ length: 80 }, (_, i) => 100 + i)
    const ema9 = emaSeries(bars(closes), 9, 75)
    expect(ema9).toHaveLength(6)
    expect(ema9[0].time).toBe(74 * 300)
    const alpha = 2 / 10
    let prev = closes[0]
    for (let i = 1; i < 75; i++) prev = alpha * closes[i] + (1 - alpha) * prev
    expect(ema9[0].value).toBeCloseTo(prev, 10)
  })

  it('computes Bollinger 20/2 with sample standard deviation', () => {
    const closes = Array.from({ length: 20 }, (_, i) => i + 1)
    const { middle, upper, lower } = bollingerSeries(bars(closes), 20, 2)
    expect(middle).toHaveLength(1)
    expect(middle[0].value).toBeCloseTo(10.5, 10)
    const mean = 10.5
    const variance = closes.reduce((sum, value) => sum + (value - mean) ** 2, 0) / 19
    const std = Math.sqrt(variance)
    expect(upper[0].value).toBeCloseTo(mean + 2 * std, 10)
    expect(lower[0].value).toBeCloseTo(mean - 2 * std, 10)
  })

  it('marks BUY when EMA 9 is above EMA 15 on a bullish completed bar', () => {
    const sample = Array.from({ length: 80 }, (_, i) => ({
      time: i * 300,
      open: 100 + i,
      high: 101 + i,
      low: 99 + i,
      close: 100.6 + i,
    }))
    const marker = lastBarBiasMarker(sample, ['ema9', 'ema15'])
    expect(marker?.label).toBe('BUY')
  })

  it('marks SELL on a bearish completed bar for profiles without overlays', () => {
    const sample = [
      { time: 0, open: 102, high: 103, low: 99, close: 100 },
      { time: 300, open: 101, high: 102, low: 98, close: 99 },
    ]
    expect(lastBarBiasMarker(sample, [])?.label).toBe('SELL')
  })

  it('rejects a live tick that cannot be a current NIFTY/SENSEX/MCX price', () => {
    expect(isPlausibleLivePrice(8, 22780)).toBe(false)
    expect(isPlausibleLivePrice(22790, 22780)).toBe(true)
    expect(isPlausibleLivePrice(0, 22780)).toBe(false)
    expect(isPlausibleLivePrice(22790, null)).toBe(true)
  })

  it('drops cross-symbol history before computing SENSEX indicators', () => {
    const corrupt = [
      ...bars(Array.from({ length: 80 }, (_, i) => 9700 + i)),
      ...bars(Array.from({ length: 80 }, (_, i) => 72000 + i)).map((bar, i) => ({
        ...bar,
        time: (80 + i) * 300,
      })),
    ]
    const filtered = plausibleHistoryTail(corrupt)
    expect(filtered).toHaveLength(80)
    expect(filtered[0].close).toBe(72000)
    expect(filtered.at(-1)?.close).toBe(72079)
    expect(emaSeries(filtered, 9, 75).at(-1)?.value).toBeGreaterThan(70000)

    const anchored = plausibleHistoryTail(corrupt, 0.25, 72155)
    expect(anchored).toHaveLength(80)
    expect(anchored[0].close).toBe(72000)
    expect(anchored.at(-1)?.close).toBe(72079)
  })

  it('computes SMA 5 on completed closes only', () => {
    const points = smaSeries(bars([1, 2, 3, 4, 5, 6]), 5)
    expect(points.map((p) => p.value)).toEqual([3, 4])
  })
})
