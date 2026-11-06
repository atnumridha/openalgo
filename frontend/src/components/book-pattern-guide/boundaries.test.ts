import { describe, it, expect } from 'vitest'
import { CANDLE_FIXTURES, bar, timed, trendBars, TEST_CONTEXT } from './fixtures'
import { detectCandles } from './candles'
import {
  analyzeBookGuide,
  advanceBookCandidate,
  BookPatternEngine,
  qualifyBookEvent,
} from './engine'
import { DEFAULT_BOOK_SETTINGS as S } from './settings'
import type { BookEvent, BookFormation } from './types'
function event(f: Partial<BookFormation> = {}): BookEvent {
  return {
    id: 'test',
    patternId: 'bull-engulfing',
    name: 'Fixture',
    side: 'long',
    sourcePhotos: [39],
    kind: 'candle',
    mode: 'reversal',
    startIndex: 0,
    endIndex: 0,
    recognitionIndex: 0,
    formationStart: 100,
    formationEnd: 100,
    recognitionTime: 100,
    status: 'pending',
    nextCondition: 'Later close',
    trigger: 110,
    stopAnchor: 99,
    stopMethod: 'source',
    targetMethod: 'r-multiple',
    scale: 2,
    contacts: 2,
    rank: 3,
    points: [],
    segments: [],
    notes: [],
    confirmationRule: 'later-close',
    priorTrend: 'bear',
    ...f,
  }
}
const context = { ...TEST_CONTEXT, tickSize: 0.1 }
const advance = (
  e: BookEvent,
  rows: ReturnType<typeof bar>[],
  index = 1,
  armIndex?: number,
  boundary?: number
) => advanceBookCandidate({ event: e, armIndex, boundary }, timed(rows), index, context, S)

describe('nearby valid-OHLC counterexamples for every candle family', () => {
  for (const fixture of CANDLE_FIXTURES)
    it(`rejects nearby nonpattern ${fixture.id}`, () => {
      const rows = fixture.rows.map((b) => ({ ...b }))
      const last = rows.length - 1,
        b = rows[last]!
      // Removing the terminal candle's defining color/wick/size/level relationship must remove this family.
      if (
        [
          'rising-three-methods',
          'falling-three-methods',
          'tweezer-bottom',
          'tweezer-top',
          'three-white-soldiers',
          'three-black-crows',
          'bull-harami',
          'bear-harami',
          'piercing-line',
          'dark-cloud-cover',
          'morning-star',
          'evening-star',
          'bull-engulfing',
          'bear-engulfing',
        ].includes(fixture.id)
      )
        rows[last] = { ...b, open: b.close, close: b.open }
      else if (['hammer', 'hanging-man', 'inverted-hammer', 'shooting-star'].includes(fixture.id))
        rows[last] = bar(101, 110, 100, 109)
      else if (fixture.id.includes('marubozu')) rows[last] = bar(103, 110, 100, 107)
      else rows[last] = bar(96, 105, 95, 104)
      const bars = timed([...trendBars('long'), ...rows])
      expect(
        detectCandles(bars, bars.length - 1, S, 0.01, 2, []).some((f) => f.patternId === fixture.id)
      ).toBe(false)
    })
  it('does not require a body gap for engulfing geometry and separately applies strict full-range mode', () => {
    const rows = timed([...trendBars('short'), bar(106, 112, 95, 100), bar(100, 110, 99, 107)])
    expect(
      detectCandles(rows, 71, S, 0.01, 2, []).some((f) => f.patternId === 'bull-engulfing')
    ).toBe(true)
    expect(
      detectCandles(rows, 71, { ...S, strictRangeEngulfing: true }, 0.01, 2, []).some(
        (f) => f.patternId === 'bull-engulfing'
      )
    ).toBe(false)
  })
})

