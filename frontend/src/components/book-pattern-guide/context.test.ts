import { describe, it, expect } from 'vitest'
import { analyzeBookGuide, BookPatternEngine } from './engine'
import { indicators, confirmedPivots } from './math'
import { calculateBookRisk } from './risk'
import { DEFAULT_BOOK_SETTINGS as S } from './settings'
import { bar, timed, trendBars, TEST_CONTEXT } from './fixtures'

describe('indicator context from received completed price data', () => {
  it('computes hand-derived seeded EMA/SMA, Wilder ATR/RSI and MACD rather than future values', () => {
    const rows = timed(
      Array.from({ length: 70 }, (_, i) => bar(100 + i, 101.5 + i, 99.5 + i, 101 + i))
    )
    const x = indicators(rows, S).at(-1)!
    expect(x.maFast).toBeCloseTo(160.5, 10)
    expect(x.maSlow).toBeCloseTo(145.5, 10)
    expect(x.atr).toBe(2)
    expect(x.rsi).toBe(100)
    expect(x.macd).toBeCloseTo(7, 10)
    expect(x.macdSignal).toBeCloseTo(7, 10)
    const alternating = timed(
      Array.from({ length: 70 }, (_, i) =>
        bar(100 + (i % 3), 103 + (i % 3), 99 + (i % 3), 101 + (i % 3))
      )
    )
    const simple = indicators(alternating, { ...S, maType: 'sma' }).at(-1)!
    expect(simple.maFast).toBeCloseTo(102, 10)
    expect(simple.maSlow).toBeCloseTo(102, 10)
  })
  it('publishes SMA/price-MA, MACD signal/zero crosses and RSI recrosses as context without automatically making a plan', () => {
    const descending = trendBars('short')
    const reversal = Array.from({ length: 80 }, (_, i) =>
      bar(105 + i * 0.8, 105.6 + i * 0.8, 104.8 + i * 0.8, 105.3 + i * 0.8)
    )
    const result = analyzeBookGuide(timed([...descending, ...reversal]), TEST_CONTEXT, {
      maType: 'sma',
    })
    for (const type of [
      'ma-cross',
      'price-ma-cross',
      'macd-signal-cross',
      'macd-zero-cross',
      'rsi-recross',
    ])
      expect(
        result.observations.some((o) => o.type === type),
        type
      ).toBe(true)
    expect(result.events.every((e) => !e.patternId.includes('cross'))).toBe(true)
  })
  it('matches divergence oscillator samples to the same confirmed price pivots and publishes at recognition, never at the old pivot', () => {
    const values = trendBars('short').map((b) => b.close)
    const segment = (from: number, to: number, count: number) =>
      Array.from({ length: count }, (_, i) => from + ((to - from) * (i + 1)) / count)
    values.push(
      ...segment(105, 112, 8),
      ...segment(112, 100, 8),
      ...segment(100, 110, 12),
      ...segment(110, 99, 20),
      ...segment(99, 108, 8)
    )
    const rows = timed(values.map((p) => bar(p + 0.05, p + 0.3, p - 0.3, p)))
    const result = analyzeBookGuide(rows, TEST_CONTEXT),
      pivots = confirmedPivots(rows, 3, 3)
    const divergence = result.observations.find(
      (o) => o.type === 'rsi-divergence' && o.side === 'long'
    )
    expect(divergence).toBeDefined()
    const last = divergence!.points!.at(-1)!
    expect(divergence!.time).toBe(rows[last.index + 3]!.time)
    expect(last.time).toBe(rows[last.index]!.time)
    expect(pivots.find((p) => p.index === last.index)?.recognitionTime).toBe(divergence!.time)
    const before = analyzeBookGuide(
      rows.filter((b) => b.time < divergence!.time),
      TEST_CONTEXT
    )
    expect(before.observations.find((o) => o.id === divergence!.id)).toBeUndefined()
  })
  it('resets oscillator warmup at an invalid candle and does not bridge unreliable volume', () => {
    const rows = trendBars('long')
    rows[60] = { ...rows[60]!, repaired: true }
    rows[65] = { ...rows[65]!, volume: NaN }
    const x = indicators(rows, S).at(-1)!
    expect(x.trend).toBe('unavailable')
    expect(x.rsi).toBeUndefined()
    expect(x.volumeMean).toBeUndefined()
  })
  it('does not treat repeated equal highs as strict confirmed pivots', () => {
    const rows = timed([
      bar(5, 6, 4, 5),
      bar(6, 8, 5, 6),
      bar(7, 9, 6, 7),
      bar(7, 9, 6, 7),
      bar(6, 8, 5, 6),
      bar(5, 6, 4, 5),
    ])
    expect(confirmedPivots(rows, 2, 2).some((p) => p.side === 'high')).toBe(false)
  })
  it('uses a future-prefix-independent frozen ATR and stops/targets', () => {
    const rows = timed([
      ...trendBars('short'),
      bar(100, 110, 99.9, 102),
      bar(102.5, 105, 102.3, 104),
    ])
    const before = analyzeBookGuide(rows, TEST_CONTEXT)
    const after = analyzeBookGuide(timed([...rows, bar(104, 130, 80, 110)]), TEST_CONTEXT)
    const e = before.events.find((e) => e.patternId === 'inverted-hammer')!
    expect(after.events.find((x) => x.id === e.id)?.scale).toBe(e.scale)
    expect(after.lastTerminalPlan?.stop).toBe(before.activePlan?.stop)
    expect(after.lastTerminalPlan?.status).toBe('ambiguous')
  })
})

