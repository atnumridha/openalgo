import { expect, it } from 'vitest'
import { analyzeBookGuide, BookPatternEngine, DEFAULT_BOOK_SETTINGS as S } from './engine'
import { bookTrendWorklist, bookDrawingWorklist } from './BookPatternLayer'
import { bar, timed, trendBars, TEST_CONTEXT } from './fixtures'
const rows = () =>
  timed(
    Array.from({ length: 28 }, (_, i) =>
      bar(
        100,
        ({ 8: 110, 16: 108, 24: 106 } as Record<number, number>)[i] ?? 101,
        ({ 4: 90, 12: 92, 20: 94 } as Record<number, number>)[i] ?? 99,
        100
      )
    )
  )
it('shows two causal context trends without a breakout and projects only to the received bar', () => {
  const bars = rows(),
    r = analyzeBookGuide(bars, TEST_CONTEXT)
  expect(S.showTrendLines).toBe(true)
  expect(r.activePlan).toBeUndefined()
  expect(r.trendLines).toHaveLength(2)
  expect(r.trendLines?.find((l) => l.role === 'Support trend')?.to).toMatchObject({
    index: 27,
    time: bars[27].time,
    price: 95.75,
  })
  expect(r.trendLines?.find((l) => l.role === 'Resistance trend')?.to).toMatchObject({
    index: 27,
    time: bars[27].time,
    price: 105.25,
  })
  const prior = analyzeBookGuide(bars.slice(0, 27), TEST_CONTEXT)
  expect(prior.trendLines?.find((l) => l.role === 'Resistance trend')?.to.recognitionTime).toBe(
    bars[19].time
  )
  const c = { ...TEST_CONTEXT, now: bars[27].time + 60, observedAt: bars[27].time + 60 }
  const engine = new BookPatternEngine(),
    first = engine.reconcile(bars, c)
  const forming = { ...bar(100, 101, 99, 100), time: bars[27].time + 60 }
  const next = engine.reconcile([...bars, forming], { ...c, now: c.now + 20 })
  expect(next.trendLines?.every((l) => l.to.time === forming.time && l.to.index === 28)).toBe(true)
  expect(next.trendLines?.map((l) => l.from)).toEqual(first.trendLines?.map((l) => l.from))
  expect(next.alerts).toEqual([])
  const replay = analyzeBookGuide([...bars, forming], { ...c, now: bars[26].time + 30 })
  expect(replay.trendLines?.every((line) => line.to.time <= bars[26].time)).toBe(true)
})
it('context visibility is independent of pattern history and changes neither events nor plans', () => {
  const bars = rows(),
    r = analyzeBookGuide(bars, TEST_CONTEXT),
    off = analyzeBookGuide(bars, TEST_CONTEXT, { showTrendLines: false })
  expect(off.events).toEqual(r.events)
  expect(off.activePlan).toEqual(r.activePlan)
  expect(off.alerts).toEqual(r.alerts)
  expect(bookTrendWorklist(r, S)).toHaveLength(2)
  expect(bookTrendWorklist(r, { ...S, showTrendLines: false })).toEqual([])
  expect(
    bookTrendWorklist(r, { ...S, showPending: false, fullHistory: false, showNeutral: false })
  ).toHaveLength(2)
  expect(bookDrawingWorklist(r, bars, S)).toEqual(
    bookDrawingWorklist(r, bars, { ...S, showTrendLines: false })
  )
  expect(bookTrendWorklist(r, { ...S, maxLines: 1 })).toHaveLength(1)
  const active = analyzeBookGuide(
    timed([...trendBars('short'), bar(100, 110, 99.9, 102), bar(102.5, 105, 102.3, 104)]),
    TEST_CONTEXT
  ).activePlan
  expect(active?.entry).toBe(104)
  expect(bookTrendWorklist({ ...r, activePlan: active }, { ...S, maxLines: 3 })).toHaveLength(0)
  expect(bookTrendWorklist({ ...r, activePlan: active }, { ...S, maxLines: 4 })).toHaveLength(1)
})

it('toggling only context lines preserves fresh alert delivery and selected plan', () => {
  const bars = timed([...trendBars('short'), bar(100, 110, 99.9, 102), bar(102.5, 105, 102.3, 104)])
  const engines = [new BookPatternEngine(), new BookPatternEngine()]
  const c = (i: number) => ({
    ...TEST_CONTEXT,
    now: bars[i].time + 60,
    observedAt: bars[i].time + 60,
    quoteObservedAt: bars[i].time + 60,
  })
  for (const e of engines) e.reconcile(bars.slice(0, 71), c(70))
  const a = engines[0].reconcile(bars, c(71)),
    b = engines[1].reconcile(bars, c(71), { showTrendLines: false })
  expect(a.alerts.length).toBeGreaterThan(0)
  expect(b.alerts).toEqual(a.alerts)
  expect(b.activePlan).toEqual(a.activePlan)
})
