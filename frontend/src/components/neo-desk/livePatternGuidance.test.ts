import { expect, it } from 'vitest'
import { liveCandleProgress, makePatternGuidance } from './livePatternGuidance'
import type { TimedArchiveMatch } from '../chart-toolkit/archiveConfirmations'
import type { Bar } from '../chart-toolkit/model'
const time = 1793844000
const bar = (i: number, close = 112, high = close + 1, low = close - 1): Bar => ({
  time: time + i * 60,
  open: Math.min(high, Math.max(low, 111)),
  high,
  low,
  close,
  volume: 1,
})
const bars = [bar(0), bar(1), bar(2)]
const event: TimedArchiveMatch = {
  time: time + 120,
  name: 'Double Bottom',
  pattern: 'double-bottom',
  side: 'CALL',
  confirmed: true,
  extreme: 100,
  entry: 112,
  target: 124,
  startTime: time,
  boundary: [
    { time, price: 110 },
    { time: time + 120, price: 110 },
  ],
  structure: [
    [
      { time, price: 100 },
      { time: time + 120, price: 110 },
    ],
  ],
}
const read = (events = [event], bs = bars, price: number | null = null) =>
  makePatternGuidance(events, bs, 60, bs.at(-1)!.time + 60, price)
it('automatically explains a confirmed shape with its boundary, projection and invalidation', () => {
  const r = read()
  expect(r).toMatchObject({
    status: 'confirmed',
    side: 'CALL',
    boundary: 110,
    stop: 100,
    target: 124,
  })
  expect(r.event?.pattern).toBe('double-bottom')
  expect(r.expectation).toMatch(/upward|rise/i)
  expect(r.next).toMatch(/retest/i)
})
it('does not turn an older confirmed label or an unconfirmed candidate into a new entry', () => {
  expect(read([event], [...bars, bar(3)])).toMatchObject({ status: 'active' })
  expect(read([{ ...event, confirmed: false }]).status).toBe('none')
  const old = Array.from({ length: 11 }, (_, i) => bar(i))
  expect(read([{ ...event, time }], old).status).toBe('none')
})
it('conflicting directions at the same knowledge time wait without fabricated levels', () => {
  const r = read([
    event,
    { ...event, side: 'PUT', pattern: 'double-top', name: 'Double Top', extreme: 120 },
  ])
  expect(r.status).toBe('mixed')
  expect(r.target).toBeNull()
  expect(r.next).toMatch(/wait/i)
})
it('retires a verified failed breakout, a touched target and ambiguous barriers', () => {
  expect(read([event], [...bars, bar(3, 109, 113, 108)]).status).toBe('invalidated')
  expect(read([event], [...bars, bar(3, 123, 125, 112)]).status).toBe('target')
  expect(read([event], [...bars, bar(3, 112, 125, 99)]).status).toBe('ambiguous')
})
it('live crossing is provisional and never changes confirmed history or assumes a fill', () => {
  const before = JSON.stringify(event),
    r = read([event], bars, 99)
  expect(r.status).toBe('confirmed')
  expect(r.liveNote).toMatch(/invalidation.*intrabar|intrabar.*invalidation/i)
  expect(JSON.stringify(event)).toBe(before)
})
it('excludes forming bars and future events even when supplied in the input', () => {
  const r = makePatternGuidance(
    [{ ...event, time: time + 180 }],
    [...bars, bar(3)],
    60,
    time + 180,
    null
  )
  expect(r.status).toBe('none')
})
it('shows neutral indecision without directional target or action', () => {
  const r = read([{ ...event, side: 'NEUTRAL', name: 'Doji', pattern: 'doji', confirmed: false }])
  expect(r.status).toBe('neutral')
  expect(r.target).toBeNull()
  expect(r.expectation).toMatch(/direction|indecision/i)
})
it('tracks every forming candle and rejects stale, future and historical receipts', () => {
  const current = bar(3, 113, 114, 110),
    now = time + 195
  expect(liveCandleProgress(current, 60, now, now, true)).toMatchObject({
    state: 'forming',
    direction: 'bullish',
    remaining: 45,
  })
  expect(
    liveCandleProgress({ ...current, close: 109, low: 108 }, 60, now + 1, now + 1, true)
  ).toMatchObject({ state: 'forming', direction: 'bearish', remaining: 44 })
  expect(liveCandleProgress(current, 60, now - 16, now, true).state).toBe('stale')
  expect(liveCandleProgress(current, 60, now + 1, now, true).state).toBe('stale')
  expect(liveCandleProgress(current, 60, now, now, false).state).toBe('history')
  expect(liveCandleProgress(current, 60, time + 241, time + 241, true).state).toBe('waiting')
})

