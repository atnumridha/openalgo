import type { Bar } from './model'
import type { PlanSession } from '../neo-desk/chartTradePlan'

export type CandleSide = 'CALL' | 'PUT'
export type CandlePattern = import('./candlePatterns').PatternFamily
export interface CandleCounts {
  targets: number
  stops: number
  timeouts: number
  ambiguous: number
}
export interface CandleEstimate {
  samples: number
  targets: number
  probability: number | null
  lower: number | null
  upper: number | null
}
export interface CandleGeometry {
  pattern: CandlePattern
  name: string
  side: CandleSide
  context: 'aligned' | 'opposing' | 'flat'
  key: string
  entry: number
  stop: number
  target: number
  support: number
  resistance: number
}
export interface CandleSetup extends CandleGeometry {
  time: number
  estimate: CandleEstimate
  qualified: boolean
  reason: string
}
export interface CandleOutcome {
  setup: CandleSetup
  time: number
  result: 'TARGET' | 'STOP' | 'TIMEOUT' | 'UNKNOWN'
  ambiguous: boolean
  price: number | null
  r: number | null
}
export interface CandleModel {
  version: 1
  symbol: string
  exchange: string
  seconds: number
  indian: boolean
  session?: PlanSession | null
  tickSize?: number
  pattern?: import('./candlePatterns').PatternSelection
  trainedThrough: number
  source: string
  counts: Record<string, CandleCounts>
}
export interface CandleOptions {
  symbol: string
  exchange: string
  seconds: number
  indian: boolean
  session?: PlanSession | null
  tickSize?: number
  pattern?: import('./candlePatterns').PatternSelection
  asOf: number
  minProbability?: number
  minSamples?: number
}
export interface CandleStudy {
  bars: Bar[]
  setups: CandleSetup[]
  outcomes: CandleOutcome[]
  signalOutcomes: CandleOutcome[]
  latest: CandleSetup | null
  lastSetup: CandleSetup | null
  active: CandleSetup | null
  lastOutcome: CandleOutcome | null
  support: number | null
  resistance: number | null
  closedTime: number | null
  model: CandleModel
  seedUsed: boolean
}
