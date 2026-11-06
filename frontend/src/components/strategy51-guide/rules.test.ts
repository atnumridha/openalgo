import { expect, it } from 'vitest'
import { STRATEGIES_51 } from './catalog'
import { buildFrames } from './indicators'
import { assessStrategy } from './rules'
import { DEFAULT_STRATEGY51_SETTINGS } from './settings'
import type { EvaluationInput, StrategyContext } from './types'
const t = Date.UTC(2026, 10, 2, 3, 45) / 1000
const ctx: StrategyContext = {
  symbol: 'NIFTY',
  exchange: 'NSE_INDEX',
  intervalSeconds: 300,
  now: t + 86400,
  observedAt: t + 86400,
  sourceReady: true,
  connected: true,
  marketOpen: false,
  chartType: 'standard',
  tickSize: 0.05,
}
const frames = () =>
  buildFrames(
    Array.from({ length: 80 }, (_, i) => ({
      time: t + i * 300,
      open: 100,
      high: 101,
      low: 99,
      close: 100,
      volume: 100,
    })),
    300
  )
const input = (f = frames(), c = ctx): EvaluationInput => ({
  frames: f,
  index: f.length - 1,
  context: c,
  settings: DEFAULT_STRATEGY51_SETTINGS,
  extras: {},
})
const rule = (id: string, a: EvaluationInput) =>
  assessStrategy(STRATEGIES_51.find((s) => s.id === id)!, a)
it('evaluates every strategy explicitly and returns a useful next condition', () => {
  for (const s of STRATEGIES_51) {
    const r = assessStrategy(s, input())
    expect(r.definition.id).toBe(s.id)
    expect(r.next.length).toBeGreaterThan(5)
    expect(['confirmed', 'waiting', 'timeframe', 'needs-data', 'needs-context']).toContain(r.state)
  }
})
it('requires the exact5m/hourly RSI combination, not two RSI periods', () => {
  expect(rule('2.6', input()).state).toBe('needs-data')
  expect(rule('2.6', input(frames(), { ...ctx, intervalSeconds: 900 })).state).toBe('timeframe')
})
it('requires an outside CLOSE before the VWAP reversal, not a wick touch', () => {
  const f = frames(),
    i = f.length - 1
  Object.assign(f[i - 2], {
    vwap: 100,
    vwapSD: 2,
    bar: { ...f[i - 2].bar, open: 101, high: 102, low: 94, close: 99 },
  })
  Object.assign(f[i - 1], {
    vwap: 100,
    vwapSD: 2,
    bar: { ...f[i - 1].bar, open: 96, high: 98, low: 95, close: 97 },
  })
  f[i].bar = { ...f[i].bar, open: 98, high: 100, low: 97, close: 99 }
  expect(rule('2.3', input(f)).candidate).toBeUndefined()
  f[i - 2].bar.close = 95
  expect(rule('2.3', input(f)).candidate).toMatchObject({
    side: 'long',
    signalIndex: i - 1,
    stopMethod: expect.stringMatching(/reversal/i),
  })
})
it('uses SMA50 and a causally known4L4R fractal, not a3L3R substitute', () => {
  const f = frames(),
    i = f.length - 1
  Object.assign(f[i - 1], {
    sma: { 50: 99 },
    fractalHighs: [],
    fractalLows: [{ index: 50, knownAt: 54, price: 90, kind: 'low' }],
    highs: [{ index: 65, knownAt: 68, price: 102, kind: 'high' }],
  })
  f[i - 1].bar = { ...f[i - 1].bar, open: 101, high: 104, low: 100, close: 103 }
  f[i].bar = { ...f[i].bar, open: 103, high: 106, low: 102, close: 105 }
  expect(rule('3.4', input(f)).candidate).toBeUndefined()
  f[i - 1].fractalHighs = [{ index: 65, knownAt: 69, price: 102, kind: 'high' }]
  expect(rule('3.4', input(f)).candidate?.side).toBe('long')
  f[i - 2].bar = { ...f[i - 2].bar, open: 103, high: 104, low: 102, close: 103 }
  expect(rule('3.4', input(f)).candidate).toBeUndefined()
})
it('does not relabel an already-broken Dow swing on every trend candle', () => {
  const f = frames(),
    i = f.length - 1
  f[i - 2].highs = [
    { index: 40, knownAt: 43, price: 100, kind: 'high' },
    { index: 60, knownAt: 63, price: 102, kind: 'high' },
  ]
  f[i - 2].lows = [
    { index: 45, knownAt: 48, price: 95, kind: 'low' },
    { index: 65, knownAt: 68, price: 96, kind: 'low' },
  ]
  f[i - 1].lows = f[i - 2].lows
  f[i - 1].rsi = 60
  f[i - 2].bar = { ...f[i - 2].bar, open: 101, high: 102, low: 100, close: 101 }
  f[i - 1].bar = { ...f[i - 1].bar, open: 101, high: 105, low: 100, close: 104 }
  f[i].bar = { ...f[i].bar, open: 104, high: 107, low: 103, close: 106 }
  expect(rule('3.1', input(f)).candidate?.side).toBe('long')
  f[i - 2].bar = { ...f[i - 2].bar, open: 102, high: 104, low: 101, close: 103 }
  expect(rule('3.1', input(f)).candidate).toBeUndefined()
})
it('does not erase later first-hour EMA setups when the second candle touched the EMA', () => {
  const f = buildFrames(
      Array.from({ length: 12 }, (_, i) => ({
        time: t + i * 300,
        open: 100,
        high: 102,
        low: 98,
        close: 100,
        volume: 100,
      })),
      300
    ),
    i = 5
  for (const x of f) x.ema[5] = 90
  f[1].bar.low = 89
  f[4].bar = { ...f[4].bar, open: 100, high: 103, low: 99, close: 101 }
  f[5].bar = { ...f[5].bar, open: 99, high: 100, low: 95, close: 96 }
  expect(rule('5.5', { ...input(f), index: i }).candidate).toMatchObject({
    side: 'short',
    signalIndex: 4,
  })
})
it('never treats an underlying rise as an option-premium momentum entry', () => {
  expect(rule('6.6', input()).state).toBe('needs-data')
  const a = input()
  a.context = { ...ctx, symbol: 'NIFTY09NOV2624500CE', exchange: 'NFO' }
  expect(rule('6.3', a).next).toMatch(/OI/i)
  expect(rule('6.6', a).candidate).toBeUndefined()
})
it('does not invent repo changes, Elliott waves, Gann scaling or sector weights', () => {
  for (const id of ['3.3', '3.7', '4.3', '7.5']) expect(rule(id, input()).candidate).toBeUndefined()
})
it('preserves unsupported long-only source directions and no-stop macro rules', () => {
  const f = frames()
  for (const x of f) {
    x.trend = 'bear'
    x.rsi = 20
  }
  for (const id of ['1.3', '1.4', '7.2', '7.4', '7.6'])
    expect(rule(id, input(f)).candidate?.side).not.toBe('short')
  expect(STRATEGIES_51.find((s) => s.id === '7.5')?.stop).toMatch(/no fixed stop/i)
})
it('does not let a future manual context qualify an earlier chart', () => {
  const a = input()
  a.extras.supplied = [
    {
      strategyId: '3.3',
      kind: 'elliott',
      symbol: ctx.symbol,
      exchange: ctx.exchange,
      intervalSeconds: 300,
      asOf: ctx.now + 86400,
      side: 'long',
      entry: 100,
      stop: 90,
      target: 130,
      description: 'future waves',
    },
  ]
  expect(rule('3.3', a).candidate).toBeUndefined()
})
