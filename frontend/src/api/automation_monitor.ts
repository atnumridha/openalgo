import { webClient } from './client'
export interface TechnicalReview {
  profile: string
  bar_at: string
  data_ready: boolean
  direction: string | null
  metrics: Record<string, string | number | null>
  checks: { side: string; label: string; passed: boolean | null }[]
}
export interface MonitorStrategy {
  id: number
  name: string
  mode: string
  automation_state: string
  run_status: string
  live_enabled: boolean
  webhook_locked: boolean
  monitor_status: string
  reason: string
  activity_status?: string
  activity_reason?: string
  live_readiness?: {
    blocked: boolean
    blocker_count: number
    checks: {
      code: string
      label: string
      status: 'passed' | 'blocked' | 'pending'
      message: string
      action_url?: string | null
    }[]
  }
  workflow_id: number | null
  workflow_name: string | null
  workflow_active: boolean
  schedule_status: string
  last_check_at: string | null
  next_check_at: string | null
  check_age_seconds: number | null
  interval_seconds: number | null
  last_check_status: string | null
  last_check_error: string | null
  last_risk_rejection?: { at: string; message: string; details: unknown } | null
  entry_plan?: {
    at: string
    details: {
      context?: {
        structure?: {
          symbol: string
          entry_price: string
          stop_price: string
          planned_gross_loss: string
          objective_r: number
          hard_target: boolean
        }
      }
    }
  } | null
  last_failure: { at: string; message: string } | null
  entry_time: string | null
  exit_time: string | null
  open_run_count: number
  current_run_id: number | null
  open_runs: {
    id: number
    mode: string
    started_at: string
    stop_requested_reason: string | null
  }[]
  configuration: Record<string, unknown>
  rules: string[]
  checkpoint: Record<string, unknown> | null
  evaluation: {
    recorded_at: string
    evaluated_at: string
    stage: string
    reason: string
    technical?: TechnicalReview
    technical_error?: string
    signal_age_seconds?: number
    expected_bar_at?: string
    history?: { symbol: string; interval: string; candles: number; last_bar_at: string }[]
  } | null
}
export interface RiskEvidence {
  available: boolean
  reason?: string
  capital?: number
  policy_version?: string
  costs_configured?: boolean
  pause_reason?: string | null
  daily_stop_reason?: string | null
  managed_scalp_recipe?: string
  ledger?: Record<string, unknown>
}
export interface AutomationMonitor {
  server_time: string
  scheduler: { status: string; error?: string | null }
  live_authorization: { active: boolean; expires_at: string }
  strategies: MonitorStrategy[]
  risk: Record<string, RiskEvidence>
}
export interface LogRecord {
  id: number
  at: string | null
  status: string
  message: string
  details: unknown
  kind?: string
  run_id?: number
  completed_at?: string | null
}
export interface LogPage {
  items: LogRecord[]
  next_cursor: number | null
  notice?: string | null
}
export type LogStream = 'executions' | 'events' | 'orders'
export interface StopResult {
  all_stopped: boolean
  items: {
    strategy_id: number
    name: string
    ok: boolean
    state: string
    close_pending: boolean
    reason: string | null
  }[]
}
export async function getAutomationMonitor(): Promise<AutomationMonitor> {
  return (await webClient.get('/strategy/api/automation/monitor', { timeout: 10000 })).data.data
}
export async function getAutomationLogs(
  id: number,
  stream: LogStream,
  before?: number
): Promise<LogPage> {
  return (
    await webClient.get(`/strategy/api/automation/strategies/${id}/logs`, {
      params: { stream, limit: 25, before_id: before },
      timeout: 10000,
    })
  ).data.data
}
export async function emergencyStopAutomation(): Promise<StopResult> {
  return (
    await webClient.post(
      '/strategy/api/automation/emergency-stop',
      { confirmation: 'STOP ALL' },
      { timeout: 180000 }
    )
  ).data.data
}
