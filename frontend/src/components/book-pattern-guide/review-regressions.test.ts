import { describe, expect, it } from 'vitest'
import { analyzeBookGuide, BookPatternEngine } from './engine'
import { bar, CANDLE_FIXTURES, TEST_CONTEXT, timed, trendBars } from './fixtures'
import { confirmedPivots } from './math'
import type { BookBar, BookSettings } from './types'

const SHAPES = [
  'symmetrical-triangle',
  'ascending-triangle',
  'descending-triangle',
  'bull-rectangle',
  'bear-rectangle',
  'bull-flag',
  'bear-flag',
  'falling-wedge',
  'rising-wedge',
  'double-bottom',
  'double-top',
  'triple-bottom',
  'triple-top',
  'inverse-head-shoulders',
  'head-shoulders',
  'cup-handle',
]
function only(pattern: string): Partial<BookSettings> {
  return {
    disabledPatterns: [
      ...CANDLE_FIXTURES.map((f) => f.id),
      ...SHAPES.filter((id) => id !== pattern),
      'sr-long',
      'sr-short',
      'trendline-long',
      'trendline-short',
    ],
  }
}
function cupBars(lastIndex: number): BookBar[] {
  const rows = trendBars('long')
  for (let i = 70; i <= lastIndex; i++) {
    const p =
      i <= 140
        ? 110 - 10 * Math.sin((Math.PI * (i - 70)) / 70)
        : i <= 160
          ? 110 - 2 * Math.sin((Math.PI * (i - 140)) / 20)
          : 109.8
    rows.push(bar(p - 0.1, p + 0.3, p - 0.3, p))
  }
  return timed(rows)
}
function flagBars(side: 'long' | 'short', breakout: number): BookBar[] {
  const rows = trendBars('long')
  for (let i = 70; i <= breakout; i++) {
    const center = 118.5 - (i - 70) * 0.25
    rows.push(bar(center - 0.1, center + 0.3, center - 0.3, center))
  }
  rows[70] = bar(119.6, 120, 119.2, 119.7)
  rows[74] = bar(116.4, 116.8, 116, 116.3)
  rows[78] = bar(117.6, 118, 117.3, 117.7)
  rows[82] = bar(114.4, 114.8, 114, 114.3)
  for (let i = 83; i < breakout; i++) rows[i] = bar(114.4, 114.8, 114.2, 114.5)
  const B = 120 - (breakout - 70) * 0.25
  rows[breakout] = bar(B + 0.2, B + 1, B + 0.1, B + 0.8)
  const directional =
    side === 'long'
      ? rows
      : rows.map((b) => ({
          ...b,
          open: 240 - b.open,
          high: 240 - b.low,
          low: 240 - b.high,
          close: 240 - b.close,
        }))
  return timed(directional)
}

// These exercise actual strict pivots, detection, pending transitions and qualification together.
describe('review round 1: received-prefix shape revalidation', () => {
  it('expires a cup after twenty handle bars rather than activating a cached thirty-one-bar handle', () => {
    const rows = cupBars(171)
    rows[171] = { ...bar(110.5, 112, 110.4, 111.5), time: rows[171]!.time }
    const before = analyzeBookGuide(rows.slice(0, 155), TEST_CONTEXT, only('cup-handle'))
    expect(before.pendingEvents.some((e) => e.patternId === 'cup-handle')).toBe(true)
    expect(confirmedPivots(rows.slice(0, 155), 3, 3).map((p) => p.index)).toEqual([
      70, 105, 140, 150,
    ])
    const r = analyzeBookGuide(rows, TEST_CONTEXT, only('cup-handle'))
    expect(r.events.some((e) => e.patternId === 'cup-handle' && e.confirmationIndex === 171)).toBe(
      false
    )
    expect(r.activePlan).toBeUndefined()
  })
  it('updates handle resistance before a new high pivot is recognized and preserves it after recognition', () => {
    const rows = cupBars(159)
    rows[155] = { ...bar(109.2, 111, 109, 109.7), time: rows[155]!.time }
    rows[156] = { ...bar(109.8, 110.8, 109.7, 110.5), time: rows[156]!.time }
    rows[157] = { ...bar(109.7, 110, 109.5, 109.8), time: rows[157]!.time }
    rows[158] = { ...bar(109.7, 110, 109.5, 109.8), time: rows[158]!.time }
    rows[159] = { ...bar(110.2, 110.8, 110.1, 110.5), time: rows[159]!.time }
    for (const end of [157, 160]) {
      const r = analyzeBookGuide(rows.slice(0, end), TEST_CONTEXT, only('cup-handle'))
      expect(r.events.some((e) => e.patternId === 'cup-handle')).toBe(false)
      expect(r.activePlan).toBeUndefined()
      expect(r.pendingEvents.find((e) => e.patternId === 'cup-handle')?.trigger).toBe(111)
    }
    const valid = timed([...rows, bar(111.2, 112, 111.1, 111.5)])
    const r = analyzeBookGuide(valid, TEST_CONTEXT, only('cup-handle'))
    expect(r.events.find((e) => e.patternId === 'cup-handle')?.confirmationIndex).toBe(160)
    expect(r.activePlan?.entry).toBe(111.5)
  })
  it.each([
    'long',
    'short',
  ] as const)('expires a %s flag whose breakout occurs after its twenty-bar corrective window', (side) => {
    const pattern = side === 'long' ? 'bull-flag' : 'bear-flag',
      rows = flagBars(side, 91)
    if (side === 'short')
      rows.push({ ...bar(124.3, 124.5, 123.5, 124), time: rows.at(-1)!.time + 60 })
    const before = analyzeBookGuide(rows.slice(0, 87), TEST_CONTEXT, only(pattern))
    expect(before.pendingEvents.some((e) => e.patternId === pattern)).toBe(true)
    const r = analyzeBookGuide(rows, TEST_CONTEXT, only(pattern))
    expect(r.events.some((e) => e.patternId === pattern)).toBe(false)
    expect(r.activePlan).toBeUndefined()
  })
  it('confirms a bull flag inside the window and lets a valid final-bar bear breakout confirm on its required next candle', () => {
    const bull = analyzeBookGuide(flagBars('long', 90), TEST_CONTEXT, only('bull-flag'))
    expect(bull.events.find((e) => e.patternId === 'bull-flag')?.confirmationIndex).toBe(90)
    const bearRows = flagBars('short', 90)
    bearRows.push({ ...bar(124.8, 125, 124, 124.3), time: bearRows.at(-1)!.time + 60 })
    const bear = analyzeBookGuide(bearRows, TEST_CONTEXT, only('bear-flag'))
    expect(bear.events.find((e) => e.patternId === 'bear-flag')?.armedIndex).toBe(90)
    expect(bear.events.find((e) => e.patternId === 'bear-flag')?.confirmationIndex).toBe(91)
  })
})

