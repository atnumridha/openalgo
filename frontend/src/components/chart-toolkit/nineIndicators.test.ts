import { describe, expect, it } from 'vitest'
import { ToolkitEngine, type Bar } from './model'
import { INDICATORS, NineIndicatorEngine, type IndicatorKey } from './nineIndicators'

const start = 1_700_000_000
const candle = (index: number, close: number, open = close): Bar => ({
  time: start + index * 60,
  open,
  high: Math.max(open, close) + 1,
  low: Math.min(open, close) - 1,
  close,
  volume: 100,
})
const flat = (length: number) => Array.from({ length }, (_, i) => candle(i, 100))
const reversalPrice = (i: number) =>
  i < 35 ? 150 - i : i < 75 ? 115 + (i - 35) * 2 : 195 - (i - 75) * 2
const reversals = Array.from({ length: 120 }, (_, i) =>
  candle(i, reversalPrice(i), reversalPrice(Math.max(i - 1, 0)))
)
const complete = (bars: Bar[]) => ({ seconds: 60, asOf: (bars.at(-1)?.time ?? start) + 60 })
const evaluate = (bars: Bar[]) => new NineIndicatorEngine().update(bars, complete(bars))
const stateOf = (bars: Bar[], key: IndicatorKey) =>
  evaluate(bars).states.find((s) => s.key === key)!

describe('independent indicator catalog and warmup', () => {
  it('exposes all nine studies with stable chart ids and readable names', () => {
    expect(INDICATORS.map(({ key, id, short }) => [key, id, short])).toEqual([
      ['rsi', 'nine-rsi', 'RSI'],
      ['bb', 'nine-bb', 'BB'],
      ['iv', 'nine-iv', 'IV'],
      ['imi', 'nine-imi', 'IMI'],
      ['mfi', 'nine-mfi', 'MFI'],
      ['pcr', 'nine-pcr', 'PCR'],
      ['oi', 'nine-oi', 'OI'],
      ['macd', 'nine-macd', 'MACD'],
      ['ma', 'nine-ma', 'MA'],
    ])
    expect(INDICATORS.every((indicator) => indicator.label.length > 3)).toBe(true)
  })

  it('returns nine neutral states before any candle closes', () => {
    const result = new NineIndicatorEngine().update([candle(0, 100)], {
      seconds: 60,
      asOf: start + 59,
    })
    expect(result.lastTime).toBeNull()
    expect(result.bias).toBe('WAIT')
    expect(result.events).toEqual([])
    expect(result.states).toHaveLength(9)
    expect(
      result.states.every((s) => s.side === 'WAIT' && s.value === null && s.time === null)
    ).toBe(true)
  })

  it.each<[IndicatorKey, number]>([
    ['rsi', 14],
    ['imi', 13],
    ['mfi', 14],
    ['bb', 19],
    ['macd', 25],
    ['ma', 49],
  ])('withholds %s until its numeric window is ready', (key, count) => {
    const state = stateOf(flat(count), key)
    expect(state.value).toBeNull()
    expect(state.side).toBe('WAIT')
    expect(state.time).toBeNull()
    expect(state.reason).toMatch(/warm/i)
  })

  it('keeps ready numeric studies neutral until a confirmed transition occurs', () => {
    const result = evaluate(flat(70))
    for (const key of ['rsi', 'bb', 'imi', 'mfi', 'macd', 'ma']) {
      const state = result.states.find((s) => s.key === key)!
      expect(state.value).not.toBeNull()
      expect(state.side).toBe('WAIT')
      expect(state.time).toBeNull()
      expect(state.reason).toMatch(/no confirmed event/i)
    }
    expect(result.events).toEqual([])
  })

  it('leaves IV, PCR and OI for independently validated external context', () => {
    const result = evaluate(reversals)
    for (const key of ['iv', 'pcr', 'oi']) {
      expect(result.states.find((s) => s.key === key)).toMatchObject({
        value: null,
        side: 'WAIT',
        time: null,
      })
      expect(result.events.some((event) => event.key === key)).toBe(false)
    }
  })
})