describe('instrument sizing refusal and exact step boundaries', () => {
  const p = { entry: 100, stop: 98, target: 106, side: 'long' as const }
  it('one complete quantity step is inclusive and a smaller risk budget is unavailable', () => {
    const u = { ...TEST_CONTEXT.instrument!, quantityStep: 5 }
    expect(calculateBookRisk(p, { ...S, equity: 1000, riskPercent: 1 }, u).quantity).toBe(5)
    expect(calculateBookRisk(p, { ...S, equity: 999, riskPercent: 1 }, u).quantity).toBeUndefined()
  })
  it('does not multiply explicit per-contract point value by lot size again', () => {
    const risk = calculateBookRisk(
      p,
      { ...S, equity: 10000, riskPercent: 1 },
      {
        ...TEST_CONTEXT.instrument!,
        unitDefinition: 'contract',
        valuePerPriceUnit: 10,
        quantityStep: 1,
        lotSize: 10,
      }
    )
    expect(risk.quantity).toBe(5)
    expect(risk.estimatedRiskCash).toBe(100)
  })
  it('refuses non-premium option and index charts and invalid cost inputs', () => {
    const s = { ...S, equity: 10000 }
    expect(
      calculateBookRisk(p, s, {
        ...TEST_CONTEXT.instrument!,
        unitDefinition: 'option-premium',
        chartPriceKind: 'underlying',
      }).quantity
    ).toBeUndefined()
    expect(
      calculateBookRisk(p, s, { ...TEST_CONTEXT.instrument!, kind: 'index' }).quantity
    ).toBeUndefined()
    expect(
      calculateBookRisk(p, { ...s, fixedCost: 100000 }, TEST_CONTEXT.instrument).quantity
    ).toBeUndefined()
    expect(
      calculateBookRisk(p, { ...s, slippagePrice: -1 }, TEST_CONTEXT.instrument).quantity
    ).toBeUndefined()
  })
  it('exposes absent linear unit definition as unavailable instead of fabricating quantity', () => {
    expect(
      calculateBookRisk(
        p,
        { ...S, equity: 10000 },
        { ...TEST_CONTEXT.instrument!, unitDefinition: undefined as never }
      ).quantity
    ).toBeUndefined()
  })
})