describe('source confirmation exceptions are closed, later and causal', () => {
  it('does not use a formation candle as its own confirmation', () => {
    expect(advance(event(), [bar(111, 114, 110, 113)], 0).state).toBe('waiting')
  })
  it('full tick beyond anchor is inclusive; equality and sub-tick closes fail', () => {
    for (const close of [110, 110.09])
      expect(advance(event(), [bar(100, 110, 99, 108), bar(109, 111, 108, close)]).state).toBe(
        'waiting'
      )
    expect(advance(event(), [bar(100, 110, 99, 108), bar(109, 111, 108, 110.1)]).state).toBe(
      'confirmed'
    )
  })
  it('explicit engulfing confirmation requires an open beyond second close, continuous variant can relax only that gap', () => {
    const e = event(),
      rows = timed([bar(100, 110, 99, 108), bar(107, 112, 106, 111)])
    expect(advanceBookCandidate({ event: e }, rows, 1, context, S).state).toBe('waiting')
    expect(
      advanceBookCandidate({ event: e }, rows, 1, context, { ...S, gapPolicy: 'continuous' }).state
    ).toBe('confirmed')
  })
  it('inverted hammer confirms above body while still below wick high, but never one candle late', () => {
    const e = event({
      patternId: 'inverted-hammer',
      trigger: 102,
      confirmationRule: 'inverted-body',
    })
    expect(advance(e, [bar(100, 110, 99, 102), bar(102.1, 105, 102, 104)]).state).toBe('confirmed')
    expect(advance(e, [bar(100, 110, 99, 102), bar(101, 105, 100, 104)]).state).toBe('expired')
    expect(
      advance(e, [bar(100, 110, 99, 102), bar(101, 105, 100, 104), bar(103, 106, 102, 105)], 2)
        .state
    ).toBe('expired')
  })
  it('support/resistance only permits the next candle and needs its directional close beyond original extreme', () => {
    const e = event({
      patternId: 'sr-long',
      kind: 'level',
      mode: 'neutral',
      confirmationRule: 'next-extreme',
      trigger: 110,
    })
    expect(advance(e, [bar(100, 110, 99, 108), bar(109, 112, 108, 111)]).state).toBe('confirmed')
    expect(advance(e, [bar(100, 110, 99, 108), bar(109, 112, 108, 109.5)]).state).toBe('expired')
    expect(
      advance(e, [bar(100, 110, 99, 108), bar(109, 112, 108, 109.5), bar(110, 113, 109, 112)], 2)
        .state
    ).toBe('expired')
  })
  it.each([
    'long',
    'short',
  ] as const)('rectangle %s requires breakout then next open/close and preserves asymmetric stop', (side) => {
    const long = side === 'long',
      e = event({
        patternId: long ? 'bull-rectangle' : 'bear-rectangle',
        side,
        kind: 'shape',
        mode: 'continuation',
        confirmationRule: 'next-boundary',
        trigger: long ? 110 : 100,
        stopAnchor: long ? 99 : 111,
      })
    const rows = long
      ? [bar(105, 109, 101, 108), bar(108, 113, 107, 112), bar(111, 115, 110.5, 114)]
      : [bar(105, 109, 101, 102), bar(102, 103, 97, 98), bar(99, 99.5, 95, 96)]
    const armed = advance(e, rows)
    expect(armed.state).toBe('waiting')
    expect(armed.candidate.armIndex).toBe(1)
    expect(armed.candidate.event.stopAnchor).toBe(long ? 107 : 111)
    const confirmed = advanceBookCandidate(armed.candidate, timed(rows), 2, context, S)
    expect(confirmed.state).toBe('confirmed')
    expect(confirmed.candidate.event.stopAnchor).toBe(long ? 107 : 111)
    expect(
      advanceBookCandidate(
        armed.candidate,
        timed(
          rows.map((b, j) =>
            j === 2
              ? {
                  ...b,
                  open: long ? 109 : 101,
                  low: long ? 108.5 : b.low,
                  high: long ? b.high : 101.5,
                }
              : b
          )
        ),
        2,
        context,
        S
      ).state
    ).toBe('expired')
  })
  it('uses the frozen trendline for a later retest, not the break candle or later pivots', () => {
    const line = [
      {
        side: 'high' as const,
        index: 0,
        time: 100,
        recognitionTime: 100,
        recognitionIndex: 0,
        price: 110,
      },
      {
        side: 'high' as const,
        index: 4,
        time: 340,
        recognitionTime: 340,
        recognitionIndex: 4,
        price: 106,
      },
    ] as const
    const e = event({
      patternId: 'trendline-long',
      kind: 'trendline',
      endIndex: 5,
      recognitionIndex: 5,
      confirmationRule: 'retest',
      line: [...line],
    })
    const rows = timed(Array.from({ length: 7 }, () => bar(104, 107, 103, 106)))
    rows[6] = bar(104, 106, 103.8, 105)
    expect(advanceBookCandidate({ event: e }, rows, 5, context, S).state).toBe('waiting')
    expect(advanceBookCandidate({ event: e }, rows, 6, context, S).state).toBe('confirmed')
  })
  it('keeps a three-method corrective stop valid despite earlier impulse wick and rejects fifth-candle breach', () => {
    const bars = timed([
      ...trendBars('long'),
      ...CANDLE_FIXTURES.find((f) => f.id === 'rising-three-methods')!.rows,
    ])
    const f = detectCandles(bars, 74, S, 0.01, 2, []).find(
      (f) => f.patternId === 'rising-three-methods'
    )!
    expect(f.stopAnchor).toBe(102)
    const e = { ...event(f), priorTrend: 'bull' as const }
    const confirmation = bar(113, 116, 111, 115)
    expect(
      advanceBookCandidate({ event: e }, timed([...bars, confirmation]), 75, context, S).state
    ).toBe('confirmed')
  })
})