describe('six separate confirmed transition rules', () => {
  it.each<[IndicatorKey, number, number]>([
    ['rsi', 38, 80],
    ['imi', 38, 80],
    ['mfi', 38, 78],
    ['macd', 37, 77],
  ])('emits both %s directions at its own threshold or line cross', (key, callIndex, putIndex) => {
    const result = evaluate(reversals)
    expect(result.events.filter((event) => event.key === key)).toEqual([
      { key, time: reversals[callIndex].time, side: 'CALL', price: reversals[callIndex].low },
      { key, time: reversals[putIndex].time, side: 'PUT', price: reversals[putIndex].high },
    ])
    expect(result.states.find((s) => s.key === key)).toMatchObject({
      side: 'PUT',
      time: reversals[putIndex].time,
    })
  })

  it('emits Bollinger breakouts once per close crossing, with the current bands', () => {
    const bars = [...flat(20), candle(20, 150), candle(21, 160), candle(22, 50)]
    expect(evaluate(bars).events.filter((event) => event.key === 'bb')).toEqual([
      { key: 'bb', time: bars[20].time, side: 'CALL', price: bars[20].low },
      { key: 'bb', time: bars[22].time, side: 'PUT', price: bars[22].high },
    ])
    const shared = new ToolkitEngine().update(bars, complete(bars))
    expect(stateOf(bars, 'bb').value).toBeCloseTo(shared.current.bbWidth!, 10)
  })

  it('emits MA only when close enters above or below both EMA20 and SMA50', () => {
    const bars = [...flat(50), candle(50, 110), candle(51, 111), candle(52, 90), candle(53, 89)]
    const result = evaluate(bars)
    expect(result.events.filter((event) => event.key === 'ma')).toEqual([
      { key: 'ma', time: bars[50].time, side: 'CALL', price: bars[50].low },
      { key: 'ma', time: bars[52].time, side: 'PUT', price: bars[52].high },
    ])
    expect(result.bias).toBe('PUT')
    expect(stateOf(bars.slice(0, 52), 'ma').side).toBe('CALL')
  })

  it('makes current MA direction available as bias even before any transition', () => {
    const bars = Array.from({ length: 50 }, (_, i) => candle(i, 100 + i))
    const result = evaluate(bars)
    expect(result.bias).toBe('CALL')
    expect(result.events.filter((event) => event.key === 'ma')).toEqual([])
    expect(result.states.find((s) => s.key === 'ma')?.side).toBe('WAIT')
  })

  it('uses shared numeric metrics while clearly dating previous confirmed events', () => {
    const result = evaluate(reversals)
    const metrics = new ToolkitEngine().update(reversals, complete(reversals)).current
    for (const key of ['rsi', 'imi', 'mfi', 'macd'] as const) {
      expect(result.states.find((s) => s.key === key)?.value).toBeCloseTo(metrics[key]!, 10)
      expect(result.states.find((s) => s.key === key)?.reason).toMatch(/last confirmed event/i)
    }
    expect(result.lastTime).toBe(reversals.at(-1)!.time)
  })

  it('does not discard older markers after repeated waves', () => {
    const bars = Array.from({ length: 900 }, (_, i) => {
      const close = 200 + 30 * Math.sin(i / 9)
      const open = 200 + 30 * Math.sin(Math.max(0, i - 1) / 9)
      return candle(i, close, open)
    })
    const full = evaluate(bars)
    const earlier = evaluate(bars.slice(0, 200))
    expect(full.events.length).toBeGreaterThan(100)
    expect(full.events.filter((event) => event.time <= bars[199].time)).toEqual(earlier.events)
  })
})

