import { expect, it } from 'vitest'
import { Strategy51Engine } from './engine'
import { DEFAULT_STRATEGY51_SETTINGS } from './settings'
import type { StrategyBar, StrategyContext } from './types'

it('bounds a long history and reuses completed analysis while the current candle changes', () => {
  const start = Date.UTC(2026, 9, 1) / 1000,
    bars: StrategyBar[] = Array.from({ length: 5000 }, (_, i) => {
      const close = 100 + Math.sin(i / 8) * 3 + i * 0.002
      return {
        time: start + i * 300,
        open: close - 0.1,
        high: close + 1,
        low: close - 1,
        close,
        volume: 100 + (i % 13),
      }
    })
  const end = bars.at(-1)!.time + 300,
    context: StrategyContext = {
      symbol: 'TEST',
      exchange: 'NSE',
      intervalSeconds: 300,
      now: end,
      observedAt: end,
      sourceReady: true,
      connected: true,
      marketOpen: false,
      chartType: 'standard',
      tickSize: 0.05,
    },
    engine = new Strategy51Engine(),
    before = performance.now()
  const initial = engine.reconcile(bars, context, DEFAULT_STRATEGY51_SETTINGS)
  const duration = performance.now() - before
  expect(initial.processed).toBe(1500)
  expect(initial.rows).toHaveLength(51)
  expect(initial.frames![0].vwap).toBeUndefined()
  const forming = { time: end, open: 111, high: 113, low: 110, close: 112, volume: 100 }
  const updated = engine.reconcile(
    [...bars, forming],
    { ...context, now: end + 5, observedAt: end + 5 },
    DEFAULT_STRATEGY51_SETTINGS
  )
  expect(updated.frames).toBe(initial.frames)
  expect(updated.forming?.price).toBe(112)
  console.info(`51-strategy bounded 1500-candle scan: ${duration.toFixed(1)} ms`)
})
