import { expect, it } from 'vitest'
import { STRATEGIES_51 } from './catalog'
import { buildFrames } from './indicators'
import { assessStrategy } from './rules'
import { Strategy51Engine } from './engine'
import { DEFAULT_STRATEGY51_SETTINGS as defaults } from './settings'
import type { EvaluationInput, Frame, StrategyBar, StrategyContext, StrategyExtras } from './types'
const start = Date.UTC(2026, 10, 2, 3, 45) / 1000
const bar = (
  time: number,
  open = 100,
  high = 101,
  low = 99,
  close = 100,
  volume = 100
): StrategyBar => ({ time, open, high, low, close, volume })
const context = (bars: StrategyBar[], seconds = 300): StrategyContext => ({
  symbol: 'NIFTY',
  exchange: 'NSE_INDEX',
  intervalSeconds: seconds,
  now: bars.at(-1)!.time + seconds,
  observedAt: bars.at(-1)!.time + seconds,
  sourceReady: true,
  connected: true,
  marketOpen: false,
  chartType: 'standard',
  tickSize: 0.05,
})
const a = (frames: Frame[], seconds = 300): EvaluationInput => ({
  frames,
  index: frames.length - 1,
  context: context(
    frames.map((f) => f.bar),
    seconds
  ),
  settings: defaults,
  extras: {},
})
const rule = (id: string, input: EvaluationInput) =>
  assessStrategy(STRATEGIES_51.find((d) => d.id === id)!, input)
