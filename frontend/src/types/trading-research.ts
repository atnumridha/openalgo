export type ResearchCandidateId = 'trend_breakout' | 'trend_breakout_filtered' | 'vwap_pullback'
export type ResearchRunKind = 'development' | 'optimization' | 'ml' | 'final'

export interface MLSettings {
  folds: number
  min_train_sessions: number
  estimators: number
  threshold: number
  max_hold_minutes?: number
}

export interface PredictionAccuracy {
  labelled_observations: number
  unlabelled_observations: number
  accuracy_pct: number | null
  precision_pct: number | null
  recall_pct: number | null
  majority_baseline_pct: number | null
}

export interface ResearchOptimizationReport {
  candidate_count: number
  best_index: number
  max_candidates: number
  holdout_consumed: false
  best_report: ResearchReport
  best_configuration: { parameters: Record<string, number> }
  candidates: Array<{
    index: number
    parameters: Record<string, number>
    complete: boolean
    metrics: ResearchMetrics
    configuration_hash: string
  }>
}

export interface CostSchedule {
  exchange?: 'NFO' | 'BFO' | 'MCX'
  broker?: 'kotak'
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
  initial_capital?: number
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
  signal_bar_minutes?: number
  execution_bar_minutes?: number
  ambiguous_exit_count?: number
}

export interface ResearchReport {
  session_analytics?: {
    session_count: number
    annualization_sessions: number
    convention: string
    metrics: {
      cagr?: number | null
      volatility?: number | null
      sharpe?: number | null
      sortino?: number | null
    }
  }
  ml?: {
    artifact?: { feature_importance?: Record<string, number>; weighting?: string }
    diagnostics?: {
      brier_score: number | null
      baseline_brier_score?: number | null
      baseline_difference_95?: { lower_95: number; upper_95: number } | null
      reliability: Array<{ mean_prediction: number; mean_actual: number; observations: number }>
    }
    accuracy: PredictionAccuracy
    model_hash: string
    prediction_hash: string
    signal_count: number
    deployment_supported: boolean
    deployment_reason: string
    cross_validation: {
      model_metadata: {
        folds_report: Array<{
          fold: number
          train_observations: number
          validation_observations: number
          accuracy: PredictionAccuracy
        }>
      }
    }
  }
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
  kind: ResearchRunKind
  configuration_hash: string
  configuration?: {
    capital?: number
    run_kind?: ResearchRunKind
    ml_settings?: MLSettings
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
  report?: ResearchReport | ResearchOptimizationReport | null
}

export interface ResearchOverview {
  capabilities?: {
    optimization_max_candidates: number
    ml: { available: boolean; reason?: string; sklearn_version?: string }
    ml_live: boolean
  }
  datasets: ResearchDataset[]
  runs: ResearchRun[]
  candidates: ResearchCandidate[]
  worker: { online: boolean; last_seen: string | null }
  limits: Record<string, number>
}

export interface ResearchRunRequest {
  capital: number
  run_kind?: Exclude<ResearchRunKind, 'final'>
  parameter_grid?: Record<string, number[]>
  ml_settings?: MLSettings
  dataset_id: number
  candidate: ResearchCandidateId
  parameters: Record<string, number>
  costs: CostSchedule
  seed: number
}

export interface RiskAccount {
  capital: number
  equity: number
  peak_equity: number
  drawdown: number
  drawdown_headroom: number
  first_remaining: number | null
  later_remaining: number | null
  policy_version?: string
  per_trade_limit?: number
  daily_limit?: number
  day_start_equity?: number
  risk_reduced?: boolean
  drawdown_pct?: number
  consecutive_losses?: number
  daily_stopped?: boolean
  daily_stop_reason?: string | null
  policy_transition_blocked?: string | null
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
    per_trade_limit?: number
    first_trade_limit: number
    later_trades_limit: number
    daily_limit: number
    drawdown_pct: number
    cash_buffer_pct: number
    version: string
  }
  costs: CostSchedule | null
  costs_by_exchange?: Partial<Record<'NFO' | 'BFO' | 'MCX', CostSchedule>>
  accounts: { sandbox: RiskAccount | null; live: RiskAccount | null }
}