describe('reconciliation availability and label rules', () => {
  const base = () =>
    timed([...trendBars('short'), bar(100, 110, 99.9, 102), bar(102.5, 105, 102.3, 104)])
  it('suppresses stale/disconnected/synthetic alerts and consumes them without reconnect replay', () => {
    const engine = new BookPatternEngine(),
      rows = base()
    engine.reconcile(rows.slice(0, -1), TEST_CONTEXT)
    const stale = engine.reconcile(rows, { ...TEST_CONTEXT, observedAt: TEST_CONTEXT.now - 16 })
    expect(stale.readiness).toBe('unavailable')
    expect(stale.alerts).toEqual([])
    expect(engine.reconcile(rows, TEST_CONTEXT).alerts).toEqual([])
    expect(analyzeBookGuide(rows, { ...TEST_CONTEXT, connected: false }).readiness).toBe(
      'unavailable'
    )
    expect(analyzeBookGuide(rows, { ...TEST_CONTEXT, chartType: 'synthetic' }).readiness).toBe(
      'unavailable'
    )
    expect(
      analyzeBookGuide(rows, { ...TEST_CONTEXT, marketOpen: false, observedAt: 1 }).readiness
    ).toBe('last-session')
  })
  it('retains frozen levels while old labels leave the ten-bar display window', () => {
    const rows = timed([...base(), ...Array.from({ length: 11 }, () => bar(104, 105, 103, 104.2))])
    const result = analyzeBookGuide(rows, TEST_CONTEXT)
    expect(result.activePlan?.name).toBe('Inverted hammer')
    expect(result.visibleEvents.some((e) => e.patternId === 'inverted-hammer')).toBe(false)
    expect(
      analyzeBookGuide(rows, TEST_CONTEXT, { fullHistory: true }).visibleEvents.some(
        (e) => e.patternId === 'inverted-hammer'
      )
    ).toBe(true)
  })
  it('does not create candle signals across repaired or invalid bars', () => {
    const rows = base()
    rows[70] = { ...rows[70]!, repaired: true }
    expect(analyzeBookGuide(rows, TEST_CONTEXT).activePlan).toBeUndefined()
  })
  it('failed pending trigger can re-arm a fresh pattern on that same bar', () => {
    const rows = timed([
      ...trendBars('short'),
      bar(100, 110, 99.9, 102),
      bar(99.5, 110, 99.4, 101.5),
      bar(102, 106, 101.8, 104),
    ])
    const result = analyzeBookGuide(rows, TEST_CONTEXT)
    expect(
      result.events.some(
        (e) =>
          e.patternId === 'inverted-hammer' &&
          e.formationEnd === rows[71]!.time &&
          e.confirmationTime === rows[72]!.time
      )
    ).toBe(true)
  })
  it('all returned earlier confirmations remain unchanged as a suffix arrives', () => {
    const rows = base(),
      first = analyzeBookGuide(rows, TEST_CONTEXT)
    const more = analyzeBookGuide(
      timed([...rows, bar(104, 106, 103, 105), bar(105, 107, 104, 106)]),
      TEST_CONTEXT
    )
    for (const e of first.events) expect(more.events.find((x) => x.id === e.id)).toEqual(e)
  })
  it('explains the exact pending condition even before a plan exists', () => {
    const result = analyzeBookGuide(base().slice(0, -1), TEST_CONTEXT)
    expect(result.nextCondition.toLowerCase()).toContain('next candle')
  })
})