it('confirms VCP on the current breakout close, without waiting another candle or backdating it', () => {
  const f = buildFrames(
      Array.from({ length: 80 }, (_, i) => bar(start + i * 300)),
      300
    ),
    i = f.length - 1
  const lows = [
      { index: 30, knownAt: 33, price: 80, kind: 'low' as const },
      { index: 50, knownAt: 53, price: 90, kind: 'low' as const },
      { index: 65, knownAt: 68, price: 95, kind: 'low' as const },
    ],
    highs = [
      { index: 20, knownAt: 23, price: 100, kind: 'high' as const },
      { index: 44, knownAt: 47, price: 100, kind: 'high' as const },
      { index: 62, knownAt: 65, price: 100, kind: 'high' as const },
    ]
  for (const z of f) {
    z.lows = lows.filter((p) => p.knownAt <= z.index)
    z.highs = highs.filter((p) => p.knownAt <= z.index)
    z.volumeMean = 100
    z.atr = 1
    z.bar.volume = z.index < 40 ? 100 : z.index < 60 ? 70 : 30
  }
  f[i - 1].bar = bar(f[i - 1].bar.time, 98, 100, 97, 99, 30)
  f[i].bar = bar(f[i].bar.time, 99, 104, 98, 103, 200)
  const r = rule('7.6', a(f))
  expect(r.candidate).toMatchObject({ signalIndex: i, index: i, entry: 103, side: 'long' })
  expect(r.candidate!.stop).toBeLessThan(95)
  expect(r.candidate!.segments).toHaveLength(5)
  expect(r.candidate!.segments![0].from.time).toBe(f[20].bar.time)
  expect(r.candidate!.segments![0].to.time).toBe(f[30].bar.time)
  expect(rule('7.6', a(f.slice(0, -1))).candidate).toBeUndefined()
})
it('does not call a truncated prior month a completed monthly pivot anchor', () => {
  const bars = Array.from({ length: 22 }, (_, i) =>
      bar(Date.UTC(2026, 9, 10 + i) / 1000, 100, 101, 99, 100)
    ),
    next = bar(Date.UTC(2026, 10, 2) / 1000, 100, 104, 99.9, 103),
    confirmed = bar(Date.UTC(2026, 10, 3) / 1000, 103, 106, 102, 105)
  const f = buildFrames([...bars, next, confirmed], 86400)
  f.at(-2)!.trend = 'bull'
  f.at(-2)!.atr = 1
  expect(rule('4.1', a(f, 86400))).toMatchObject({ state: 'needs-data', candidate: undefined })
})
it('requires an actual upward rally before the long-only triangle, rather than any volatile range', () => {
  const f = buildFrames(
      Array.from({ length: 80 }, (_, i) => bar(start + i * 86400, 100, 101, 99, 100, 50)),
      86400
    ),
    i = f.length - 1
  const q = f[i - 1]
  q.highs = [
    { index: 60, knownAt: 63, price: 120, kind: 'high' },
    { index: 70, knownAt: 73, price: 118, kind: 'high' },
  ]
  q.lows = [
    { index: 65, knownAt: 68, price: 100, kind: 'low' },
    { index: 73, knownAt: 76, price: 104, kind: 'low' },
  ]
  q.volumeMean = 100
  q.atr = 1
  for (let j = 45; j < 60; j++)
    f[j].bar = bar(
      f[j].bar.time,
      130 - (j - 45) * 2,
      132 - (j - 45) * 2,
      100 - (j - 45),
      120 - (j - 45) * 2,
      50
    )
  f[60].bar = bar(f[60].bar.time, 119, 121, 118, 120, 50)
  f[70].bar = bar(f[70].bar.time, 117, 119, 116, 118, 50)
  f[65].bar = bar(f[65].bar.time, 101, 102, 99, 100, 50)
  f[73].bar = bar(f[73].bar.time, 105, 106, 103, 104, 50)
  q.bar = bar(q.bar.time, 112, 121, 110, 120, 200)
  f[i].bar = bar(f[i].bar.time, 120, 124, 119, 123, 200)
  expect(rule('1.4', a(f, 86400)).candidate).toBeUndefined()
  f[59].bar = bar(f[59].bar.time, 159, 162, 158, 160, 50)
  expect(rule('1.4', a(f, 86400)).candidate?.side).toBe('long')
})
it('does not invent an Indian opening hour for a continuously traded chart', () => {
  const f = buildFrames(
      Array.from({ length: 12 }, (_, i) => bar(start + i * 300)),
      300
    ),
    input = a(f)
  input.context.exchange = 'DELTA'
  for (const z of f) z.ema[5] = 90
  f.at(-2)!.bar = bar(f.at(-2)!.bar.time, 100, 103, 99, 101)
  f.at(-1)!.bar = bar(f.at(-1)!.bar.time, 99, 100, 95, 96)
  expect(rule('5.5', input)).toMatchObject({ state: 'needs-context', candidate: undefined })
})
it('requires complete lower-high AND lower-low trend evidence before a short two-leg pullback', () => {
  const f = buildFrames(
      Array.from({ length: 80 }, (_, i) => bar(start + i * 300)),
      300
    ),
    i = f.length - 1
  f[i - 1].highs = [
    { kind: 'high', index: 10, knownAt: 13, price: 120 },
    { kind: 'high', index: 20, knownAt: 23, price: 110 },
    { kind: 'high', index: 40, knownAt: 43, price: 105 },
    { kind: 'high', index: 65, knownAt: 68, price: 103 },
  ]
  f[i - 1].lows = [
    { kind: 'low', index: 15, knownAt: 18, price: 80 },
    { kind: 'low', index: 30, knownAt: 33, price: 85 },
    { kind: 'low', index: 55, knownAt: 58, price: 90 },
  ]
  f[i - 1].bar = bar(f[i - 1].bar.time, 100, 103, 98, 99)
  f[i].bar = bar(f[i].bar.time, 99, 100, 95, 96)
  expect(rule('7.7', a(f)).candidate).toBeUndefined()
})
it('withholds Double RSI when the hourly request has not observed the confirming five-minute close', () => {
  const f = buildFrames(
      Array.from({ length: 20 }, (_, i) => bar(start + i * 300)),
      300
    ),
    input = a(f),
    i = f.length - 1
  f[i - 1].rsi = 20
  f[i - 1].bar = bar(f[i - 1].bar.time, 99, 102, 98, 101)
  f[i].bar = bar(f[i].bar.time, 101, 104, 100, 103)
  input.extras.higher = Object.assign(
    {
      symbol: input.context.symbol,
      exchange: input.context.exchange,
      intervalSeconds: 3600,
      observedAt: input.context.observedAt - 600,
      bars: Array.from({ length: 15 }, (_, j) => bar(start - (14 - j) * 3600)),
    },
    { rsi: Array(15).fill(60) }
  )
  expect(rule('2.6', input)).toMatchObject({ state: 'needs-data', candidate: undefined })
  input.extras.higher.observedAt = input.context.observedAt
  expect(rule('2.6', input).candidate?.side).toBe('long')
})
const optionContext = (bars: StrategyBar[]): StrategyContext => ({
  ...context(bars, 60),
  symbol: 'NIFTY09NOV2624500CE',
  exchange: 'NFO',
})
const optionExtras = (time: number, kind: 'near40' | 'chosen-call'): StrategyExtras => ({
  option: {
    symbol: 'NIFTY09NOV2624500CE',
    exchange: 'NFO',
    underlying: 'NIFTY',
    expiry: '09NOV26',
    expiryTime: Date.UTC(2026, 10, 9, 10, 0) / 1000,
    strike: 24500,
    optionType: 'CE',
    selection: {
      time,
      kind,
      source: 'supplied',
      description: 'Dated source contract selection',
      exitAt: kind === 'chosen-call' ? start + 86400 + 15 * 60 : undefined,
    },
  },
})
it('never opens a fresh premium reference at or after its source time exit', () => {
  const base = start + 15 * 60,
    f = buildFrames(
      Array.from({ length: 23 }, (_, i) => bar(base + i * 900)),
      900
    ),
    input = a(f, 900)
  f.at(-1)!.bar = bar(f.at(-1)!.bar.time, 100, 117, 99, 116)
  input.context = { ...input.context, symbol: 'NIFTY09NOV2624500CE', exchange: 'NFO' }
  input.extras.option = {
    ...optionExtras(base, 'near40').option!,
    selection: {
      time: base,
      kind: 'atm',
      source: 'verified-history',
      description: 'Dated ATM at 09:30',
    },
  }
  expect(rule('6.6', input).candidate).toBeUndefined()
})
it('moves the 6.2 stop to entry only after a completed premium candle reaches half entry', () => {
  const bars = [
      bar(start - 60, 40, 41, 39, 40),
      bar(start, 40, 41, 39, 40),
      bar(start + 60, 40, 41, 39, 40),
    ],
    s = { ...defaults, selected: '6.2', localTargets: false },
    extras = optionExtras(start + 60, 'near40'),
    engine = new Strategy51Engine()
  expect(engine.reconcile(bars, optionContext(bars), s, extras).plan).toMatchObject({
    entry: 40,
    stop: 80,
  })
  bars.push(bar(start + 120, 40, 42, 19, 20))
  const r = engine.reconcile(bars, optionContext(bars), s, extras)
  expect(r.plan?.currentStop).toBe(40)
  expect(r.plan?.status).toBe('active')
  bars.push(bar(start + 180, 20, 41, 19, 39))
  expect(engine.reconcile(bars, optionContext(bars), s, extras).lastPlan?.status).toBe(
    'stop-touched'
  )
})
it('keeps the source BTST overnight duration and exits at the next session 09:30, rather than local 50-bar expiry', () => {
  const base = start + 105 * 60,
    bars = [
      bar(base - 120, 100, 101, 99, 100),
      bar(base - 60, 100, 101, 99, 100),
      bar(base, 100, 101, 99, 100),
      bar(base + 60, 100, 122, 99, 121),
    ]
  const extras = optionExtras(base, 'chosen-call'),
    s = { ...defaults, selected: '6.10', localTargets: false, planExpiryBars: 50 },
    engine = new Strategy51Engine()
  for (let i = 2; i <= 60; i++) bars.push(bar(base + i * 60, 122, 123, 121, 122))
  expect(engine.reconcile(bars, optionContext(bars), s, extras).plan?.status).toBe('active')
  bars.push(bar(start + 86400 + 15 * 60, 122, 123, 121, 122))
  expect(engine.reconcile(bars, optionContext(bars), s, extras).lastPlan?.status).toBe('time-exit')
})
