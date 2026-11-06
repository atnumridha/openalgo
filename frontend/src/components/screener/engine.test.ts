import { expect, it } from 'vitest'
import { evaluateScreen, validateDefinition } from './engine'
import type { ScreenDefinition, ScanDataset, RuleNode } from './model'
const start = Date.UTC(2026, 9, 30) / 1000
const data: ScanDataset = {
  symbol: 'BTCUSD',
  exchange: 'DELTA',
  interval: '1m',
  source: 'test',
  observedAt: start + 60 * 60,
  tickSize: 0.5,
  session: null,
  candles: Array.from({ length: 60 }, (_, i) => ({
    time: start + i * 60,
    open: 100,
    high: 111,
    low: 99,
    close: i === 59 ? 110 : 100,
    volume: i === 59 ? 200 : 100,
  })),
  daily: [],
}
const condition = (left: unknown, op: string, right: unknown) =>
  ({ type: 'condition', id: 'a', left, op, right }) as RuleNode
const definition = (children: RuleNode[], op: 'all' | 'any' = 'all'): ScreenDefinition => ({
  version: 1,
  name: 'My scan',
  interval: '1m',
  universe: { kind: 'stored' },
  intent: 'observe',
  rule: { type: 'group', id: 'root', op, children },
})
it('uses hand-checked relative volume and closed-price thresholds', () => {
  const r = evaluateScreen(
    data,
    definition([
      condition({ field: 'relative_volume', period: 20 }, 'gte', 2),
      condition({ field: 'close' }, 'gt', 105),
    ]),
    data.observedAt
  )
  expect(r.state).toBe('match')
  expect(r.values.relative_volume).toBe(2)
  expect(r.direction).toBe('MATCH')
})
it('keeps missing volume unknown instead of passing a screen', () => {
  const r = evaluateScreen(
    { ...data, candles: data.candles.map((b) => ({ ...b, volume: 0 })) },
    definition([condition({ field: 'relative_volume', period: 20 }, 'gt', 1)]),
    data.observedAt
  )
  expect(r.state).toBe('unavailable')
})
it('uses three-valued ALL/ANY logic and ignores disabled leaves without treating empty rules as a match', () => {
  const no = condition({ field: 'close' }, 'lt', 50),
    unknown = condition({ field: 'session_change_pct' }, 'gt', 1)
  expect(evaluateScreen(data, definition([no, unknown]), data.observedAt).state).toBe('no-match')
  expect(evaluateScreen(data, definition([no, unknown], 'any'), data.observedAt).state).toBe(
    'unavailable'
  )
  expect(evaluateScreen(data, definition([{ ...no, enabled: false }]), data.observedAt).state).toBe(
    'unavailable'
  )
})
it('does not use a forming candle and verifies a real cross from the preceding closed bar', () => {
  const screen = definition([condition({ field: 'close' }, 'cross_above', 105)])
  expect(evaluateScreen(data, screen, data.observedAt).state).toBe('match')
  const future = {
    ...data,
    candles: [...data.candles, { ...data.candles[59], time: data.observedAt, close: 50, low: 40 }],
  }
  expect(evaluateScreen(future, screen, data.observedAt)).toEqual(
    evaluateScreen(data, screen, data.observedAt)
  )
})
it('does not bridge missing crypto bars to claim a crossover', () => {
  const bars = data.candles.filter((_, i) => i !== 58)
  expect(
    evaluateScreen(
      { ...data, candles: bars },
      definition([condition({ field: 'close' }, 'cross_above', 105)]),
      data.observedAt
    ).state
  ).toBe('unavailable')
})
it.each(['CE', 'PE'])('labels a bearish %s premium as AVOID, never SHORT', (side) => {
  const r = evaluateScreen(
    { ...data, symbol: `NIFTY03NOV2623000${side}`, exchange: 'NFO' },
    { ...definition([condition({ field: 'close' }, 'gt', 1)]), intent: 'bearish' },
    data.observedAt
  )
  expect(r.direction).toBe(`AVOID ${side}`)
})
it('keeps historical matches visible but ineligible for a new alert', () => {
  const r = evaluateScreen(
    data,
    definition([condition({ field: 'close' }, 'gt', 1)]),
    data.observedAt + 3600
  )
  expect(r.state).toBe('match')
  expect(r.fresh).toBe(false)
})
it('rejects malformed, excessive and unknown rules before evaluating', () => {
  expect(() =>
    validateDefinition({ ...definition([]), rule: condition({ field: 'made_up' }, 'gt', 1) })
  ).toThrow()
  expect(() =>
    validateDefinition(
      definition(Array.from({ length: 25 }, () => condition({ field: 'close' }, 'gt', 1)))
    )
  ).toThrow()
  expect(() =>
    validateDefinition(definition([condition({ field: 'ema', period: 0 }, 'gt', 1)]))
  ).toThrow()
  expect(validateDefinition(definition([condition({ field: 'rsi' }, 'gt', 50)])).name).toBe(
    'My scan'
  )
})

