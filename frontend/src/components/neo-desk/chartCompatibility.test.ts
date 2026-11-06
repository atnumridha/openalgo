import { analyzeCandles, detectPattern } from '../chart-toolkit/candleProbability'
import { calculateBBChikou } from '../chart-toolkit/bbChikou'
import { expect, it } from 'vitest'
import { NineIndicatorEngine } from '../chart-toolkit/nineIndicators'
import { ToolkitEngine, closeTime, type Bar } from '../chart-toolkit/model'
import { resolveIndicatorChart, indicatorAction } from '../chart-toolkit/indicatorChartContext'
import { calculateEntryPlan, type PlanSession } from './chartTradePlan'
import { compute } from './piyushResearchEngine.js'
import { computeStudies } from './tradingViewStudies'
const equity = { start: 555, end: 930, offset: 19800 },
  derivative = { ...equity, end: 940 },
  commodity = { start: 540, end: 1435, offset: 19800 },
  currency = { start: 540, end: 1020, offset: 19800 }
const profiles = [
  { symbol: 'NIFTY', exchange: 'NSE_INDEX', tick: 0.01, scale: 200, session: equity },
  { symbol: 'BANKNIFTY', exchange: 'NSE_INDEX', tick: 0.01, scale: 400, session: equity },
  { symbol: 'SENSEX', exchange: 'BSE_INDEX', tick: 0.01, scale: 500, session: equity },
  { symbol: 'RELIANCE', exchange: 'NSE', tick: 0.01, scale: 20, session: equity },
  { symbol: 'TCS', exchange: 'NSE', tick: 0.05, scale: 30, session: equity },
  { symbol: 'RELIANCE24NOV26FUT', exchange: 'NFO', tick: 0.05, scale: 20, session: derivative },
  ...['CE', 'PE'].map((side) => ({
    symbol: `NIFTY03NOV2623000${side}`,
    exchange: 'NFO',
    tick: 0.05,
    scale: 1,
    session: derivative,
  })),
  ...['CE', 'PE'].map((side) => ({
    symbol: `SENSEX05NOV2675000${side}`,
    exchange: 'BFO',
    tick: 0.05,
    scale: 1,
    session: derivative,
  })),
  ...['CE', 'PE'].map((side) => ({
    symbol: `RELIANCE24NOV262500${side}`,
    exchange: 'NFO',
    tick: 0.05,
    scale: 1,
    session: derivative,
  })),
  { symbol: 'GOLD30NOV26FUT', exchange: 'MCX', tick: 1, scale: 500, session: commodity },
  { symbol: 'GOLD30NOV26100000PE', exchange: 'MCX', tick: 0.5, scale: 10, session: commodity },
  { symbol: 'USDINR30NOV26FUT', exchange: 'CDS', tick: 0.0025, scale: 1, session: currency },
  { symbol: 'BTCUSD', exchange: 'DELTA', tick: 0.5, scale: 500, session: undefined },
  { symbol: 'ETHUSD', exchange: 'DELTA', tick: 0.05, scale: 20, session: undefined },
]
const frames = [
  ['1m', 60],
  ['3m', 180],
  ['5m', 300],
  ['15m', 900],
  ['30m', 1800],
  ['1h', 3600],
  ['1d', 86400],
] as const
function times(count: number, seconds: number, session?: PlanSession) {
  const out: number[] = []
  let day = Date.UTC(2026, 8, 1) / 1000,
    at = 0
  while (out.length < count) {
    if (!session || ![0, 6].includes(new Date(day * 1000).getUTCDay())) {
      const start = day - (session?.offset ?? 0) + (session?.start ?? 0) * 60,
        end = day - (session?.offset ?? 0) + (session?.end ?? 1440) * 60
      // Daily broker history carries a UTC date stamp, rather than the session open.
      if (seconds >= 86400) out.push(day)
      else for (at = start; at < end && out.length < count; at += seconds) out.push(at)
    }
    day += 86400
  }
  return out
}
const barsFor = (values: number[], seconds: number, p: (typeof profiles)[number]): Bar[] => {
  const stamps = times(values.length, seconds, p.session)
  return values.map((v, i) => {
    const open = values[Math.max(0, i - 1)] * p.scale,
      close = v * p.scale
    return {
      time: stamps[i],
      open,
      close,
      high: Math.max(open, close) + p.scale,
      low: Math.min(open, close) - p.scale,
      volume: 100 + (i % 7),
    }
  })
}
const reversal = Array.from({ length: 120 }, (_, i) =>
  i < 35 ? 150 - i : i < 75 ? 115 + (i - 35) * 2 : 195 - (i - 75) * 2
)
for (const p of profiles) {
  it(`${p.symbol}: every price-indicator rule emits both directions and maps the selected contract correctly`, () => {
    const source = barsFor(reversal, 60, p),
      result = new NineIndicatorEngine().update(source, {
        seconds: 60,
        asOf: source.at(-1)!.time + 60,
        continuous: p.exchange === 'DELTA',
        session: p.session,
      })
    for (const key of ['rsi', 'imi', 'mfi', 'macd'])
      for (const side of ['CALL', 'PUT'])
        expect(result.events.some((e) => e.key === key && e.side === side)).toBe(true)
    for (const [key, values] of [
      ['bb', [...Array(20).fill(100), 150, 160, 50]],
      ['ma', [...Array(50).fill(100), 110, 111, 90, 89]],
    ] as const) {
      const bars = barsFor([...values], 60, p),
        r = new NineIndicatorEngine().update(bars, {
          seconds: 60,
          asOf: bars.at(-1)!.time + 60,
          continuous: p.exchange === 'DELTA',
          session: p.session,
        })
      expect(r.events.filter((e) => e.key === key).map((e) => e.side)).toEqual(['CALL', 'PUT'])
    }
    const context = resolveIndicatorChart(p.symbol, p.exchange)
    for (const side of ['CALL', 'PUT'] as const) {
      const action = indicatorAction(side, context, 'premium', 'macd')
      expect(action.side).toBe(side)
      if (context.kind === 'option')
        expect(action.label).toBe(`${side === 'CALL' ? 'BUY' : 'AVOID'} ${context.optionSide}`)
      if (p.exchange === 'DELTA') expect(action.label).toBe(side === 'CALL' ? 'LONG' : 'SHORT')
    }
  })

  it(`${p.symbol}: combined RSI/MACD and BB setups preserve both price directions and option risk geometry`, () => {
    const wave = barsFor(
      Array.from({ length: 220 }, (_, i) => 100 + 10 * Math.sin(i / 8) + i / 100),
      60,
      p
    )
    const result = new ToolkitEngine().update(wave, {
      seconds: 60,
      asOf: wave.at(-1)!.time + 60,
      continuous: p.exchange === 'DELTA',
      session: p.session,
    })
    expect(result.allSignals.some((s) => s.side === 'BULL')).toBe(true)
    expect(result.allSignals.some((s) => s.side === 'BEAR')).toBe(true)
    for (const bull of [true, false]) {
      const values = [
        ...Array.from({ length: 60 }, (_, i) => (i % 2 ? 101 : 99)),
        bull ? 103 : 97,
        bull ? 104 : 96,
      ]
      const bars = barsFor(values, 60, p).map((b) => ({
        ...b,
        open: b.close,
        high: b.close + 0.1 * p.scale,
        low: b.close - 0.1 * p.scale,
      }))
      const option = /(CE|PE)$/.test(p.symbol)
      const r = calculateBBChikou(bars, {
        seconds: 60,
        asOf: bars.at(-1)!.time + 60,
        continuous: p.exchange === 'DELTA',
        session: p.session,
        tickSize: p.tick,
        reward: 2,
        longOnly: option,
      })
      expect(r.signals.at(-1)?.side).toBe(bull ? 'BULL' : 'BEAR')
      if (option && !bull) expect(r.latest).toBeNull()
      else {
        expect(r.latest).not.toBeNull()
        expect(Math.abs(r.latest!.target - r.latest!.entry)).toBeCloseTo(
          2 * Math.abs(r.latest!.entry - r.latest!.stop),
          6
        )
      }
    }
  })
  for (const [interval, seconds] of frames)
    it(`${p.symbol} ${interval}: values, prefix causality and tick-aligned long/short 2R plans`, () => {
      const source = barsFor(reversal, seconds, p),
        asOf = closeTime(source.at(-1)!, seconds, !!p.session, p.session),
        opts = { seconds, asOf, continuous: p.exchange === 'DELTA', session: p.session }
      const engine = new NineIndicatorEngine(),
        result = engine.update(source, opts)
      expect(result.states).toHaveLength(9)
      for (const key of ['rsi', 'bb', 'imi', 'mfi', 'macd', 'ma'])
        expect(result.states.find((s) => s.key === key)?.value).toEqual(expect.any(Number))
      for (const key of ['iv', 'pcr', 'oi'])
        expect(result.states.find((s) => s.key === key)?.side).toBe('WAIT')
      const until = closeTime(source[69], seconds, !!p.session, p.session)
      expect(new NineIndicatorEngine().update(source, { ...opts, asOf: until })).toEqual(
        new NineIndicatorEngine().update(source.slice(0, 70), { ...opts, asOf: until })
      )
      const shape = barsFor(Array(35).fill(100), seconds, p)
      shape[25] = {
        ...shape[25],
        open: 98 * p.scale,
        high: 100 * p.scale,
        low: 94 * p.scale,
        close: 98 * p.scale,
      }
      shape[29] = {
        ...shape[29],
        open: 104 * p.scale,
        high: 108 * p.scale,
        low: 102 * p.scale,
        close: 104 * p.scale,
      }
      for (const direction of ['long', 'short'] as const) {
        const plan = calculateEntryPlan(
          shape,
          100 * p.scale,
          p.tick,
          direction,
          seconds,
          p.session ?? false
        ).plan
        expect(plan).not.toBeNull()
        expect(plan!.entry).toBe(100 * p.scale)
        expect(Math.abs(plan!.target - plan!.entry)).toBeCloseTo(
          2 * Math.abs(plan!.entry - plan!.stop),
          6
        )
        for (const value of [plan!.stop, plan!.target])
          expect(value / p.tick).toBeCloseTo(Math.round(value / p.tick), 6)
        expect(
          direction === 'long'
            ? plan!.stop < plan!.entry && plan!.target > plan!.entry
            : plan!.stop > plan!.entry && plan!.target < plan!.entry
        ).toBe(true)
      }
      const levels = new ToolkitEngine().update(source, opts)
      expect(
        levels.zones.every(
          (z) => z.low <= z.high && Number.isFinite(z.low) && Number.isFinite(z.high)
        )
      ).toBe(true)
      const legacy = computeStudies(source, interval, asOf, { continuous: p.exchange === 'DELTA' })
      expect(legacy.ema.at(-1)?.value).toEqual(expect.any(Number))
      expect(legacy.rsi.at(-1)?.value).toEqual(expect.any(Number))
      expect(legacy.upper.at(-1)?.value).toBe(Math.max(...source.slice(-21, -1).map((b) => b.high)))
      expect(legacy.lower.at(-1)?.value).toBe(Math.min(...source.slice(-21, -1).map((b) => b.low)))
      const candleScope = {
        symbol: p.symbol,
        exchange: p.exchange,
        seconds,
        asOf,
        indian: !!p.session,
        session: p.session,
        tickSize: p.tick,
      }
      const candles = analyzeCandles(source, candleScope)
      expect(candles.closedTime).toBe(source.at(-1)!.time)
      expect(analyzeCandles(source, { ...candleScope, asOf: until })).toEqual(
        analyzeCandles(source.slice(0, 70), { ...candleScope, asOf: until })
      )
      if (seconds >= 86400) expect(candles.support).toEqual(expect.any(Number))
    })
  it(`${p.symbol}: both candlestick directions use own prices, tick-aligned SL and exact 2R`, () => {
    const source = barsFor(Array(12).fill(100), 60, p)
    source[10] = {
      ...source[10],
      open: 100.5 * p.scale,
      high: 100.8 * p.scale,
      low: 99.8 * p.scale,
      close: 100 * p.scale,
    }
    source[11] = {
      ...source[11],
      open: 99.9 * p.scale,
      high: 101 * p.scale,
      low: 99.5 * p.scale,
      close: 100.8 * p.scale,
    }
    for (const bull of [true, false]) {
      const bars = bull
        ? source
        : source.map((b) => ({
            ...b,
            open: 200 * p.scale - b.open,
            high: 200 * p.scale - b.low,
            low: 200 * p.scale - b.high,
            close: 200 * p.scale - b.close,
          }))
      expect(detectPattern(bars)?.side).toBe(bull ? 'CALL' : 'PUT')
      const r = analyzeCandles(bars, {
        symbol: p.symbol,
        exchange: p.exchange,
        seconds: 60,
        asOf: bars.at(-1)!.time + 60,
        indian: !!p.session,
        session: p.session,
        tickSize: p.tick,
      })
      expect(r.latest?.side).toBe(bull ? 'CALL' : 'PUT')
      expect(Math.abs(r.latest!.target - r.latest!.entry)).toBeCloseTo(
        2 * Math.abs(r.latest!.entry - r.latest!.stop),
        6
      )
      expect(r.latest!.stop / p.tick).toBeCloseTo(Math.round(r.latest!.stop / p.tick), 6)
      expect(r.latest!.target / p.tick).toBeCloseTo(Math.round(r.latest!.target / p.tick), 6)
    }
  })
  for (const mode of [
    'previous_day_break_5m',
    'opening_range_break_5m',
    'ema_cross_1m',
    'ema_cross_5m',
    'ema_pullback_1m',
  ])
    it(`${p.symbol}: ${mode} uses its own prices, session and permitted trade direction`, () => {
      const session = p.session ?? { start: 0, end: 1440, offset: 0 },
        start = Date.UTC(2026, 9, 29) / 1000 - session.offset + session.start * 60
      const previous = Array.from({ length: session.end - session.start }, (_, i) => ({
        time: start + i * 60,
        open: 100 * p.scale,
        close: 100 * p.scale,
        high: 101 * p.scale,
        low: 99 * p.scale,
        volume: 100,
      }))
      const current = Array.from({ length: 180 }, (_, i) => {
        const close = Math.round(((100 + 20 * Math.sin(i / 10)) * p.scale) / p.tick) * p.tick,
          open =
            Math.round(((100 + 20 * Math.sin(Math.max(0, i - 1) / 10)) * p.scale) / p.tick) * p.tick
        return {
          time: start + 86400 + i * 60,
          open,
          close,
          high: Math.max(open, close) + p.scale,
          low: Math.min(open, close) - p.scale,
          volume: 100,
        }
      })
      const optionSide = /(CE|PE)$/.exec(p.symbol)?.[0] as 'CE' | 'PE' | undefined
      const result = compute(
        [...previous, ...current],
        { mode, reward: 4 },
        {
          symbol: p.symbol,
          interval: '1m',
          universal: true,
          continuous: p.exchange === 'DELTA',
          session: p.session,
          tickSize: p.tick,
          optionSide,
        }
      )
      expect(result.values.ready.at(-1)).toBe(1)
      for (const trade of result.trades) {
        expect(Math.abs(trade.target - trade.entry)).toBeCloseTo(
          2 * Math.abs(trade.entry - trade.stop),
          6
        )
        expect(trade.stop / p.tick).toBeCloseTo(Math.round(trade.stop / p.tick), 6)
        expect(trade.target / p.tick).toBeCloseTo(Math.round(trade.target / p.tick), 6)
        if (optionSide) expect(trade.side).toBe(1)
      }
    })
}
