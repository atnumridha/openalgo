import { describe, expect, it } from 'vitest'
import {
  ToolkitEngine,
  advanceSetup,
  emptyTiming,
  breakoutStrength,
  completedReferences,
  optionPrice,
  impliedVolatility,
  matchOptionSnapshot,
  type Bar,
} from './model'

const bar = (time: number, close: number, high = close + 1, low = close - 1): Bar => ({
  time,
  open: close,
  high,
  low,
  close,
  volume: 100,
})
const wave = Array.from({ length: 220 }, (_, i) =>
  bar(1700000000 + i * 60, 100 + Math.sin(i / 8) * 10 + i / 100)
)

describe('closed price decisions', () => {
  it('updates EMA 9 and EMA 15 independently on the latest candle', () => {
    const result = new ToolkitEngine().update([bar(1000, 100), bar(1060, 101)], {
      seconds: 60,
      asOf: 1120,
    })
    expect(result.current.ema9).toBeCloseTo(100.2, 8)
    expect(result.current.emaSlow).toBeCloseTo(100.125, 8)
  })
  it('requires matching recent RSI exit, MACD cross and strengthening momentum once per event', () => {
    const state = emptyTiming()
    expect(
      advanceSetup(
        state,
        {
          rsi: 32,
          previousRsi: 28,
          macd: -1,
          previousMacd: -2,
          signal: -1.5,
          previousSignal: -1.5,
          histogram: 0.5,
          previousHistogram: -0.5,
        },
        30
      ).status
    ).toBe('BULL')
    expect(
      advanceSetup(
        state,
        {
          rsi: 40,
          previousRsi: 32,
          macd: 2,
          previousMacd: -1,
          signal: 0,
          previousSignal: -1.5,
          histogram: 2,
          previousHistogram: 0.5,
        },
        31
      ).status
    ).toBe('WAIT')
  })
  it('supports BEAR exits and rejects stale or opposite MACD crosses', () => {
    const state = emptyTiming()
    expect(
      advanceSetup(
        state,
        {
          rsi: 68,
          previousRsi: 75,
          macd: -1,
          previousMacd: 1,
          signal: 0,
          previousSignal: 0,
          histogram: -1,
          previousHistogram: 1,
        },
        40
      ).status
    ).toBe('BEAR')
    const late = { ...emptyTiming(), bullExit: 10, bullCross: 10 }
    expect(
      advanceSetup(
        late,
        {
          rsi: 50,
          previousRsi: 49,
          macd: 2,
          previousMacd: 1,
          signal: 0,
          previousSignal: 0,
          histogram: 2,
          previousHistogram: 1,
        },
        16
      ).status
    ).toBe('WAIT')
  })
  it('does not emit decisions, pivots or liquidity from an unclosed candle', () => {
    const engine = new ToolkitEngine()
    const asOf = wave.at(-1)!.time + 10
    const first = engine.update(wave, { seconds: 60, asOf })
    const changed = [...wave.slice(0, -1), { ...wave.at(-1)!, close: 150, high: 150 }]
    const second = engine.update(changed, { seconds: 60, asOf })
    expect(second.signals).toEqual(first.signals)
    expect(second.zones).toEqual(first.zones)
    expect(second.pools).toEqual(first.pools)
    expect(second.current.ema9).not.toBe(first.current.ema9)
    expect(second.closedTime).toBe(wave.at(-2)!.time)
  })
  it('keeps historical signals unchanged when future bars arrive', () => {
    const engine = new ToolkitEngine()
    const a = engine.update(wave.slice(0, 170), { seconds: 60, asOf: wave[170].time })
    const b = engine.update(wave, { seconds: 60, asOf: wave.at(-1)!.time + 60 })
    expect(a.signals.length).toBeGreaterThan(0)
    expect(b.allSignals.filter((s) => s.time <= a.closedTime!)).toEqual(a.allSignals)
  })
  it('invalidates cached history when an earlier candle is corrected', () => {
    const engine = new ToolkitEngine()
    const options = { seconds: 60, asOf: wave.at(-1)!.time + 60 }
    const a = engine.update(wave, options)
    const changed = wave.map((b, i) =>
      i === 205 ? { ...b, close: b.close + 8, high: b.high + 8 } : b
    )
    const b = engine.update(changed, options)
    expect(b.current.ema9).not.toBe(a.current.ema9)
  })
  it('withholds warmup values and hides volume-dependent MFI for index data', () => {
    const result = new ToolkitEngine().update(
      wave.slice(0, 10).map((b) => ({ ...b, volume: 0 })),
      { seconds: 60, asOf: wave[10].time }
    )
    expect(result.current.rsi).toBeNull()
    expect(result.current.mfi).toBeNull()
    expect(result.confirmed.status).toBe('WAIT')
  })
})

