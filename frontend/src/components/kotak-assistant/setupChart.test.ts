import { describe, it, expect } from 'vitest'
import { setupChartAnnotations } from './setupChart'
import type { SetupResult } from '@/api/kotakAssistant'

describe('Setup chart annotations', () => {
  it('numbers causal first and second swings and labels an untriggered watch accurately', () => {
    const setup: SetupResult = {
      strategy: 'opening_reversal',
      version: '1.0',
      mode: 'literal',
      stage: 'waiting_trigger',
      direction: 'PE',
      reason: 'watch',
      evidence: [],
      reference: { price: 22590 },
      trigger: 22608,
      expires: 1600,
      signal_candle: { time: 1200, open: 22615, high: 22620, low: 22608, close: 22610 },
      numbered_swings: [
        { kind: 'high', ordinal: 1, price: 22580, time: 800, known_at: 980 },
        { kind: 'high', ordinal: 2, price: 22590, time: 1000, known_at: 1180 },
      ],
    }
    const result = setupChartAnnotations(setup, 1300)
    expect(result.markers.map((m) => m.label)).toEqual(
      expect.arrayContaining(['H1 · 22580.00', 'H2 · 22590.00', 'PE red signal'])
    )
    expect(result.levels.some((l) => l.title.includes('Watching PE below'))).toBe(true)
    expect(result.markers.some((m) => m.label?.includes('TRIGGERED'))).toBe(false)
  })
  it('does not expose levels or markers known only after the replay cursor', () => {
    const setup: SetupResult = {
      strategy: 'trend',
      version: '1.0',
      mode: 'confirmed',
      stage: 'ready',
      reason: 'ready',
      evidence: [],
      numbered_swings: [{ kind: 'low', ordinal: 2, price: 100, time: 800, known_at: 1200 }],
    }
    expect(setupChartAnnotations(setup, 1000).markers).toEqual([])
  })
})
