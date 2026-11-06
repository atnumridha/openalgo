import { describe, expect, it } from 'vitest'
import { detectCandles } from './candles'
import { analyzeBookGuide, BookPatternEngine } from './engine'
import { calculateBookRisk } from './risk'
import { DEFAULT_BOOK_SETTINGS } from './settings'
import { confirmedPivots, indicators, validBar } from './math'
import { CANDLE_FIXTURES, TEST_CONTEXT, bar, timed, trendBars } from './fixtures'

describe('book candle geometry and source stop anchors', () => {
  for (const fixture of CANDLE_FIXTURES) {
    it(`recognizes ${fixture.id} and rejects malformed OHLC`, () => {
      const bars = timed([...trendBars('long'), ...fixture.rows])
      const found = detectCandles(bars, bars.length - 1, DEFAULT_BOOK_SETTINGS, 0.01, 2, [])
      const event = found.find((f) => f.patternId === fixture.id)
      expect(event, fixture.id).toBeDefined()
      if (fixture.side !== 'neutral') expect(event?.stopAnchor).toBe(fixture.stop)
      const broken = bars.map((b, i) => (i === bars.length - 1 ? { ...b, high: b.low - 1 } : b))
      expect(
        detectCandles(broken, broken.length - 1, DEFAULT_BOOK_SETTINGS, 0.01, 2, []).find(
          (f) => f.patternId === fixture.id
        )
      ).toBeUndefined()
    })
  }
  it('preserves harami and engulfing stop asymmetries', () => {
    const bear = CANDLE_FIXTURES.find((f) => f.id === 'bear-harami')!
    const bull = CANDLE_FIXTURES.find((f) => f.id === 'bull-harami')!
    expect(
      detectCandles(
        timed([...trendBars('long'), ...bear.rows]),
        71,
        DEFAULT_BOOK_SETTINGS,
        0.01,
        2,
        []
      ).find((f) => f.patternId === bear.id)?.stopAnchor
    ).toBe(111)
    expect(
      detectCandles(
        timed([...trendBars('long'), ...bull.rows]),
        71,
        DEFAULT_BOOK_SETTINGS,
        0.01,
        2,
        []
      ).find((f) => f.patternId === bull.id)?.stopAnchor
    ).toBe(103)
  })
})

describe('causal math and monetary units', () => {
  it('rejects repaired, zero range and nonfinite prices', () => {
    expect(validBar({ ...bar(10, 12, 9, 11), repaired: true })).toBe(false)
    expect(validBar(bar(10, 10, 10, 10))).toBe(false)
    expect(validBar(bar(NaN, 12, 9, 11))).toBe(false)
  })
  it('only exposes a strict pivot after its right window closes', () => {
    const b = timed([
      bar(5, 6, 4, 5),
      bar(6, 7, 5, 6),
      bar(9, 10, 8, 9),
      bar(7, 8, 6, 7),
      bar(6, 7, 5, 6),
    ])
    expect(confirmedPivots(b.slice(0, 4), 2, 2)).toEqual([])
    expect(confirmedPivots(b, 2, 2)).toMatchObject([
      { index: 2, recognitionIndex: 4, price: 10, side: 'high' },
    ])
  })
  it('does not make trend available before 55 prior valid bars', () => {
    expect(indicators(trendBars('long').slice(0, 54), DEFAULT_BOOK_SETTINGS).at(-1)?.trend).toBe(
      'unavailable'
    )
    expect(indicators(trendBars('long'), DEFAULT_BOOK_SETTINGS).at(-1)?.trend).toBe('bull')
  })
  it('applies point value, FX and per-unit costs once and rounds down by step', () => {
    const risk = calculateBookRisk(
      { entry: 100, stop: 98, target: 106, side: 'long' },
      {
        equity: 100000,
        riskPercent: 1,
        fixedCost: 100,
        perUnitCost: 2,
        slippagePrice: 0.1,
      },
      {
        ...TEST_CONTEXT.instrument!,
        quoteCurrency: 'USD',
        conversionRate: 80,
        valuePerPriceUnit: 2,
        quantityStep: 0.5,
        lotSize: 5,
      }
    )
    expect(risk.quantity).toBe(2.5)
    expect(risk.lots).toBe(0.5)
    expect(risk.lossPerUnit).toBe(338)
    expect(risk.estimatedRiskCash).toBe(945)
  })
  it('refuses missing equity, conversion and nonlinear products without hiding RR', () => {
    const p = { entry: 100, stop: 98, target: 106, side: 'long' as const }
    expect(calculateBookRisk(p, DEFAULT_BOOK_SETTINGS, TEST_CONTEXT.instrument).rr).toBe(3)
    expect(
      calculateBookRisk(p, DEFAULT_BOOK_SETTINGS, TEST_CONTEXT.instrument).unavailableReasons
    ).toContain('Account equity is unset')
    expect(
      calculateBookRisk(
        p,
        { ...DEFAULT_BOOK_SETTINGS, equity: 1000 },
        { ...TEST_CONTEXT.instrument!, kind: 'inverse' }
      ).quantity
    ).toBeUndefined()
    expect(
      calculateBookRisk(
        p,
        { ...DEFAULT_BOOK_SETTINGS, equity: 1000 },
        { ...TEST_CONTEXT.instrument!, quoteCurrency: 'USD' }
      ).quantity
    ).toBeUndefined()
  })
})

