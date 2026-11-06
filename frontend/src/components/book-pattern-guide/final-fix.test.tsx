import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { analyzeBookGuide, BookPatternEngine, DEFAULT_BOOK_SETTINGS as S } from './engine'
import { bar, timed, trendBars, TEST_CONTEXT } from './fixtures'
import { BookPatternGuide } from './BookPatternGuide'
import { bookDrawingWorklist } from './BookPatternLayer'
const activeBars = () =>
  timed([...trendBars('short'), bar(100, 110, 99.9, 102), bar(102.5, 105, 102.3, 104)])
const props = {
  settings: S,
  context: TEST_CONTEXT,
  instrument: {},
  onSettingsChange: vi.fn(),
  onInstrumentChange: vi.fn(),
}
it('retains actual 104 references on source loss, blocks cached completion and consumes reconnect history', () => {
  const engine = new BookPatternEngine(),
    bars = activeBars(),
    end = bars.at(-1)!.time + 60
  const c = { ...TEST_CONTEXT, now: end, observedAt: end, quoteObservedAt: end }
  const forming = { ...bar(104, 120, 103, 118), time: end }
  const first = engine.reconcile([...bars, forming], c)
  expect(first.activePlan?.entry).toBe(104)
  const failed = engine.reconcile([...bars, forming], {
    ...c,
    sourceReady: false,
    observedAt: 0,
    now: end + 120,
  })
  expect(failed.readiness).toBe('unavailable')
  expect(failed.activePlan).toEqual(first.activePlan)
  expect(failed.events).toEqual(first.events)
  expect(failed.alerts).toEqual([])
  const restored = engine.reconcile([...bars, forming], {
    ...c,
    now: end + 120,
    quoteObservedAt: end + 120,
  })
  expect(restored.activePlan).toEqual(first.activePlan)
  expect(restored.alerts).toEqual([])
  // A late history catch-up is consumed even after an unchanged reconnect.
  const caught = engine.reconcile([...bars, forming], {
    ...c,
    now: end + 180,
    observedAt: end + 180,
    quoteObservedAt: end + 180,
  })
  expect(caught.lastTerminalPlan?.status).toBe('target-touched')
  expect(caught.alerts).toEqual([])
  const changed = engine.reconcile([], { ...c, symbol: 'OTHER', sourceReady: false, observedAt: 0 })
  expect(changed.activePlan).toBeUndefined()
})
for (const family of ['doji', 'bull-marubozu'])
  it(`uses stable neutral/local visibility for confirmed ${family}`, () => {
    const rows =
      family === 'doji'
        ? [bar(100, 105, 95, 100.5), bar(105.1, 107, 105, 106)]
        : [bar(100, 110, 100, 110), bar(110.1, 112, 110, 111)]
    const bars = timed([...trendBars('long'), ...rows]),
      result = analyzeBookGuide(bars, TEST_CONTEXT)
    const e = result.events.find((e) => e.patternId === family)!
    expect(e?.side).toBe('long')
    expect(e.rank).toBe(4)
    for (const fullHistory of [false, true])
      for (const showPending of [false, true]) {
        expect(
          bookDrawingWorklist(result, bars, { ...S, fullHistory, showPending }).some(
            (e) => e.rank === 4
          )
        ).toBe(false)
        expect(
          bookDrawingWorklist(result, bars, {
            ...S,
            fullHistory,
            showPending,
            showNeutral: true,
          }).some((item) => item.id === e.id)
        ).toBe(true)
      }
    const noPlan = { ...result, events: [e], pendingEvents: [], activePlan: undefined }
    const view = render(<BookPatternGuide {...props} result={noPlan} />)
    expect(
      within(screen.getByLabelText('Book compact summary')).queryByText(new RegExp(e.name))
    ).not.toBeInTheDocument()
    view.rerender(
      <BookPatternGuide {...props} settings={{ ...S, showNeutral: true }} result={noPlan} />
    )
    expect(
      within(screen.getByLabelText('Book compact summary')).getByText(new RegExp(e.name))
    ).toBeInTheDocument()
  })
it('defaults to a slim summary with visible selected plan, next condition and sizing; Details exposes full guide', () => {
  const result = analyzeBookGuide(activeBars(), TEST_CONTEXT)
  render(<BookPatternGuide {...props} result={result} />)
  const summary = screen.getByLabelText('Book compact summary')
  expect(within(summary).getByText(/Inverted hammer/)).toBeVisible()
  expect(
    within(summary).getByText(new RegExp(`Trend ${result.indicators.trend} · Next`))
  ).toBeVisible()
  expect(within(summary).getByText(/Entry 104/)).toBeVisible()
  expect(within(summary).getByText(/SL 99.86/)).toBeVisible()
  expect(within(summary).getByText(/Target/)).toBeVisible()
  expect(within(summary).getByText(/3R/)).toBeVisible()
  expect(within(summary).getByText(/Sizing unavailable/)).toBeVisible()
  const details = screen.getByText('Details').closest('details')!
  expect(details.open).toBe(false)
  expect(screen.getByText('Invalidation')).not.toBeVisible()
  fireEvent.click(screen.getByText('Details'))
  expect(details.open).toBe(true)
  expect(screen.getByText('Invalidation')).toBeVisible()
  expect(screen.getByText('Display, filters & risk settings')).toBeVisible()
})
it('keeps selected local-plan explanation and references even with its ordinary label hidden', () => {
  const bars = timed([...trendBars('long'), bar(100, 110, 100, 110), bar(110.1, 112, 110, 111)])
  const result = analyzeBookGuide(bars, TEST_CONTEXT)
  expect(result.activePlan?.eventId).toBe(
    result.events.find((e) => e.patternId === 'bull-marubozu')?.id
  )
  render(<BookPatternGuide {...props} result={result} />)
  expect(within(screen.getByLabelText('Book compact summary')).getByText(/marubozu/i)).toBeVisible()
  expect(bookDrawingWorklist(result, bars, S)).toEqual([])
  fireEvent.click(screen.getByText('Details'))
  expect(screen.getByText('Invalidation')).toBeVisible()
  expect(screen.getByLabelText('Frozen book plan price references')).toBeVisible()
})