it('retires observations across an unscheduled missing candle or malformed source bar', () => {
  expect(read([event], [...bars, bar(4)]).status).toBe('none')
  expect(read([event], [...bars, { ...bar(3), high: NaN }, bar(4)]).status).toBe('none')
})
it('prefers a chart outline over a generic same-side candle label without hiding the other evidence', () => {
  const r = read([
    {
      ...event,
      name: 'Engulfing confirmed',
      pattern: 'confirmed-engulfing',
      structure: undefined,
      target: undefined,
      boundary: undefined,
    },
    { ...event, target: undefined },
  ])
  expect(r.event?.name).toBe('Double Bottom')
  expect(r.others).toContain('Engulfing confirmed')
})

it.each([
  ['CALL', 100, 124, 99, 113, 'invalidated'],
  ['CALL', 100, 124, 111, 125, 'target'],
  ['CALL', 100, 124, 99, 125, 'ambiguous'],
  ['PUT', 124, 100, 111, 125, 'invalidated'],
  ['PUT', 124, 100, 99, 113, 'target'],
  ['PUT', 124, 100, 99, 125, 'ambiguous'],
] as const)('ignores %s confirmation-bar touches of stop=%s target=%s low=%s high=%s until a later verified candle', (side, extreme, target, low, high, retired) => {
  const e = { ...event, side, extreme, target, boundary: undefined }
  const confirming = [bar(0), bar(1), bar(2, 112, high, low)]
  expect(read([e], confirming).status).toBe('confirmed')
  expect(read([e], [...confirming, bar(3, 112, high, low)]).status).toBe(retired)
})

it.each([
  ['CALL', 100, 110, 113, 115],
  ['PUT', 120, 110, 107, 105],
] as const)('uses the explicit forming-candle time for a %s sloped boundary', (side, start, end, livePrice, projected) => {
  const e = { ...event, side, extreme: undefined, target: undefined,
    boundary: [{ time, price: start }, { time: time + 120, price: end }] }
  const r = makePatternGuidance([e], bars, 60, time + 190, livePrice, null, false, time + 180)
  expect(r.status).toBe('confirmed')
  expect(r.boundary).toBe(projected)
  expect(r.liveNote).toMatch(/back through.*intrabar/i)
  // A later completed candle still retires against its own boundary, not the live projection.
  const later = makePatternGuidance([e], [...bars, bar(3, side === 'CALL' ? 116 : 104)],
    60, time + 240, livePrice, null, false, time + 240)
  expect(later.status).toBe('active')
  expect(later.boundary).toBe(side === 'CALL' ? 120 : 100)
})

it('counts an available forming slot within the recent ten chart candles', () => {
  const source = Array.from({ length: 11 }, (_, i) => bar(i))
  const oldest = { ...event, time, extreme: undefined, target: undefined, boundary: undefined }
  expect(makePatternGuidance([oldest], source.slice(0, 10), 60, time + 600, null).status).toBe('active')
  expect(makePatternGuidance([oldest], source, 60, time + 600, null).status).toBe('none')
  expect(makePatternGuidance([{ ...oldest, time: time + 60 }], source, 60, time + 600, null).status).toBe('active')
  expect(makePatternGuidance([oldest], source.slice(0, 10), 60, time + 600, 112, null, false, time + 600).status).toBe('none')
})

it.each([false, true])('caps additional names while preserving the hidden count (mixed=%s)', (mixed) => {
  const events = [event, ...['Hammer', 'Harami', 'Engulfing', 'Morning Star', 'Piercing'].map((name, i) => ({
    ...event, name, pattern: `other-${i}`, structure: undefined,
    side: mixed && i === 0 ? 'PUT' as const : 'CALL' as const,
  }))]
  const r = read(events)
  expect(r.status).toBe(mixed ? 'mixed' : 'confirmed')
  expect(r.others).toHaveLength(3)
  expect(r.otherCount).toBe(mixed ? 6 : 5)
})
