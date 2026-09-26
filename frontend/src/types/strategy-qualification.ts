import type { CostSchedule } from './trading-research'

export interface QualificationPolicy {
  version: string
  min_final_trades: number
  min_sessions: number
  min_closed_trades: number
  min_profit_factor: number
  max_drawdown_pct: number
  approval_days: number
  max_quote_age_seconds: number
  max_fill_delay_seconds: number
}

export interface QualificationCheck {
  code: string
  passed: boolean
  message: string
  actual?: unknown
  required?: unknown
}

export interface ForwardTrade {
  trade_ref: string
  registered_at: string
  status: string
  session_day: string | null
  net_pnl: number | null
  stressed_net_pnl: number | null
  valid: boolean
  issues: string[]
  orders_count: number
}

export interface QualificationCampaign {
  id: number
  strategy_id: number
  final_run_id: number
  created_at: string
  binding_hash: string
  revision: number
  evidence_digest: string
  status: string
  binding_problem?: string
  binding: {
    costs: CostSchedule
    broker_connection_id: string
    broker: string
    strategy_hash: string
    workflow_hash: string
    source_hash: string
    risk_policy_version: string
  }
  qualification: {
    eligible: boolean
    checks: QualificationCheck[]
    metrics: {
      session_count: number
      closed_trade_count: number
      net_pnl: number | null
      expectancy: number | null
      profit_factor: number | null
      profit_factor_unbounded: boolean
      stressed_net_pnl: number | null
      max_drawdown_pct: number | null
      unresolved_count: number
      invalid_count: number
      risk_breach: boolean
    }
  }
  approval: {
    status: 'approved' | 'invalidated' | 'revoked' | 'expired'
    at: string
    expires_at: string
    reason: string
    invalidation_reason?: string
  } | null
  reconciliation: {
    status: 'current' | 'stale'
    at: string
    reason: string
    costs_confirmed: boolean
    revision: number
    evidence_digest: string
  } | null
  trades?: ForwardTrade[]
}

export interface QualificationOverview {
  campaigns: QualificationCampaign[]
  strategies: Array<{ id: number; name: string }>
  policy: QualificationPolicy
}