describe('verified session close-time adapter contract', () => {
  const rows = () =>
    timed([...trendBars('short'), bar(100, 110, 99.9, 102), bar(102.5, 105, 102.3, 104)]).map(
      (b, i) => ({ ...b, closeTime: b.time + (i === 71 ? 30 : 60) })
    )
  it('accepts an earlier verified session close only once that close has been observed', () => {
    const bars = rows(),
      last = bars.at(-1)!,
      engine = new BookPatternEngine()
    expect(
      engine.reconcile(bars, { ...TEST_CONTEXT, now: last.time + 29, observedAt: last.time + 29 })
        .activePlan
    ).toBeUndefined()
    const confirmed = engine.reconcile(bars, {
      ...TEST_CONTEXT,
      now: last.time + 30,
      observedAt: last.time + 30,
    })
    expect(confirmed.activePlan?.name).toBe('Inverted hammer')
    expect(confirmed.alerts.some((a) => a.type === 'qualified-plan')).toBe(true)
  })
  it('never promotes a candle using the wall clock alone without a received close observation', () => {
    const bars = rows(),
      last = bars.at(-1)!
    const r = analyzeBookGuide(bars, {
      ...TEST_CONTEXT,
      now: last.time + 3600,
      observedAt: last.time + 29,
    })
    expect(r.activePlan).toBeUndefined()
    expect(r.provisional?.time).toBe(last.time)
  })
  it('rejects invalid supplied close times rather than trusting them or silently falling back', () => {
    const bars = rows(),
      last = bars.at(-1)!
    expect(
      analyzeBookGuide(
        bars.map((b, i) => (i === 71 ? { ...b, closeTime: last.time } : b)),
        TEST_CONTEXT
      ).activePlan
    ).toBeUndefined()
    expect(
      analyzeBookGuide(
        bars.map((b, i) => (i === 71 ? { ...b, closeTime: NaN } : b)),
        TEST_CONTEXT
      ).activePlan
    ).toBeUndefined()
  })
  it('uses nominal interval fallback only when an explicit close time is absent', () => {
    const bars = timed([
        ...trendBars('short'),
        bar(100, 110, 99.9, 102),
        bar(102.5, 105, 102.3, 104),
      ]),
      last = bars.at(-1)!
    expect(
      analyzeBookGuide(bars, { ...TEST_CONTEXT, now: last.time + 59, observedAt: last.time + 59 })
        .activePlan
    ).toBeUndefined()
    expect(
      analyzeBookGuide(bars, { ...TEST_CONTEXT, now: last.time + 60, observedAt: last.time + 60 })
        .activePlan
    ).toBeDefined()
  })
})

describe('separate history observation and live quote freshness', () => {
  it('a fresh history response does not disguise an old live quote during an open market', () => {
    const rows = trendBars('long')
    const stale = analyzeBookGuide(rows, {
      ...TEST_CONTEXT,
      quoteObservedAt: TEST_CONTEXT.now - 16,
    })
    expect(stale.readiness).toBe('unavailable')
    expect(stale.unavailableReasons).toContain('Live quote is stale')
    expect(
      analyzeBookGuide(rows, { ...TEST_CONTEXT, quoteObservedAt: TEST_CONTEXT.now - 15 }).readiness
    ).toBe('ready')
  })
  it('after the session, an old quote retains last-session references without a stale-quote failure', () => {
    expect(
      analyzeBookGuide(trendBars('long'), {
        ...TEST_CONTEXT,
        marketOpen: false,
        quoteObservedAt: 1,
      }).readiness
    ).toBe('last-session')
  })
})

