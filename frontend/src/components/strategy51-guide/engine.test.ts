import { expect, it } from 'vitest'
import { Strategy51Engine } from './engine'
import { DEFAULT_STRATEGY51_SETTINGS as defaults } from './settings'
import type { StrategyBar, StrategyContext } from './types'
const start = Date.UTC(2026, 10, 2, 3, 45) / 1000
const rows = (): StrategyBar[] => [
  ...Array.from({ length: 20 }, (_, i) => ({
    time: start - 86400 + i * 300,
    open: 90,
    high: 91,
    low: 89,
    close: 90,
    volume: 100,
  })),
  { time: start, open: 110, high: 112, low: 109, close: 111, volume: 100 },
  { time: start + 300, open: 111, high: 114, low: 109, close: 112, volume: 100 },
  { time: start + 600, open: 109, high: 110, low: 106, close: 108, volume: 100 },
]
const context = (b: StrategyBar[]): StrategyContext => ({
  symbol: 'TEST',
  exchange: 'NSE',
  intervalSeconds: 300,
  now: b.at(-1)!.time + 300,
  observedAt: b.at(-1)!.time + 300,
  sourceReady: true,
  connected: true,
  marketOpen: false,
  chartType: 'standard',
  tickSize: 0.05,
})
const settings = { ...defaults, selected: '5.5' }
it('creates a frozen plan from the actual first-hour candle sequence', () => {
  const b = rows(),
    r = new Strategy51Engine().reconcile(b, context(b), settings)
  expect(r.rows).toHaveLength(51)
  expect(r.plan).toMatchObject({ strategyId: '5.5', side: 'short', entry: 108, status: 'active' })
  expect(r.plan!.stop).toBeGreaterThan(114)
  expect(r.events.at(-1)?.signalTime).toBe(start + 300)
})
it('never promotes a forming candle just because wall clock moves forward', () => {
  const b = rows(),
    c = context(b)
  c.observedAt = b.at(-1)!.time + 10
  c.now += 3600
  expect(new Strategy51Engine().reconcile(b, c, settings).plan).toBeUndefined()
})
it('keeps an initial plan frozen instead of recalculating entry/SL with each candle', () => {
  const b = rows(),
    e = new Strategy51Engine(),
    r = e.reconcile(b, context(b), settings)
  b.push({ time: start + 900, open: 108, high: 109, low: 106, close: 107, volume: 100 })
  const later = e.reconcile(b, context(b), settings)
  expect([later.plan?.entry, later.plan?.stop, later.plan?.target]).toEqual([
    r.plan?.entry,
    r.plan?.stop,
    r.plan?.target,
  ])
})
it('marks both-stop-and-target touches ambiguous without inventing an intrabar winner', () => {
  const b = rows(),
    e = new Strategy51Engine(),
    p = e.reconcile(b, context(b), settings).plan!
  b.push({
    time: start + 900,
    open: 108,
    high: p.stop + 1,
    low: p.target! - 1,
    close: 108,
    volume: 100,
  })
  const r = e.reconcile(b, context(b), settings)
  expect(r.lastPlan?.status).toBe('ambiguous')
  expect(r.plan).toBeUndefined()
})
it('rebuilds corrected history and never retains another chart identity or focus plan', () => {
  const b = rows(),
    e = new Strategy51Engine()
  expect(e.reconcile(b, context(b), settings).plan).toBeDefined()
  const changed = b.map((x) => ({ ...x }))
  changed.at(-1)!.close = 110
  expect(e.reconcile(changed, context(changed), settings).plan).toBeUndefined()
  expect(
    e.reconcile(b, { ...context(b), symbol: 'OTHER' }, { ...settings, selected: '3.3' }).plan
  ).toBeUndefined()
})
it('rejects duplicate/non-finite/repaired candles and unavailable source metadata', () => {
  for (const b of [
    [...rows(), rows().at(-1)!],
    rows().map((x, i) => (i === 5 ? { ...x, high: NaN } : x)),
    rows().map((x, i) => (i === 5 ? { ...x, repaired: true } : x)),
  ]) {
    const r = new Strategy51Engine().reconcile(b, context(b), settings)
    expect(r.readiness).toBe('unavailable')
    expect(r.plan).toBeUndefined()
  }
  expect(
    new Strategy51Engine().reconcile(rows(), { ...context(rows()), sourceReady: false }, settings)
      .plan
  ).toBeUndefined()
})
it('withholds current guidance on stale live source, while labelling closed-session references', () => {
  const b = rows(),
    c = context(b)
  expect(new Strategy51Engine().reconcile(b, c, settings).readiness).toBe('last-session')
  const r = new Strategy51Engine().reconcile(
    b,
    { ...c, now: c.now + 4000, marketOpen: true },
    settings
  )
  expect(r.readiness).toBe('unavailable')
  expect(r.plan).toBeUndefined()
})
it('does not backdate prior confirmed events when future candles are appended', () => {
  const b = rows(),
    e = new Strategy51Engine(),
    prefix = e.reconcile(b, context(b), settings).events
  b.push({ time: start + 900, open: 108, high: 109, low: 106, close: 107, volume: 100 })
  expect(
    e.reconcile(b, context(b), settings).events.filter((x) => x.time <= prefix.at(-1)!.time)
  ).toEqual(prefix)
})
it('uses fixed cash risk only after exact scoped product units are explicitly supplied', () => {
  const b = rows(),
    c = context(b),
    e = new Strategy51Engine(),
    s = {
      ...settings,
      equity: 10000,
      riskPercent: 1,
      instrumentScope: 'NSE:TEST',
      instrument: {
        kind: 'linear' as const,
        unitDefinition: 'underlying' as const,
        accountCurrency: 'INR',
        quoteCurrency: 'INR',
        quantityStep: 1,
        valuePerPriceUnit: 1,
        lotSize: 65,
      },
    }
  const r = e.reconcile(b, c, s)
  expect(r.plan?.sizing?.quantity).toBeGreaterThan(0)
  expect(r.plan?.sizing?.estimatedRiskCash).toBeLessThanOrEqual(100)
  expect(e.reconcile(b, { ...c, symbol: 'OTHER' }, s).plan?.sizing?.quantity).toBeUndefined()
  expect(e.reconcile(b, c, settings).plan?.sizing?.quantity).toBeUndefined()
})
it('rejects duplicate auxiliary hourly candles rather than treating their RSI as verified', () => {
  const b = rows(),
    c = context(b),
    h = Array.from({ length: 16 }, (_, i) => ({ ...b[0], time: c.observedAt - (16 - i) * 3600 }))
  h.at(-1)!.time = h.at(-2)!.time
  const r = new Strategy51Engine().reconcile(
    b,
    c,
    { ...defaults, selected: '2.6' },
    {
      higher: {
        symbol: c.symbol,
        exchange: c.exchange,
        intervalSeconds: 3600,
        observedAt: c.observedAt,
        bars: h,
      },
    }
  )
  expect(r.rows.find((r) => r.definition.id === '2.6')?.state).toBe('needs-data')
})