it('rejects a future after-session bar even if the session close helper clamps its close time', () => {
  const session = { start: 555, end: 930, offset: 19800 },
    end = Date.UTC(2026, 9, 30, 10) / 1000
  const source = {
    ...data,
    symbol: 'NIFTY',
    exchange: 'NSE_INDEX',
    session,
    observedAt: end,
    candles: [
      { ...data.candles[0], time: end - 60, close: 100 },
      { ...data.candles[0], time: end + 3600, close: 110, high: 111 },
    ],
  }
  const row = evaluateScreen(source, definition([condition({ field: 'close' }, 'gt', 105)]), end)
  expect(row.state).toBe('no-match')
  expect(row.values.close).toBe(100)
})
it('compares each daily crossover operand with its own preceding session', () => {
  const candles = Array.from({ length: 16 }, (_, i) => ({
    time: start + i * 86400,
    open: 100 + i,
    close: 100 + i,
    high: 100.5 + i,
    low: 99 + i,
    volume: 100,
  }))
  const daily = {
    ...data,
    interval: '1d' as const,
    observedAt: start + 16 * 86400,
    candles,
    daily: candles,
  }
  const d = {
    ...definition([condition({ field: 'close' }, 'cross_above', { field: 'prior_day_high' })]),
    interval: '1d' as const,
  }
  expect(evaluateScreen(daily, d, daily.observedAt).state).toBe('no-match')
  d.rule.children = [condition({ field: 'session_change_pct', offset: 1 }, 'gt', 0)]
  expect(evaluateScreen(daily, d, daily.observedAt).state).toBe('match')
})
it('does not warm up an opening-session candle pattern with the previous afternoon', () => {
  const session = { start: 555, end: 930, offset: 19800 },
    startOfDay = Date.UTC(2026, 9, 30, 3, 45) / 1000
  const previous = Array.from({ length: 11 }, (_, i) => ({
    time: startOfDay - 86400 + (364 + i) * 60,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 100,
  }))
  previous[10] = { ...previous[10], open: 100.5, close: 100 }
  const candles = [
    ...previous,
    { time: startOfDay, open: 99.9, high: 101, low: 99.5, close: 100.8, volume: 100 },
  ]
  const d = {
    ...data,
    symbol: 'NIFTY',
    exchange: 'NSE_INDEX',
    session,
    candles,
    observedAt: startOfDay + 60,
  }
  const row = evaluateScreen(
    d,
    definition([condition({ field: 'candle_pattern', pattern: 'engulfing' }, 'eq', 1)]),
    d.observedAt
  )
  expect(row.state).toBe('unavailable')
})
it('does not substitute an older daily candle for a missing preceding session', () => {
  const screen = definition([condition({field:'prior_day_high'},'lt',200)])
  const daily = [{...data.candles[0],time:start-10*86400}]
  const row=evaluateScreen({...data,daily},screen,data.observedAt)
  expect(row.state).toBe('unavailable')
  expect(row.values.session_change_pct).toBeNull()
})