describe('structure and price events', () => {
  it('confirms equal-high liquidity only after the second pivot has right-hand bars', () => {
    const values = [100, 101, 105, 101, 100, 102, 105, 102, 100]
    const bars = values.map((v, i) => bar(1700000000 + i * 60, v))
    const engine = new ToolkitEngine({ left: 2, right: 2 })
    expect(
      engine
        .update(bars.slice(0, 8), { seconds: 60, asOf: bars[7].time + 60 })
        .pools.filter((p) => p.above).length
    ).toBe(0)
    const confirmed = engine.update(bars, { seconds: 60, asOf: bars[8].time + 60 })
    expect(confirmed.pools.find((p) => p.above)).toMatchObject({
      level: 106,
      touches: 2,
      state: 'active',
      confirmedTime: bars[8].time,
    })
    const swept = engine.update(
      [...bars, { ...bar(bars[8].time + 60, 105, 108, 103), open: 104 }],
      { seconds: 60, asOf: bars[8].time + 120 }
    )
    expect(swept.pools.find((p) => p.above)?.state).toBe('swept')
    expect(swept.events.at(-1)?.kind).toBe('sweep-high')
  })
  it('requires a strong directional close for a breakout, not a wick poke', () => {
    expect(breakoutStrength({ open: 100, high: 106, low: 99, close: 105 }, 4, true)).toBe(true)
    expect(breakoutStrength({ open: 100, high: 106, low: 99, close: 101 }, 4, true)).toBe(false)
    expect(breakoutStrength({ open: 106, high: 107, low: 99, close: 100 }, 4, false)).toBe(true)
  })
})

describe('timeframe references', () => {
  const start = Date.parse('2026-10-23T09:15:00+05:30') / 1000
  const hourly = Array.from({ length: 7 }, (_, i) =>
    bar(start + i * 3600, 100 + i, 110 + i, 90 - i)
  )
  it('uses the last completed 4H session block and includes the shortened closing bar', () => {
    const result = completedReferences(hourly, 3600, start + 22500, true)
    expect(result.find((r) => r.name === '4H High')?.price).toBe(116)
    expect(result.find((r) => r.name === '4H Low')?.price).toBe(84)
    expect(result.find((r) => r.name === '1D High')?.price).toBe(116)
  })
  it('does not invent 1H levels from daily candles or use a partially open 4H block', () => {
    expect(
      completedReferences([bar(start, 100)], 86400, start + 86400, true).some((r) =>
        r.name.startsWith('1H')
      )
    ).toBe(false)
    const result = completedReferences(hourly, 3600, start + 4 * 3600 - 1, true)
    expect(result.some((r) => r.name.startsWith('4H'))).toBe(false)
    expect(result.find((r) => r.name === '1H High')?.price).toBe(112)
  })
  it('anchors crypto periods to UTC and excludes future source bars', () => {
    const t = Date.parse('2026-10-23T00:00:00Z') / 1000
    const result = completedReferences(
      [bar(t, 10, 12, 9), bar(t + 3600, 10, 999, 1)],
      3600,
      t + 3600,
      false
    )
    expect(result.find((r) => r.name === '1H High')?.price).toBe(12)
  })
})

describe('independent option IV', () => {
  it('inverts a known European call and put without inventing an IV history', () => {
    // Standard BSM fixture S=K=100, T=1, r=5%, q=0, sigma=20%.
    expect(optionPrice(100, 100, 1, 0.05, 0, 0.2, true)).toBeCloseTo(10.45058, 4)
    expect(impliedVolatility(10.45058, 100, 100, 1, 0.05, 0, true)).toBeCloseTo(20, 3)
    expect(impliedVolatility(5.573526, 100, 100, 1, 0.05, 0, false)).toBeCloseTo(20, 3)
  })
  it('rejects expired, impossible or missing option data', () => {
    expect(impliedVolatility(200, 100, 100, 1, 0, 0, true)).toBeNull()
    expect(impliedVolatility(10, 100, 100, 0, 0, 0, true)).toBeNull()
    expect(impliedVolatility(NaN, 100, 100, 1, 0, 0, true)).toBeNull()
  })
  it('pairs exact closed one-minute timestamps and reports stale context separately', () => {
    const option = [bar(1000, 5), bar(1060, 6)]
    const spot = [bar(1000, 100), bar(1120, 101)]
    expect(matchOptionSnapshot(option, spot, 1180)).toEqual({
      time: 1000,
      premium: 5,
      spot: 100,
      fresh: true,
    })
    expect(matchOptionSnapshot(option, spot, 1400)?.fresh).toBe(false)
  })
})

it('does not emit continuous-market setups or confirm pivots across missing minutes', () => {
  const original = new ToolkitEngine().update(wave, { seconds: 60, asOf: wave.at(-1)!.time + 60 })
  const signal = original.allSignals[0],
    index = wave.findIndex((b) => b.time === signal.time)
  expect(index).toBeGreaterThan(0)
  const source = wave.map((b, i) => (i >= index ? { ...b, time: b.time + 7200 } : b))
  const changed = new ToolkitEngine().update(source, {
    seconds: 60,
    asOf: source.at(-1)!.time + 60,
    continuous: true,
  } as never)
  expect(changed.allSignals.some((s) => s.time === source[index].time)).toBe(false)
  expect(
    changed.zones.some((z) => z.time < source[index].time && z.confirmedTime >= source[index].time)
  ).toBe(false)
})

it('confirms a partial final derivatives candle only at the configured contract session close', () => {
  const b = bar(Date.parse('2026-10-30T15:30:00+05:30') / 1000, 100),
    session = { start: 555, end: 940, offset: 19800 }
  expect(
    new ToolkitEngine().update([b], { seconds: 900, asOf: b.time + 300, indian: true, session })
      .closedTime
  ).toBeNull()
  expect(
    new ToolkitEngine().update([b], { seconds: 900, asOf: b.time + 600, indian: true, session })
      .closedTime
  ).toBe(b.time)
})