it('keeps all strategy detections when focus only selects the displayed plan', () => {
  const b = rows(),
    c = context(b),
    engine = new Strategy51Engine()
  const automatic = engine.reconcile(b, c, defaults)
  const focused = engine.reconcile(b, c, { ...defaults, selected: '3.3' })
  expect(automatic.events.some((e) => e.strategyId === '5.5')).toBe(true)
  expect(focused.events).toEqual(automatic.events)
  expect(focused.rows).toEqual(automatic.rows)
  expect(focused.plan).toBeUndefined()
  expect(engine.reconcile(b, c, settings).plan?.strategyId).toBe('5.5')
})
it('refreshes all51 at the next source-observed candle close while retaining a different plan focus', () => {
  const b = rows(),
    engine = new Strategy51Engine(),
    focused = { ...defaults, selected: '3.3' }
  const opened = b.at(-1)!.time,
    c = {
      ...context(b),
      marketOpen: true,
      quoteObservedAt: opened + 10,
      now: opened + 10,
      observedAt: opened + 10,
    }
  const forming = engine.reconcile(b, c, focused)
  expect(forming.rows).toHaveLength(51)
  expect(forming.events.some((e) => e.strategyId === '5.5')).toBe(false)
  const notObserved = engine.reconcile(
    b,
    { ...c, now: opened + 300, quoteObservedAt: opened + 300 },
    focused
  )
  expect(notObserved.events.some((e) => e.strategyId === '5.5')).toBe(false)
  const closed = engine.reconcile(
    b,
    { ...c, now: opened + 300, quoteObservedAt: opened + 300, observedAt: opened + 300 },
    focused
  )
  expect(closed.readiness).toBe('ready')
  expect(closed.completedAt).toBe(opened + 300)
  expect(closed.rows).toHaveLength(51)
  expect(closed.events.find((e) => e.strategyId === '5.5')?.time).toBe(opened + 300)
  expect(closed.plan).toBeUndefined()
})

it('identifies history and scheduled closure separately and carries instrument price precision', () => {
  const b = rows(),
    engine = new Strategy51Engine(),
    c = context(b)
  const closed = engine.reconcile(b, c, settings)
  expect(closed).toMatchObject({ viewMode: 'closed-session', tickSize: 0.05 })
  const replay = engine.reconcile(b, c, settings, { historical: true })
  expect(replay.viewMode).toBe('history')
  const live = engine.reconcile(b, { ...c, marketOpen: true }, settings)
  expect(live.viewMode).toBe('live')
})
