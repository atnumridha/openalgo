/** Independent, UTC-second data contract. No broker/order actions exist in this module. */
export interface BookBar {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
  repaired?: boolean
  /** Validated session close, UTC seconds; absent uses nominal interval. */
  closeTime?: number
}
export type BookSide = 'long' | 'short'
export type BookTrend = 'bull' | 'bear' | 'neutral' | 'unavailable'
export interface BookInstrument {
  kind: 'linear' | 'inverse' | 'nonlinear' | 'index'
  /** valuePerPriceUnit is already per underlying unit OR per contract as explicitly selected. Never multiply it by lotSize. */
  unitDefinition: 'underlying' | 'contract' | 'option-premium'
  accountCurrency?: string
  quoteCurrency?: string
  conversionRate?: number
  valuePerPriceUnit?: number
  quantityStep?: number
  lotSize?: number
  /** Option sizing is allowed only for the premium instrument itself. */
  chartPriceKind?: 'premium' | 'underlying'
}
export interface BookContext {
  symbol: string
  exchange?: string
  intervalSeconds: number
  /** Current wall clock, UTC seconds. Cannot promote a candle without observedAt. */
  now: number
  /** Received history observation time, UTC seconds; caps completed candles. */
  observedAt: number
  /** Live quote time, UTC seconds. Absent means the caller supplies a unified observedAt. */
  quoteObservedAt?: number
  sourceReady: boolean
  connected: boolean
  marketOpen: boolean
  chartType: 'standard' | 'synthetic'
  tickSize: number
  instrument?: BookInstrument
}
export interface BookSettings {
  pivotLeft: number
  pivotRight: number
  pivotSpacing: number
  atrPeriod: number
  levelToleranceATR: number
  equalCandleATR: number
  minToleranceTicks: number
  shapeMinBars: number
  shapeMaxBars: number
  convergenceRatio: number
  parallelMaxRatio: number
  poleMinATR: number
  poleMinBars: number
  poleMaxBars: number
  flagMinBars: number
  flagMaxBars: number
  flagMaxRetracement: number
  cupMinBars: number
  cupMaxBars: number
  handleMinBars: number
  handleMaxBars: number
  rimToleranceATR: number
  cupMinDepthATR: number
  cupMaxDepthFraction: number
  handleMaxDepthFraction: number
  dojiBody: number
  smallBody: number
  longBody: number
  negligibleWick: number
  dominantWickRatio: number
  marubozuBody: number
  marubozuWick: number
  spinningWick: number
  averageBodyPeriod: number
  strictRangeEngulfing: boolean
  gapPolicy: 'explicit' | 'continuous'
  candleTriggerBars: number
  retestBars: number
  failedBreakoutBars: number
  levelLookback: number
  multiSwingMinBars: number
  multiSwingMaxBars: number
  reboundATR: number
  headDepthATR: number
  shoulderToleranceATR: number
  maType: 'ema' | 'sma'
  maFast: number
  maSlow: number
  maSlopeBars: number
  trendWarmup: number
  rsiPeriod: number
  macdFast: number
  macdSlow: number
  macdSignal: number
  volumePeriod: number
  volumeExpansion: number
  rsiFilter: boolean
  macdFilter: boolean
  volumeFilter: boolean
  divergenceMinBars: number
  divergenceMaxBars: number
  stopBufferATR: number
  targetR: number
  minRR: number
  planExpiryBars: number
  staleQuoteSeconds: number
  equity: number
  riskPercent: number
  fixedCost: number
  perUnitCost: number
  slippagePrice: number
  showPending: boolean
  showNeutral: boolean
  showTrendLines: boolean
  fullHistory: boolean
  labelLookback: number
  maxDrawings: number
  maxPolylines: number
  maxLabels: number
  maxLines: number
  disabledPatterns: string[]
}
export interface BookPoint {
  time: number
  price: number
  index: number
  role: string
  recognitionTime?: number
}
export interface BookSegment {
  from: BookPoint
  to: BookPoint
  role: string
}
export interface BookPivot {
  side: 'high' | 'low'
  index: number
  time: number
  price: number
  recognitionIndex: number
  recognitionTime: number
}
export interface BookLevel {
  id: string
  side: 'support' | 'resistance'
  price: number
  contacts: BookPivot[]
  recognitionTime: number
  recognitionIndex: number
}
export type BookTargetMethod = 'r-multiple' | 'measured' | 'support-resistance' | 'r-fallback'
export interface BookFormation {
  patternId: string
  name: string
  side: BookSide | 'neutral'
  sourcePhotos: number[]
  kind: 'candle' | 'shape' | 'level' | 'trendline'
  mode: 'continuation' | 'reversal' | 'neutral'
  startIndex: number
  endIndex: number
  recognitionIndex: number
  trigger: number
  stopAnchor: number
  stopMethod: string
  targetMethod: BookTargetMethod
  measuredHeight?: number
  measuredBoundary?: number
  scale: number
  contacts: number
  rank: number
  points: BookPoint[]
  segments: BookSegment[]
  notes: string[]
  confirmationRule?:
    | 'later-close'
    | 'inverted-body'
    | 'next-boundary'
    | 'next-extreme'
    | 'retest'
    | 'shape-close'
  nextOpenBoundary?: number
  line?: [BookPivot, BookPivot]
  upperLine?: [BookPivot, BookPivot]
  lowerLine?: [BookPivot, BookPivot]
  stopCheckFrom?: number
  /** Family window stays live until the first breakout, then its geometry freezes. */
  shapeWindow?: { startIndex: number; minBars: number; maxBars: number }
}
export interface BookEvent extends BookFormation {
  id: string
  formationStart: number
  formationEnd: number
  recognitionTime: number
  status: 'pending' | 'confirmed' | 'expired' | 'invalidated'
  nextCondition: string
  confirmationTime?: number
  confirmationIndex?: number
  qualificationReason?: string
  armingId?: string
  armedAt?: number
  armedIndex?: number
  confirmationId?: string
  qualificationId?: string
  qualificationTime?: number
  parentEventId?: string
  priorTrend?: BookTrend
}
export interface BookRisk {
  priceRisk: number
  priceReward: number
  rr: number
  budget?: number
  lossPerUnit?: number
  quantity?: number
  lots?: number
  estimatedRiskCash?: number
  estimatedRewardCash?: number
  unavailableReasons: string[]
  notes: string[]
}
export interface BookPlan {
  id: string
  eventId: string
  side: BookSide
  name: string
  createdAt: number
  createdIndex: number
  entry: number
  stop: number
  target: number
  rr: number
  targetMethod: BookTargetMethod
  stopMethod: string
  status: 'active' | 'stop-touched' | 'target-touched' | 'ambiguous' | 'expired'
  terminalTime?: number
  terminalIndex?: number
  sizing?: BookRisk
  notes: string[]
}
export interface BookIndicatorSnapshot {
  trend: BookTrend
  maFast?: number
  maSlow?: number
  rsi?: number
  macd?: number
  macdSignal?: number
  volumeMean?: number
  atr?: number
}
export interface BookObservation {
  id: string
  type: string
  time: number
  side?: BookSide
  text: string
  sourcePhotos: number[]
  points?: BookPoint[]
  parentEventId?: string
}
export interface BookFilterState {
  name: 'rsi' | 'macd' | 'volume'
  state: 'off' | 'pass' | 'fail' | 'unavailable'
  value?: number
  baseline?: number
}
export interface BookAlert {
  id: string
  type:
    | 'confirmed-pattern'
    | 'qualified-plan'
    | 'stop-reference-touch'
    | 'target-reference-touch'
    | 'ambiguous-reference-touch'
  time: number
  eventId: string
  patternId: string
  side: BookSide | 'neutral'
  text: string
}
export interface BookGuideResult {
  events: BookEvent[]
  pendingEvents: BookEvent[]
  visibleEvents: BookEvent[]
  observations: BookObservation[]
  activePlan?: BookPlan
  lastTerminalPlan?: BookPlan
  alternatives: BookEvent[]
  explanation: string
  nextCondition: string
  alerts: BookAlert[]
  readiness: 'ready' | 'unavailable' | 'last-session'
  unavailableReasons: string[]
  indicators: BookIndicatorSnapshot
  filters: BookFilterState[]
  levels: BookLevel[]
  /** Context only: last confirmed rising support / falling resistance, never entry evidence. */
  trendLines?: BookSegment[]
  provisional?: { time: number; price: number; distanceToStop?: number; distanceToTarget?: number }
}