describe('reference evidence and preceding-context guardrails', () => {
  it('rejects reversals without opposite preceding trend but permits broader MA conflict after reversal', () => {
    const e = { ...event(), status: 'confirmed' as const },
      b = bar(110, 113, 109, 112)
    const q = qualifyBookEvent(e, b, 2, context, S, [], { trend: 'bear', maFast: 114 })
    expect(q.plan).toBeDefined()
    expect(q.plan?.notes.join(' ')).toContain('Broader MA trend remains bear')
    expect(
      qualifyBookEvent({ ...e, priorTrend: 'bull' }, b, 2, context, S, [], {
        trend: 'bull',
        maFast: 100,
      }).plan
    ).toBeUndefined()
    expect(
      qualifyBookEvent({ ...e, priorTrend: 'unavailable' }, b, 2, context, S, [], {
        trend: 'bull',
        maFast: 100,
      }).plan
    ).toBeUndefined()
  })
  it('requires continuation close beyond current fast MA; neutral local plans require strict current trend', () => {
    const b = bar(110, 113, 109, 112)
    expect(
      qualifyBookEvent(event({ mode: 'continuation' }), b, 2, context, S, [], {
        trend: 'bull',
        maFast: 111,
      }).plan
    ).toBeUndefined()
    expect(
      qualifyBookEvent(
        { ...event({ mode: 'continuation' }), priorTrend: 'bull' },
        b,
        2,
        context,
        S,
        [],
        { trend: 'bull', maFast: 112 }
      ).plan
    ).toBeUndefined()
    expect(
      qualifyBookEvent(event({ mode: 'neutral' }), b, 2, context, S, [], {
        trend: 'neutral',
        maFast: 111,
      }).plan
    ).toBeUndefined()
  })
  it('requires each enabled oscillator independently; equality never passes', () => {
    const e = event(),
      b = bar(110, 113, 109, 112)
    expect(
      qualifyBookEvent(e, b, 2, context, { ...S, rsiFilter: true }, [], { trend: 'bull', rsi: 50 })
        .plan
    ).toBeUndefined()
    expect(
      qualifyBookEvent(e, b, 2, context, { ...S, macdFilter: true }, [], {
        trend: 'bull',
        macd: 1,
        macdSignal: 1,
      }).plan
    ).toBeUndefined()
    expect(
      qualifyBookEvent(e, b, 2, context, { ...S, rsiFilter: true, macdFilter: true }, [], {
        trend: 'bull',
        rsi: 60,
        macd: 0,
        macdSignal: 1,
      }).plan
    ).toBeUndefined()
    expect(
      qualifyBookEvent(e, b, 2, context, { ...S, rsiFilter: true }, [], { trend: 'bull', rsi: 60 })
        .plan
    ).toBeDefined()
  })
  it('does not reinterpret RSI extremes alone as entry triggers', () => {
    const r = analyzeBookGuide(trendBars('long'), TEST_CONTEXT)
    expect(r.indicators.rsi).toBe(100)
    expect(r.activePlan).toBeUndefined()
  })
  it('gives a frozen measured boundary and direct breakout/role-reversal observations their original parent event', () => {
    // Horizontal pivots are recognized before the breakout begins.
    const waves = Array.from({ length: 41 }, (_, i) => {
      const p = 105 + 5 * Math.cos((i * Math.PI) / 8)
      return bar(p - 0.1, p + 0.2, p - 0.2, p + 0.1)
    })
    const rows = timed([
      ...trendBars('long'),
      ...waves,
      bar(109, 113, 108, 112),
      bar(112.2, 115, 111.5, 114),
    ])
    const result = analyzeBookGuide(rows, TEST_CONTEXT, { minRR: 0 })
    expect(result.observations.some((o) => o.type === 'direct-breakout' && !!o.parentEventId)).toBe(
      true
    )
  })
  it('marks three-method geometry invalid if the fifth candle has already crossed its corrective stop', () => {
    const fixture = CANDLE_FIXTURES.find((f) => f.id === 'rising-three-methods')!
    const rows = fixture.rows.map((b) => ({ ...b }))
    rows[4] = { ...rows[4]!, low: 101 }
    const input = timed([...trendBars('long'), ...rows, bar(113, 116, 111, 115)])
    expect(
      analyzeBookGuide(input, TEST_CONTEXT).events.some(
        (e) => e.patternId === 'rising-three-methods'
      )
    ).toBe(false)
  })
  it('records recognition and arming/qualification IDs without backdating them', () => {
    const rows = timed([
      ...trendBars('short'),
      bar(100, 110, 99.9, 102),
      bar(102.5, 105, 102.3, 104),
    ])
    const e = analyzeBookGuide(rows, TEST_CONTEXT).events.find(
      (e) => e.patternId === 'inverted-hammer'
    )!
    expect(e.armingId).not.toBe(e.id)
    expect(e.qualificationId).not.toBe(e.armingId)
    expect(e.armedAt).toBe(rows[70]!.time)
    expect(e.qualificationTime).toBe(rows[71]!.time)
  })
})

