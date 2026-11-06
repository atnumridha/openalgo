import { expect, it } from 'vitest'
import { patternDisplayRange, patternDisplayEvents } from './patternDisplay'
import type { TimedArchiveMatch } from './archiveConfirmations'

const bars = Array.from({ length: 15 }, (_, i) => ({ time: 100 + i * 60 }))
it('shows exactly the last ten chart candles, including the forming candle slot', () => {
  expect(patternDisplayRange(bars)).toEqual({ first: 400, last: 940 })
  expect(bars.filter(b => b.time >= patternDisplayRange(bars).first)).toHaveLength(10)
})
it('expires the oldest label as a new candle arrives without requiring a new pattern', () => {
  expect(patternDisplayRange([...bars, { time: 1000 }]).first).toBe(460)
})
it('counts actual candles across session gaps and allows all loaded history', () => {
  const gapped = bars.map((b, i) => ({ time: b.time + (i >= 5 ? 86400 : 0) }))
  expect(patternDisplayRange(gapped).first).toBe(gapped[5].time)
  expect(patternDisplayRange(gapped, true).first).toBe(gapped[0].time)
  expect(patternDisplayRange(bars.slice(0, 3))).toEqual({ first: 100, last: 220 })
  expect(patternDisplayRange([])).toEqual({ first: 0, last: 0 })
})
it('hides raw unconfirmed directions by default and explicitly labels an optional preview', () => {
  const confirmed: TimedArchiveMatch = { time: 100, name: 'Hammer confirmed', side: 'CALL', pattern: 'confirmed-hammer', extreme: 90, confirmed: true }
  const raw = { ...confirmed, time: 160, name: 'Hammer', confirmed: false }
  const neutral = { ...raw, time: 220, name: 'Doji', side: 'NEUTRAL' as const }
  const events = [confirmed, raw, neutral]
  expect(patternDisplayEvents(events)).toEqual([confirmed, neutral])
  expect(patternDisplayEvents(events, true)[1].name).toBe('Hammer · unconfirmed')
  expect(events[1].name).toBe('Hammer')
})
