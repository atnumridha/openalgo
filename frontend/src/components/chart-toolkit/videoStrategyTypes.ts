export type VideoStrategyId =
  | 'fvg'
  | 'ob'
  | 'sweep'
  | 'bos'
  | 'choch'
  | 'ifvg'
  | 'breaker'
  | 'ote'
  | 'krm'
  | 'silver-bullet'
  | 'supply-demand'
  | 'support-resistance'
  | 'breakout'
  | 'crt'
  | 'po3'
export type VideoStatus =
  | 'watching'
  | 'waiting'
  | 'entry'
  | 'invalidated'
  | 'target'
  | 'expired'
  | 'ambiguous'
  | 'unpriced'
export interface VideoBar {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}
export interface VideoStrategy {
  id: VideoStrategyId
  name: string
  supported: boolean
  variant: boolean
  rule: string
  missing: string
  source: string
}
export interface VideoEvent {
  id: string
  strategy: VideoStrategyId
  kind: number
  side: number
  status: VideoStatus
  createdAt: number
  barTime: number
  createdIndex: number
  confirmedAt: number | null
  confirmedBar: number | null
  entryAt: number | null
  entryBar: number | null
  watch: number | null
  entry: number | null
  stop: number | null
  target: number | null
  low: number
  high: number
  trigger: number | null
  evidence: number[]
  reason: string
  priced: boolean
}
export interface VideoReading extends VideoStrategy {
  status: VideoStatus | 'incomplete' | 'unavailable' | 'none'
  event: VideoEvent | null
  reason: string
}
export interface VideoGuideResult {
  asOf: number
  seconds: number
  available: boolean
  reason: string
  closedTime: number | null
  lastBarTime: number | null
  readings: VideoReading[]
  events: VideoEvent[]
  history: { id: string; strategy: VideoStrategyId; at: number; status: VideoStatus }[]
}
export interface VideoGuideOptions {
  seconds: number
  asOf: number
  tickSize: number
  session?: { start: number; end: number; offset: number } | null
  indian?: boolean
  standard?: boolean
}
export interface VideoSelection {
  event: VideoEvent | null
  action: string
  reason: string
  mixed: boolean
}
