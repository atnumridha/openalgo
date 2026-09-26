export type ResearchCandidateId = 'trend_breakout' | 'vwap_pullback'

export interface CostSchedule {
  schedule_id: string
  source: string
  effective_from: string
  effective_to: string
  brokerage_per_order: number
  exchange_rate: number
  sebi_rate: number
  gst_rate: number
  stamp_buy_rate: number
  stt_sell_rate: number
  slippage_bps: number
}

export interface ResearchDataset {
  id: number
  name: string
  provider: string
  content_hash: string
  row_count: number
  session_count: number
  start: string
  end: string
  quality: 'candle_screening'
  created_at: string
}

export interface ResearchCandidate {
  id: ResearchCandidateId
  name: string
  description: string
  defaults: Record<string, number>
}

export interface ResearchMetrics {
  trade_count: number
  net_pnl: number | null
  expectancy: number | null
  profit_factor: number | null
  profit_factor_unbounded?: boolean
  max_drawdown_pct: number | null
  max_losing_streak: number | null
  win_rate: number | null
  ending_equity: number | null
  exposure_bars?: number
  max_observed_open_drawdown_pct?: number
}

export interface ResearchReport {
  metrics: ResearchMetrics
  trades: Array<{
    symbol: string
    signal_at: string
    entry_bar_at: string
    exit_at: string
    quantity: number
    entry_price: number
    exit_price: number
    gross_pnl: number
    costs: number
    net_pnl: number
    exit_reason: string
  }>
  rejections: Record<string, number>
  qualification: { eligible_for_live: false; reasons: string[] }
  oos?: ResearchReport
  stress?: ResearchReport
  bootstrap?: {
    method: string
    seed: number
    net_pnl_p05: number | null
    net_pnl_p95: number | null
    warning: string
  }
  split?: {
    kind: 'development' | 'final'
    development_sessions?: number
    training_sessions?: number
    oos_sessions?: number
    evaluated_sessions?: number
    holdout_sessions: number
    last_development_date?: string
    holdout_consumed?: boolean
  }
}

export interface ResearchRun {
  id: number
  dataset_id: number
  candidate: ResearchCandidateId
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
  kind: 'development' | 'final'
  configuration_hash: string
  configuration?: {
    candidate: ResearchCandidateId
    parameters: Record<string, number>
    costs: CostSchedule
    seed: number
    engine_version: string
    dataset_hash: string
    risk_policy_version: string
  }
  frozen_at: string | null
  parent_run_id: number | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  error: string | null
  report?: ResearchReport | null
}

export interface ResearchOverview {
  datasets: ResearchDataset[]
  runs: ResearchRun[]
  candidates: ResearchCandidate[]
  worker: { online: boolean; last_seen: string | null }
  limits: Record<string, number>
}

export interface ResearchRunRequest {
  dataset_id: number
  candidate: ResearchCandidateId
  parameters: Record<string, number>
  costs: CostSchedule
  seed: number
}

export interface RiskAccount {
  equity: number
  peak_equity: number
  drawdown: number
  drawdown_headroom: number
  first_remaining: number
  later_remaining: number
  daily_remaining: number
  paused: boolean
  pause_reason: string | null
  session_day: string
  reserved_risk: number
}

export interface TradingRisk {
  enabled: boolean
  policy: {
    capital: number
    first_trade_limit: number
    later_trades_limit: number
    daily_limit: number
    drawdown_pct: number
    cash_buffer_pct: number
    version: string
  }
  costs: CostSchedule | null
  accounts: { sandbox: RiskAccount | null; live: RiskAccount | null }
}