describe('data quality and candle confirmation', () => {
  it.each([
    0,
    -1,
    Number.NaN,
    Number.POSITIVE_INFINITY,
  ])('keeps current MFI WAIT for invalid volume %s even after a historical event', (volume) => {
    const bars = reversals.map((bar, i) => (i === reversals.length - 1 ? { ...bar, volume } : bar))
    const result = evaluate(bars)
    expect(result.events.some((event) => event.key === 'mfi')).toBe(true)
    expect(result.states.find((s) => s.key === 'mfi')).toMatchObject({
      value: null,
      side: 'WAIT',
      time: null,
    })
    expect(result.states.find((s) => s.key === 'mfi')?.reason).toMatch(/volume/i)
  })

  it('requires the whole MFI flow window to contain genuine positive volume', () => {
    const bars = reversals.slice(0, 40).map((bar, i) => (i === 30 ? { ...bar, volume: 0 } : bar))
    expect(evaluate(bars).events.some((event) => event.key === 'mfi')).toBe(false)
    expect(stateOf(bars, 'mfi').value).toBeNull()
  })

  it('suppresses entries across a missing candle while preserving older events', () => {
    const bars = [...flat(50), candle(51, 150), candle(52, 160)]
    const result = evaluate(bars)
    expect(result.events.filter((event) => event.time === bars[50].time)).toEqual([])
    expect(result.events.filter((event) => event.key === 'ma')).toEqual([])
    expect(result.bias).toBe('CALL')
  })

  it.each([
    { close: Number.NaN },
    { high: 90 },
    { low: 110 },
    { close: -1 },
  ])('does not bridge an invalid OHLC candle %o into a breakout', (invalid) => {
    const bars = [...flat(50), { ...candle(50, 100), ...invalid }, candle(51, 150)]
    const result = evaluate(bars)
    expect(result.lastTime).toBe(bars[51].time)
    expect(result.events.filter((event) => event.time === bars[51].time)).toEqual([])
    expect(
      result.states.every((state) => state.value === null || Number.isFinite(state.value))
    ).toBe(true)
  })

  it('excludes live and future candles from values, bias and markers', () => {
    const bars = [...flat(50), candle(50, 150), candle(51, 40)]
    const engine = new NineIndicatorEngine()
    const asOf = bars[50].time + 59
    const expected = engine.update(bars.slice(0, 50), { seconds: 60, asOf })
    expect(engine.update(bars, { seconds: 60, asOf })).toEqual(expected)
    const confirmed = engine.update(bars, { seconds: 60, asOf: bars[50].time + 60 })
    expect(confirmed.lastTime).toBe(bars[50].time)
    expect(confirmed.events.some((event) => event.key === 'bb' && event.side === 'CALL')).toBe(true)
    expect(confirmed.events.some((event) => event.side === 'PUT')).toBe(false)
  })

  it('confirms Indian daily candles at the session close instead of adding 24 hours', () => {
    const first = Date.parse('2026-09-01T09:15:00+05:30') / 1000
    const bars = Array.from({ length: 21 }, (_, i) => ({
      ...candle(i, i === 20 ? 150 : 100),
      time: first + i * 86400,
    }))
    const end = bars[20].time + 22500
    const engine = new NineIndicatorEngine()
    const before = engine.update(bars, { seconds: 86400, asOf: end - 1, indian: true })
    expect(before.lastTime).toBe(bars[19].time)
    expect(before.events).toEqual([])
    const after = engine.update(bars, { seconds: 86400, asOf: end, indian: true })
    expect(after.lastTime).toBe(bars[20].time)
    expect(after.events.find((event) => event.key === 'bb')?.side).toBe('CALL')
  })

  it('keeps historical prefixes identical during replay and when future bars arrive', () => {
    const engine = new NineIndicatorEngine()
    const prefix = reversals.slice(0, 65)
    const a = engine.update(prefix, complete(prefix))
    const replay = engine.update(reversals, complete(prefix))
    expect(replay).toEqual(a)
    const b = engine.update(reversals, complete(reversals))
    expect(b.events.filter((event) => event.time <= a.lastTime!)).toEqual(a.events)
    expect(engine.update(prefix, complete(prefix))).toEqual(a)
  })

  it('invalidates previous values and events after a historical correction', () => {
    const engine = new NineIndicatorEngine()
    const bars = [...flat(50), candle(50, 150)]
    expect(engine.update(bars, complete(bars)).events.length).toBeGreaterThan(0)
    expect(engine.update(flat(51), complete(bars)).events).toEqual([])
  })

  it.each([
    { seconds: 0, asOf: start + 60 },
    { seconds: Number.NaN, asOf: start + 60 },
    { seconds: 60, asOf: Number.NaN },
  ])('returns neutral results for invalid timing %o', (options) => {
    const result = new NineIndicatorEngine().update(reversals, options)
    expect(result.events).toEqual([])
    expect(result.lastTime).toBeNull()
    expect(result.bias).toBe('WAIT')
  })
})