describe('review round 1: missing history arrives after reconnection', () => {
  const rows = () =>
    timed([...trendBars('short'), bar(100, 110, 99.9, 102), bar(102.5, 105, 102.3, 104)])
  const at = (time: number) => ({
    ...TEST_CONTEXT,
    now: time,
    observedAt: time,
    quoteObservedAt: time,
  })
  it.each([
    false,
    true,
  ])('consumes historical arrivals when reconnect first contains %s unchanged history', (unchangedReconnect) => {
    const input = rows(),
      initialTime = input[69]!.time + 60,
      reconnectTime = input[71]!.time + 60 + 3600,
      engine = new BookPatternEngine()
    engine.reconcile(input.slice(0, 70), at(initialTime))
    engine.reconcile(input.slice(0, 70), { ...at(initialTime + 5), connected: false })
    if (unchangedReconnect) engine.reconcile(input.slice(0, 70), at(reconnectTime))
    const caughtUp = engine.reconcile(input, at(reconnectTime + 1))
    expect(caughtUp.events.some((e) => e.patternId === 'inverted-hammer')).toBe(true)
    expect(caughtUp.alerts).toEqual([])
    const fresh = { ...bar(104, 120, 103, 118), time: reconnectTime + 60 }
    const live = engine.reconcile([...input, fresh], at(fresh.time + 60))
    expect(live.alerts.some((a) => a.type === 'target-reference-touch')).toBe(true)
    expect(engine.reconcile([...input, fresh], at(fresh.time + 61)).alerts).toEqual([])
  })
  it('also consumes late historical arrivals during continuous readiness instead of presenting them as fresh', () => {
    const input = rows(),
      engine = new BookPatternEngine()
    engine.reconcile(input.slice(0, 70), at(input[69]!.time + 60))
    expect(engine.reconcile(input, at(input[71]!.time + 3600)).alerts).toEqual([])
  })
  it('still delivers a newly observed completed trigger while continuously ready', () => {
    const input = rows(),
      engine = new BookPatternEngine()
    engine.reconcile(input.slice(0, 71), at(input[70]!.time + 60))
    const fresh = engine.reconcile(input, at(input[71]!.time + 60))
    expect(fresh.alerts.map((a) => a.type)).toContain('confirmed-pattern')
    expect(fresh.alerts.map((a) => a.type)).toContain('qualified-plan')
  })
  it('recovers delivery after an unavailable nonfinite observation without poisoning the reconnect boundary', () => {
    const input = rows(),
      engine = new BookPatternEngine(),
      initial = input[69]!.time + 60
    engine.reconcile(input.slice(0, 70), at(initial))
    engine.reconcile(input.slice(0, 70), { ...at(initial + 1), now: NaN })
    engine.reconcile(input.slice(0, 70), at(initial + 2))
    const fresh = engine.reconcile(input, at(input[71]!.time + 60))
    expect(fresh.alerts.map((a) => a.type)).toContain('qualified-plan')
  })
})
