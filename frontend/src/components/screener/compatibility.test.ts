import { expect, it } from 'vitest'
import { evaluateScreen } from './engine'
import { FRAMES, frameSeconds, type ScreenDefinition, type ScanDataset } from './model'
import type { PatternFamily } from '../chart-toolkit/candlePatterns'
import { closeTime } from '../chart-toolkit/model'
const equity = { start: 555, end: 930, offset: 19800 },
  derivative = { ...equity, end: 940 }
const profiles = [
  ['NIFTY', 'NSE_INDEX', 200, equity],
  ['SENSEX', 'BSE_INDEX', 500, equity],
  ['RELIANCE', 'NSE', 20, equity],
  ['NIFTY03NOV2623000CE', 'NFO', 1, derivative],
  ['NIFTY03NOV2623000PE', 'NFO', 1, derivative],
  ['SENSEX05NOV2675000PE', 'BFO', 1, derivative],
  ['BTCUSD', 'DELTA', 500, null],
  ['ETHUSD', 'DELTA', 20, null],
] as const
const shapes: Record<PatternFamily, number[][]> = {
  engulfing: [
    [100, 101, 99, 100],
    [100.5, 100.8, 99.8, 100],
    [99.9, 101, 99.5, 100.8],
  ],
  rejection: [
    [100, 101, 99, 100],
    [100, 101, 99, 100],
    [100, 100.55, 97, 100.5],
  ],
  'inside-break': [
    [100, 103, 97, 100],
    [100, 101, 99, 100],
    [100, 104.5, 99.5, 104],
  ],
  star: [
    [104, 105, 99.5, 100],
    [99.5, 100, 99, 99.7],
    [100, 104, 99.8, 103],
  ],
  marubozu: [
    [100, 101, 99, 100],
    [100, 101, 99, 100],
    [100, 104.1, 99.9, 104],
  ],
  'three-candles': [
    [98, 100.1, 97.9, 100],
    [99, 101.1, 98.9, 101],
    [100, 102.1, 99.9, 102],
  ],
  piercing: [
    [100, 101, 99, 100],
    [104, 105, 99.5, 100],
    [99.8, 103.5, 99.5, 103],
  ],
}
function times(count: number, seconds: number, session: ScanDataset['session']) {
  const out: number[] = []
  let day = Date.UTC(2026, 9, 1) / 1000
  while (out.length < count) {
    if (!session || ![0, 6].includes(new Date(day * 1000).getUTCDay())) {
      if (seconds >= 86400) out.push(day)
      else
        for (
          let t = day - (session?.offset ?? 0) + (session?.start ?? 0) * 60;
          t < day - (session?.offset ?? 0) + (session?.end ?? 1440) * 60 && out.length < count;
          t += seconds
        )
          out.push(t)
    }
    day += 86400
  }
  return out
}
function definition(
  pattern: PatternFamily,
  bull: boolean,
  interval: ScreenDefinition['interval']
): ScreenDefinition {
  return {
    version: 1,
    name: 'Pattern test',
    interval,
    universe: { kind: 'stored' },
    intent: bull ? 'bullish' : 'bearish',
    rule: {
      type: 'group',
      id: 'root',
      op: 'all',
      children: [
        {
          type: 'condition',
          id: 'pattern',
          left: { field: 'candle_pattern', pattern },
          op: 'eq',
          right: bull ? 1 : -1,
        },
      ],
    },
  }
}
for (const [symbol, exchange, scale, session] of profiles)
  for (const pattern of Object.keys(shapes) as PatternFamily[]) {
    it(`${symbol}: ${pattern} confirms both own-price directions without future-bar leakage`, () => {
      const stamps = times(15, 60, session)
      for (const bull of [true, false]) {
        const candles = [
          ...Array.from({ length: 12 }, () => [100, 101, 99, 100]),
          ...shapes[pattern],
        ].map(([open, high, low, close], i) => ({
          time: stamps[i],
          open: (bull ? open : 200 - open) * scale,
          high: (bull ? high : 200 - low) * scale,
          low: (bull ? low : 200 - high) * scale,
          close: (bull ? close : 200 - close) * scale,
          volume: 100,
        }))
        const observedAt = closeTime(candles.at(-1)!, 60, !!session, session ?? undefined)
        const dataset: ScanDataset = {
          symbol,
          exchange,
          interval: '1m',
          source: 'hand-checked fixture',
          observedAt,
          session,
          candles,
          daily: [],
        }
        const screen = definition(pattern, bull, '1m'),
          row = evaluateScreen(dataset, screen, observedAt)
        expect(row.state).toBe('match')
        expect(row.time).toBe(candles.at(-1)!.time)
        const side = ['NFO', 'BFO'].includes(exchange) ? /(CE|PE)$/.exec(symbol)?.[0] : undefined
        expect(row.direction).toBe(
          side
            ? `${bull ? 'BUY' : 'AVOID'} ${side}`
            : exchange === 'DELTA'
              ? `${bull ? 'LONG' : 'SHORT'} setup`
              : `${bull ? 'BULLISH' : 'BEARISH'} setup`
        )
        const future = {
          ...candles.at(-1)!,
          time: observedAt,
          close: 90 * scale,
          low: 89 * scale,
          high: 110 * scale,
        }
        expect(
          evaluateScreen({ ...dataset, candles: [...candles, future] }, screen, observedAt)
        ).toEqual(row)
      }
    })
  }
for (const interval of FRAMES)
  it(`${interval}: screener periods and previous-session context have hand-checked values`, () => {
    const seconds = frameSeconds(interval),
      session = equity,
      stamps = times(60, seconds, session)
    const candles = stamps.map((time, i) => ({
      time,
      open: 100 + i,
      close: 100 + i,
      high: 101 + i,
      low: 99 + i,
      volume: i === 59 ? 200 : 100,
    }))
    const observedAt = closeTime(candles.at(-1)!, seconds, true, session)
    const day = Math.floor((candles.at(-1)!.time + 19800) / 86400) * 86400 - 19800
    let priorDay = day - 86400
    while ([0, 6].includes(new Date((priorDay + 19800) * 1000).getUTCDay())) priorDay -= 86400
    const data: ScanDataset = {
      symbol: 'NIFTY',
      exchange: 'NSE_INDEX',
      interval,
      source: 'fixture',
      observedAt,
      session,
      candles,
      daily: [{ time: priorDay, open: 100, high: 200, low: 90, close: 100, volume: 100 }],
    }
    const d = definition('engulfing', true, interval)
    d.rule.children = [
      { type: 'condition', id: 'sma', left: { field: 'sma', period: 20 }, op: 'eq', right: 149.5 },
      {
        type: 'condition',
        id: 'vol',
        left: { field: 'relative_volume', period: 20 },
        op: 'eq',
        right: 2,
      },
      { type: 'condition', id: 'prior', left: { field: 'prior_day_high' }, op: 'eq', right: 200 },
    ]
    const row = evaluateScreen(data, d, observedAt)
    expect(row.state).toBe('match')
    expect(row.values.rsi).toBe(100)
    expect(row.values.session_change_pct).toBeCloseTo(59)
    expect(row.values.atr).toBeCloseTo(2)
    expect(row.values.sma).toBe(149.5)
    expect(row.values.prior_day_high).toBe(200)
  })
