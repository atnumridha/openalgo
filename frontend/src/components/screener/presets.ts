import type { ScreenDefinition, Condition, Operand } from './model'
import { CANDLE_PATTERNS } from '../chart-toolkit/candlePatterns'
const c = (
  left: Operand,
  op: Condition['op'],
  right: Operand,
  extra: Partial<Condition> = {}
): Condition => ({ type: 'condition', id: crypto.randomUUID(), left, op, right, ...extra })
const screen = (
  name: string,
  intent: ScreenDefinition['intent'],
  children: Condition[]
): ScreenDefinition => ({
  version: 1,
  name,
  interval: '1d',
  universe: { kind: 'stored' },
  intent,
  rule: { type: 'group', id: 'root', op: 'all', children },
})
export const makePresets = () => [
  screen('Price rising', 'bullish', [c({ field: 'session_change_pct' }, 'gt', 0)]),
  screen('Price falling', 'bearish', [c({ field: 'session_change_pct' }, 'lt', 0)]),
  screen('EMA 9 / 21 cross', 'bullish', [
    c({ field: 'ema', period: 9 }, 'cross_above', { field: 'ema', period: 21 }),
    c({ field: 'close' }, 'gt', { field: 'ema', period: 21 }),
  ]),
  screen('MACD cross', 'bullish', [c({ field: 'macd' }, 'cross_above', { field: 'signal' })]),
  screen('RSI recovery', 'bullish', [c({ field: 'rsi' }, 'cross_above', 30)]),
  screen('RSI falling', 'bearish', [c({ field: 'rsi' }, 'cross_below', 70)]),
  screen('Volume expansion', 'observe', [c({ field: 'relative_volume', period: 20 }, 'gte', 2)]),
  screen('Range breakout', 'bullish', [
    c({ field: 'close' }, 'gt', { field: 'highest_high', period: 20 }),
  ]),
  screen('Range breakdown', 'bearish', [
    c({ field: 'close' }, 'lt', { field: 'lowest_low', period: 20 }),
  ]),
  screen('Band re-entry', 'bullish', [c({ field: 'close' }, 'cross_above', { field: 'bb_lower' })]),
  screen('Previous session break', 'bullish', [
    c({ field: 'close' }, 'cross_above', { field: 'prior_day_high' }),
  ]),
  screen('Near support', 'bullish', [
    c({ field: 'close' }, 'within_pct', { field: 'support' }, { tolerance: 1 }),
  ]),
  screen('Near resistance', 'bearish', [
    c({ field: 'close' }, 'within_pct', { field: 'resistance' }, { tolerance: 1 }),
  ]),
  ...CANDLE_PATTERNS.map(([pattern, label]) =>
    screen(pattern === 'all' ? 'Bullish candle setup' : label, 'bullish', [
      c({ field: 'candle_pattern', pattern }, 'eq', 1),
    ])
  ),
  screen('Bearish candle setup', 'bearish', [
    c({ field: 'candle_pattern', pattern: 'all' }, 'eq', -1),
  ]),
]
