import type {
  BookBar,
  BookContext,
  BookInstrument,
  BookRisk,
  BookSegment,
} from '../book-pattern-guide/types'
export type {
  BookBar as StrategyBar,
  BookContext as StrategyContext,
} from '../book-pattern-guide/types'
export type Side = 'long' | 'short'
export interface StrategySession {
  start: number
  end: number
  offset: number
}
export type RowState = 'confirmed' | 'waiting' | 'timeframe' | 'needs-data' | 'needs-context'
export interface StrategyDefinition {
  id: string
  number: number
  title: string
  category: string
  pages: number[]
  entry: string
  stop: string
  target: string
  exit: string
  timeframe: string
  requirements: string[]
  notes: string[]
  local: string[]
}
export interface Pivot {
  index: number
  knownAt: number
  price: number
  kind: 'high' | 'low'
}
export interface Frame {
  bar: BookBar
  index: number
  ema: Record<number, number | undefined>
  sma: Record<number, number | undefined>
  atr?: number
  atr7?: number
  rsi?: number
  wr?: number
  macd?: number
  macdSignal?: number
  upper?: number
  lower?: number
  basis?: number
  width?: number
  volumeMean?: number
  vo?: number
  vwap?: number
  vwapSD?: number
  pivot?: number
  r1?: number
  r2?: number
  s1?: number
  s2?: number
  cprLow?: number
  cprHigh?: number
  st7?: number
  st10?: number
  st7Side: Side
  st10Side: Side
  donHigh?: number
  donLow?: number
  donMid?: number
  conversion?: number
  base?: number
  rawSpanA?: number
  rawSpanB?: number
  cloudA?: number
  cloudB?: number
  haOpen: number
  haClose: number
  haHigh: number
  haLow: number
  sar?: number
  highs: Pivot[]
  lows: Pivot[]
  fractalHighs: Pivot[]
  fractalLows: Pivot[]
  trend: 'bull' | 'bear' | 'neutral'
  day: number
  minute: number
  sessionIndex: number
}
export interface SuppliedContext {
  /** User-supplied as-of information; never labelled chart detected. */
  strategyId: string
  symbol: string
  exchange?: string
  intervalSeconds: number
  asOf: number
  side: Side
  entry?: number
  stop?: number
  target?: number
  zoneLow?: number
  zoneHigh?: number
  description: string
  kind: 'elliott' | 'gann' | 'renko' | 'sector' | 'repo' | 'gap-zone' | 'risk'
  newRate?: number
  previousRate?: number
  liquidityConfirmed?: boolean
  touchCount?: number
  nextSessionExitAt?: number
}
export interface OptionEvidence {
  symbol: string
  exchange: string
  underlying: string
  expiry: string
  strike: number
  optionType: 'CE' | 'PE'
  /** Exact dated baseline qualification. Current spot/OI is insufficient for a past selection. */
  selection?: {
    time: number
    kind: 'atm' | 'highest-oi' | 'near40' | 'near125' | 'near150' | 'chosen-call' | 'otm'
    source: 'verified-history' | 'supplied'
    description: string
    exitAt?: number
  }
  selections?: NonNullable<OptionEvidence['selection']>[]
  vix?: { value: number; time: number }
  pair?: { symbol: string; bars: BookBar[] }
  combined?: { bars: BookBar[]; volumeVerified: boolean }
  expiryTime?: number
}
export interface StrategyExtras {
  historical?: boolean
  session?: StrategySession | null
  higher?: {
    bars: BookBar[]
    intervalSeconds: number
    observedAt: number
    symbol: string
    exchange?: string
  }
  underlying?: {
    bars: BookBar[]
    intervalSeconds: number
    observedAt: number
    symbol: string
    exchange?: string
  }
  option?: OptionEvidence
  supplied?: SuppliedContext[]
  dataReasons?: string[]
}
export interface Strategy51Settings {
  selected: string
  showPending: boolean
  showOtherSetups: boolean
  cleanChart: boolean
  fullHistory: boolean
  showTrendLines: boolean
  labelLookback: number
  localTargets: boolean
  targetR: number
  minRR: number
  planExpiryBars: number
  equity: number
  riskPercent: number
  fixedCost: number
  perUnitCost: number
  slippagePrice: number
  instrument?: BookInstrument
  instrumentScope?: string
  localStructures: boolean
  voFast: number
  voSlow: number
  donchianPeriod: number
  supertrendMultiplier: number
  squeezePercent: number
  rangeBars: number
  volumeFactor: number
  touchATR: number
  supplied: SuppliedContext[]
}
export interface Candidate {
  strategyId: string
  side: Side
  signalIndex: number
  index: number
  entry: number
  stop?: number
  target?: number
  targetMethod: string
  targetOrigin?: 'source' | 'local' | 'supplied'
  stopMethod: string
  expected: string
  next: string
  exitRule: string
  notes: string[]
  points: { index: number; price: number; role: string }[]
  segments?: BookSegment[]
  conditionalExit?:
    | 'bb-mid'
    | 'supertrend7'
    | 'supertrend10'
    | 'rsi70'
    | 'rsi30'
    | 'rsi-return70'
    | 'rsi-return30'
    | 'ema14'
    | 'vwap'
  timeLimitSeconds?: number
  cutoffMinute?: number
  nextSessionExitMinute?: number
  exitAt?: number
  partialAtR?: number
  breakevenAfterPartial?: boolean
  breakevenAtPremiumFraction?: number
  supplied?: boolean
}
export interface StrategyRow {
  definition: StrategyDefinition
  state: RowState
  reason: string
  next: string
  candidate?: Candidate
  notes: string[]
}
export interface StrategyEvent extends Candidate {
  id: string
  time: number
  signalTime: number
  name: string
}
export interface StrategyPlan extends StrategyEvent {
  stop: number
  rr?: number
  createdAt: number
  createdIndex: number
  status:
    | 'active'
    | 'stop-touched'
    | 'target-touched'
    | 'ambiguous'
    | 'conditional-exit'
    | 'time-exit'
    | 'expired'
  terminalTime?: number
  sizing?: BookRisk
  partialTime?: number
  currentStop?: number
}
export interface Strategy51Result {
  rows: StrategyRow[]
  events: StrategyEvent[]
  plan?: StrategyPlan
  lastPlan?: StrategyPlan
  readiness: 'ready' | 'last-session' | 'unavailable'
  viewMode?: 'live' | 'closed-session' | 'history'
  tickSize?: number
  reason: string
  next: string
  expected: string
  trend: 'bull' | 'bear' | 'neutral' | 'unavailable'
  completedAt?: number
  forming?: { time: number; price: number }
  trendLines: BookSegment[]
  scope: string
  processed: number
  frames?: Frame[]
}
export interface EvaluationInput {
  frames: Frame[]
  index: number
  context: BookContext
  settings: Strategy51Settings
  extras: StrategyExtras
}