describe('closed-candle reconciliation', () => {
  it('uses inverted-hammer body confirmation on the very next closed candle', () => {
    const bars = timed([
      ...trendBars('short'),
      bar(100, 110, 99.9, 102),
      bar(102.5, 105, 102.3, 104),
    ])
    const r = analyzeBookGuide(bars, TEST_CONTEXT)
    const e = r.events.find(
      (e) => e.patternId === 'inverted-hammer' && e.confirmationTime === bars.at(-1)!.time
    )
    expect(e?.status).toBe('confirmed')
    expect(e?.trigger).toBe(102)
    expect(r.activePlan?.entry).toBe(104)
  })
  it('requires a later close, freezes the plan, and suppresses first-run alerts', () => {
    const b = timed([...trendBars('short'), bar(100, 110, 99.9, 102), bar(102.5, 105, 102.3, 104)])
    const engine = new BookPatternEngine()
    const first = engine.reconcile(b, TEST_CONTEXT)
    expect(first.alerts).toEqual([])
    expect(first.activePlan).toBeDefined()
    const again = engine.reconcile(b, TEST_CONTEXT)
    expect(again.activePlan).toEqual(first.activePlan)
    expect(again.alerts).toEqual([])
    const next = engine.reconcile(timed([...b, bar(104, 105, 103, 104.5)]), TEST_CONTEXT)
    expect(next.activePlan?.entry).toBe(first.activePlan?.entry)
    expect(next.activePlan?.stop).toBe(first.activePlan?.stop)
  })
  it('excludes a forming candle and recomputes corrections without replay', () => {
    const bars = timed([
      ...trendBars('short'),
      bar(100, 110, 99.9, 102),
      bar(102.5, 105, 102.3, 104),
    ])
    const engine = new BookPatternEngine()
    const before = engine.reconcile(bars, { ...TEST_CONTEXT, now: bars.at(-1)!.time + 30 })
    expect(
      before.events.some((e) => e.patternId === 'inverted-hammer' && e.status === 'confirmed')
    ).toBe(false)
    const confirmed = engine.reconcile(bars, {
      ...TEST_CONTEXT,
      now: bars.at(-1)!.time + 60,
      observedAt: bars.at(-1)!.time + 60,
    })
    expect(confirmed.alerts.some((a) => a.type === 'qualified-plan')).toBe(true)
    const corrected = engine.reconcile(
      bars.map((b, i) => (i === bars.length - 1 ? { ...b, open: 101 } : b)),
      TEST_CONTEXT
    )
    expect(corrected.activePlan).toBeUndefined()
    expect(corrected.alerts).toEqual([])
  })
  it('is prefix deterministic and identity/settings changes suppress historical alerts', () => {
    const bars = timed([
      ...trendBars('short'),
      bar(100, 110, 99.9, 102),
      bar(102.5, 105, 102.3, 104),
    ])
    const live = new BookPatternEngine()
    for (let i = 1; i <= bars.length; i++) {
      const b = bars.slice(0, i)
      const result = live.reconcile(b, TEST_CONTEXT)
      const batch = analyzeBookGuide(b, TEST_CONTEXT)
      expect(result.events).toEqual(batch.events)
      expect(result.activePlan).toEqual(batch.activePlan)
    }
    expect(live.reconcile(bars, { ...TEST_CONTEXT, symbol: 'OTHER' }).alerts).toEqual([])
    expect(live.reconcile(bars, TEST_CONTEXT, { targetR: 4 }).alerts).toEqual([])
  })
})

describe('every candle fixture prefix agrees with deterministic batch analysis', () => {
  for (const fixture of CANDLE_FIXTURES)
    it(`${fixture.id}: no future confirmation, stable prefix results`, () => {
      const side = fixture.side === 'neutral' ? 'long' : fixture.side
      const isContinuation =
        fixture.id.includes('three-methods') ||
        fixture.id.includes('marubozu') ||
        fixture.side === 'neutral'
      const preceding = isContinuation ? side : side === 'long' ? 'short' : 'long'
      const high = Math.max(...fixture.rows.map((b) => b.high)),
        low = Math.min(...fixture.rows.map((b) => b.low)),
        last = fixture.rows.at(-1)!
      const confirm =
        fixture.id === 'inverted-hammer'
          ? bar(
              Math.max(last.open, last.close) + 0.2,
              105,
              Math.max(last.open, last.close) + 0.1,
              104
            )
          : side === 'long'
            ? bar(high + 0.2, high + 2, high + 0.1, high + 1)
            : bar(low - 0.2, low - 0.1, low - 2, low - 1)
      const rows = timed([...trendBars(preceding), ...fixture.rows, confirm]),
        engine = new BookPatternEngine()
      for (let n = 1; n <= rows.length; n++) {
        const prefix = rows.slice(0, n),
          live = engine.reconcile(prefix, TEST_CONTEXT),
          batch = analyzeBookGuide(prefix, TEST_CONTEXT)
        expect(live.events).toEqual(batch.events)
        expect(live.activePlan).toEqual(batch.activePlan)
        expect(live.observations).toEqual(batch.observations)
        expect(
          live.events.every(
            (e) =>
              e.confirmationTime! >= e.recognitionTime && e.confirmationTime! <= prefix.at(-1)!.time
          )
        ).toBe(true)
      }
    })
})
