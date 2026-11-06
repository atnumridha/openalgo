import type { Bar } from '../chart-toolkit/model'
import type { PlanSession } from '../neo-desk/chartTradePlan'
import type { PatternSelection } from '../chart-toolkit/candlePatterns'
export const FRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '1d'] as const
export type Frame = (typeof FRAMES)[number]
export const FIELDS = [
  ['close', 'Close'],
  ['open', 'Open'],
  ['high', 'High'],
  ['low', 'Low'],
  ['volume', 'Volume'],
  ['bar_change_pct', 'Bar change %'],
  ['session_change_pct', 'Session change %'],
  ['ema', 'EMA'],
  ['sma', 'SMA'],
  ['rsi', 'RSI 14'],
  ['macd', 'MACD'],
  ['signal', 'MACD signal'],
  ['histogram', 'MACD histogram'],
  ['atr', 'ATR 14'],
  ['bb_upper', 'Bollinger upper'],
  ['bb_lower', 'Bollinger lower'],
  ['relative_volume', 'Relative volume'],
  ['highest_high', 'Prior highest high'],
  ['lowest_low', 'Prior lowest low'],
  ['prior_day_high', 'Previous session high'],
  ['prior_day_low', 'Previous session low'],
  ['support', 'Confirmed support'],
  ['resistance', 'Confirmed resistance'],
  ['candle_pattern', 'Candle pattern (1 bullish / −1 bearish)'],
] as const
export type Field = (typeof FIELDS)[number][0]
export interface FieldRef {
  field: Field
  period?: number
  offset?: 0 | 1
  pattern?: PatternSelection
}
export type Operand = number | FieldRef
export const OPS = [
  ['gt', '>'],
  ['gte', '≥'],
  ['lt', '<'],
  ['lte', '≤'],
  ['eq', '='],
  ['cross_above', 'Crosses above'],
  ['cross_below', 'Crosses below'],
  ['within_pct', 'Within %'],
] as const
export interface Condition {
  type: 'condition'
  id: string
  enabled?: boolean
  left: Operand
  op: (typeof OPS)[number][0]
  right: Operand
  tolerance?: number
}
export interface RuleGroup {
  type: 'group'
  id: string
  enabled?: boolean
  op: 'all' | 'any'
  children: RuleNode[]
}
export type RuleNode = Condition | RuleGroup
export interface Instrument {
  symbol: string
  exchange: string
  name?: string
}
export interface Universe {
  kind: 'stored' | 'watchlist' | 'nifty50' | 'custom'
  id?: number
  items?: Instrument[]
}
export interface ScreenDefinition {
  version: 1
  name: string
  interval: Frame
  universe: Universe
  intent: 'observe' | 'bullish' | 'bearish'
  rule: RuleGroup
}
export interface SavedScreen {
  id: number
  name: string
  revision: number
  definition: ScreenDefinition
}
export interface ScanDataset extends Instrument {
  interval: Frame
  source: string
  observedAt: number
  tickSize?: number
  session?: PlanSession | null
  candles: Bar[]
  daily: Bar[]
  error?: string
}
export interface ScanRow extends Instrument {
  state: 'match' | 'no-match' | 'unavailable'
  fresh: boolean
  direction: string
  time: number | null
  observedAt: number
  source: string
  reason: string
  values: Partial<Record<Field, number | null>>
  pattern?: PatternSelection
}
export const frameSeconds = (frame: Frame) =>
  Number(frame.slice(0, -1)) * (frame.endsWith('m') ? 60 : frame.endsWith('h') ? 3600 : 86400)
export const instrumentKey = (item: Instrument) => `${item.exchange}:${item.symbol}`