describe('forming-quote reconciliation retains confirmed prefix', () => {
  it('refreshes forming distances and readiness while confirmed events and frozen references stay identical', () => {
    const closed = timed([
        ...trendBars('short'),
        bar(100, 110, 99.9, 102),
        bar(102.5, 105, 102.3, 104),
      ]),
      forming = bar(104, 106, 103, 105, closed.length)
    const now = forming.time + 20,
      c = { ...TEST_CONTEXT, now, observedAt: now, quoteObservedAt: now },
      engine = new BookPatternEngine()
    const first = engine.reconcile([...closed, forming], c)
    for (let i = 0; i < 20; i++) {
      const price = 104 + i * 0.05,
        result = engine.reconcile([...closed, { ...forming, close: price }], {
          ...c,
          now: now + i,
          observedAt: now + i,
          quoteObservedAt: now + i,
        })
      expect(result.events).toEqual(first.events)
      expect(result.activePlan).toEqual(first.activePlan)
      expect(result.alerts).toEqual([])
      expect(result.provisional?.price).toBe(price)
      expect(result.provisional?.distanceToStop).toBeCloseTo(price - first.activePlan!.stop, 10)
    }
    const stale = engine.reconcile([...closed, forming], { ...c, quoteObservedAt: now - 16 })
    expect(stale.readiness).toBe('unavailable')
    expect(stale.explanation).toContain('Live quote is stale')
    expect(engine.reconcile([...closed, forming], c).explanation).not.toContain(
      'Live quote is stale'
    )
  })
  it('measures a bounded 3000-bar history and twenty unchanged-prefix quote refreshes', () => {
    const closed = timed(
      Array.from({ length: 3000 }, (_, i) => {
        const p = 100 + i * 0.01 + Math.sin(i * 0.12) * 2
        return bar(p, p + 0.3, p - 0.3, p + 0.1)
      })
    )
    const forming = bar(130, 131, 129, 130.2, 3000),
      now = forming.time + 10,
      c = { ...TEST_CONTEXT, now, observedAt: now },
      engine = new BookPatternEngine()
    const start = performance.now(),
      first = engine.reconcile([...closed, forming], c),
      batchMs = performance.now() - start
    const cached = performance.now()
    for (let i = 0; i < 20; i++)
      engine.reconcile([...closed, { ...forming, close: 130 + i * 0.01 }], c)
    const refreshMs = performance.now() - cached
    process.stdout.write(
      `${JSON.stringify({
        benchmark: 'book-engine',
        bars: 3000,
        initialMs: Math.round(batchMs),
        twentyQuoteUpdatesMs: Math.round(refreshMs),
        confirmedEvents: first.events.length,
      })}\n`
    )
    expect(first.indicators.trend).not.toBe('unavailable')
  }, 30_000)
})

describe('later qualified alternatives remain beside frozen references', () => {
  it('keeps opposite evidence visible on subsequent candles without replacing the active plan', () => {
    const initial = timed([
      ...trendBars('short'),
      bar(100, 110, 99.9, 102),
      bar(102.5, 105, 102.3, 104),
    ])
    const later = timed([
      ...initial,
      ...Array.from({ length: 43 }, () => bar(116, 116.35, 115.8, 116.25)),
      bar(116, 116.4, 108, 116.2),
      bar(109, 110, 106, 107),
    ])
    const result = analyzeBookGuide(later, TEST_CONTEXT)
    expect(result.activePlan?.name).toBe('Inverted hammer')
    expect(result.alternatives.some((e) => e.side === 'short')).toBe(true)
    expect(result.explanation).toContain('Opposite qualified evidence')
    const next = analyzeBookGuide(timed([...later, bar(107, 108, 106, 107.5)]), TEST_CONTEXT)
    expect(next.activePlan?.entry).toBe(104)
    expect(next.alternatives.some((e) => e.side === 'short')).toBe(true)
  })
})

describe('monetary sizing requires valid positive price references', () => {
  it('refuses a nonpositive buffered stop and nonfinite entry even when the arithmetic distance is positive', () => {
    expect(
      calculateBookRisk(
        { entry: 1, stop: -1, target: 7, side: 'long' },
        { ...S, equity: 10000 },
        TEST_CONTEXT.instrument
      ).quantity
    ).toBeUndefined()
    expect(
      calculateBookRisk(
        { entry: Infinity, stop: 1, target: 7, side: 'long' },
        { ...S, equity: 10000 },
        TEST_CONTEXT.instrument
      ).quantity
    ).toBeUndefined()
  })
})
