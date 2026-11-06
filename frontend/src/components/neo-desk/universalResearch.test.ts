import { expect, it } from 'vitest'
import { compute, type ResearchBar } from './piyushResearchEngine.js'
const make = (continuous = false) =>
  Array.from({ length: 170 }, (_, i) => {
    const close = i < 75 ? 100 - i * 0.1 : 92.5 + (i - 75) * 0.7
    return {
      time: Date.UTC(2026, 9, 30, continuous ? 0 : 3, continuous ? 0 : 45) / 1000 + i * 60,
      open: close - 0.1,
      high: close + 0.5,
      low: close - 0.5,
      close,
      volume: 100,
    }
  })
it.each([
  'RELIANCE',
  'BANKNIFTY',
  'NIFTY03NOV2623000CE',
  'SENSEX03NOV2675000PE',
  'GOLD30NOV26FUT',
])('supports price research setups on %s using its own prices and tick', (symbol) => {
  const r = compute(make(), { mode: 'ema_cross_1m', reward: 2 }, {
    symbol,
    interval: '1m',
    universal: true,
    session: { start: 555, end: 930, offset: 19800 },
    tickSize: 0.05,
  } as never)
  expect(r.values.ready.at(-1)).toBe(1)
  expect(r.trades.length).toBeGreaterThan(0)
  for (const t of r.trades)
    expect(Math.abs(t.target - t.entry)).toBeCloseTo(2 * Math.abs(t.entry - t.stop), 8)
})
it('supports continuous BTC candles without imposing NSE market hours and rounds stops using BTC ticks', () => {
  const r = compute(make(true), { mode: 'ema_cross_1m', reward: 2 }, {
    symbol: 'BTCUSD',
    interval: '1m',
    universal: true,
    session: { start: 555, end: 930, offset: 19800 },
    continuous: true,
    tickSize: 0.5,
  } as never)
  expect(r.values.ready.at(-1)).toBe(1)
  expect(r.trades.length).toBeGreaterThan(0)
  for (const t of r.trades) expect(t.stop / 0.5).toBeCloseTo(Math.round(t.stop / 0.5), 8)
})
it('keeps the archived index-only research behavior unchanged unless universal mode is requested', () => {
  expect(
    compute(make(), { mode: 'ema_cross_1m', reward: 2 }, { symbol: 'RELIANCE', interval: '1m' })
      .trades
  ).toHaveLength(0)
})

it.each([
  'CE',
  'PE',
])('keeps bought %s premium research long and rejects bearish short-premium entries', (side) => {
  const source = make().map((b, i) =>
    i < 110
      ? b
      : {
          ...b,
          open: 150 - (i - 110),
          close: 149.9 - (i - 110),
          high: 150.5 - (i - 110),
          low: 149.4 - (i - 110),
        }
  )
  const r = compute(source, { mode: 'ema_cross_1m', reward: 4 }, {
    symbol: `NIFTY03NOV2623000${side}`,
    interval: '1m',
    universal: true,
    session: { start: 555, end: 930, offset: 19800 },
    tickSize: 0.05,
    optionSide: side,
  } as never)
  expect(r.trades.length).toBeGreaterThan(0)
  for (const t of r.trades) {
    expect(t.side).toBe(1)
    expect(t.stop).toBeLessThan(t.entry)
    expect(t.target - t.entry).toBeCloseTo(2 * (t.entry - t.stop), 8)
  }
})
it.each([
  'previous_day_break_5m',
  'opening_range_break_5m',
  'ema_cross_1m',
  'ema_cross_5m',
  'ema_pullback_1m',
])('makes %s available on continuous crypto and cash charts', (mode) => {
  for (const continuous of [false, true]) {
    const current = make(continuous),
      count = continuous ? 1440 : 375
    const previous = Array.from({ length: count }, (_, i) => ({
      ...current[0],
      time: current[0].time - 86400 + i * 60,
      open: 100,
      high: 101,
      low: 99,
      close: 100,
    }))
    const result = compute([...previous, ...current], { mode, reward: 4 }, {
      symbol: continuous ? 'BTCUSD' : 'RELIANCE',
      interval: '1m',
      universal: true,
      session: { start: 555, end: 930, offset: 19800 },
      continuous,
      tickSize: continuous ? 0.5 : 0.05,
    } as never)
    expect(result.values.ready.at(-1)).toBe(1)
    for (const t of result.trades)
      expect(Math.abs(t.target - t.entry)).toBeCloseTo(2 * Math.abs(t.entry - t.stop), 8)
  }
})

it.each([
  { symbol: 'GOLD30NOV26FUT', start: 540, end: 1435, hour: 18 },
  { symbol: 'USDINR30NOV26FUT', start: 540, end: 1020, hour: 14.5 },
])('uses the configured session for $symbol, including signals after the NSE close', ({
  symbol,
  start,
  end,
  hour,
}) => {
  const shifted = make().map((b) => ({ ...b, time: b.time + (hour * 60 - 555) * 60 }))
  const result = compute(
    shifted,
    { mode: 'ema_cross_1m' },
    {
      symbol,
      interval: '1m',
      universal: true,
      tickSize: 0.05,
      session: { start, end, offset: 19800 },
    }
  )
  expect(result.trades.length).toBeGreaterThan(0)
  expect(result.trades.some((t) => ((t.entry_time + 19800) % 86400) / 60 > 930)).toBe(true)
  for (const t of result.trades)
    expect(Math.abs(t.target - t.entry)).toBeCloseTo(2 * Math.abs(t.entry - t.stop), 8)
})
it('reports unavailable previous-session data instead of silently claiming no setup', () => {
  const result = compute(
    make(),
    { mode: 'previous_day_break_5m' },
    {
      symbol: 'RELIANCE',
      interval: '1m',
      universal: true,
      tickSize: 0.05,
      session: { start: 555, end: 930, offset: 19800 },
    }
  )
  expect(result.values.ready.at(-1)).not.toBe(1)
  expect(result.status).toMatch(/previous session/i)
})

it('rejects an older weekday range when the actual preceding weekday is missing', () => {
  const today = make(),
    old = Array.from({ length: 375 }, (_, i) => ({
      ...today[0],
      time: today[0].time - 2 * 86400 + i * 60,
      open: 100,
      high: 101,
      low: 99,
      close: 100,
    }))
  const result = compute(
    [...old, ...today],
    { mode: 'previous_day_break_5m' },
    {
      symbol: 'RELIANCE',
      interval: '1m',
      universal: true,
      tickSize: 0.05,
      session: { start: 555, end: 930, offset: 19800 },
    }
  )
  expect(result.values.ready.at(-1)).not.toBe(1)
  expect(result.trades).toHaveLength(0)
})
