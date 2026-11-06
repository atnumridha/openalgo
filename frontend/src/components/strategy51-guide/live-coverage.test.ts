import { expect, it } from 'vitest'
import { STRATEGIES_51 } from './catalog'
import { buildFrames } from './indicators'
import { assessStrategy } from './rules'
import { DEFAULT_STRATEGY51_SETTINGS as settings } from './settings'
import type { EvaluationInput } from './types'

// Exercise all handlers on each supported source family, rather than merely counting catalog rows.
it.each([
  60, 180, 300, 900, 1800, 3600, 14400, 86400,
])('checks all51 rules with useful prerequisites on %is candles', (seconds) => {
  const start = Date.UTC(2026, 7, 1) / 1000
  const bars = Array.from({ length: 320 }, (_, i) => {
    const close = 100 + Math.sin(i / 8) * 5 + i * 0.01
    return {
      time: start + i * seconds,
      open: close - 0.1,
      high: close + 1,
      low: close - 1,
      close,
      volume: 100 + (i % 17),
    }
  })
  const frames = buildFrames(bars, seconds, 0, { session: { start: 0, end: 1440, offset: 0 } })
  const a: EvaluationInput = {
    frames,
    index: frames.length - 1,
    settings,
    extras: { session: { start: 0, end: 1440, offset: 0 } },
    context: {
      symbol: 'BTCUSD',
      exchange: 'DELTA',
      intervalSeconds: seconds,
      now: bars.at(-1)!.time + seconds,
      observedAt: bars.at(-1)!.time + seconds,
      sourceReady: true,
      connected: true,
      marketOpen: true,
      chartType: 'standard',
      tickSize: 0.5,
    },
  }
  for (const d of STRATEGIES_51) {
    const r = assessStrategy(d, a)
    expect(r.definition.id).toBe(d.id)
    expect(r.reason.length).toBeGreaterThan(5)
    expect(r.next.length).toBeGreaterThan(5)
    expect(['confirmed', 'waiting', 'timeframe', 'needs-data', 'needs-context']).toContain(r.state)
    if (r.candidate) {
      expect(r.state).toBe('confirmed')
      expect(r.candidate.index).toBe(a.index)
      expect(r.candidate.signalIndex).toBeLessThanOrEqual(a.index)
      expect(r.candidate.entry).toBeGreaterThan(0)
      expect(r.candidate.stop).toBeGreaterThan(0)
    }
  }
})