describe('relative body size is distinct from a small-body morphology cutoff', () => {
  it('harami requires a smaller contained opposite body, without inventing a 30% second-range condition', () => {
    const rows = timed([...trendBars('long'), bar(110, 111, 99, 100), bar(104, 107, 103, 106)])
    expect(detectCandles(rows, 71, S, 0.01, 2, []).some((f) => f.patternId === 'bull-harami')).toBe(
      true
    )
  })
  it('three methods allows smaller corrective bodies with substantial ranges', () => {
    const rows = timed([
      ...trendBars('long'),
      bar(100, 111, 99, 110),
      bar(108, 109, 104, 105),
      bar(107, 108, 103, 104),
      bar(106, 107, 102, 103),
      bar(105, 113, 104, 112),
    ])
    expect(
      detectCandles(rows, 74, S, 0.01, 2, []).some((f) => f.patternId === 'rising-three-methods')
    ).toBe(true)
  })
  it('star third candle needs opposite midpoint confirmation rather than an extra long-body condition', () => {
    const rows = timed([
      ...trendBars('short'),
      bar(110, 111, 99, 100),
      bar(98, 99, 96, 97.5),
      bar(99, 115, 98, 106),
    ])
    expect(
      detectCandles(rows, 72, S, 0.01, 2, []).some((f) => f.patternId === 'morning-star')
    ).toBe(true)
  })
})
