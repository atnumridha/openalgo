import { webClient } from './client'

export interface MlJobStatus {
  busy: boolean
  job: string | null
  progress: number
  message: string
  error?: string | null
  result?: Record<string, unknown> | null
}
export interface MlCoverage {
  sources: Record<string, Record<string, unknown>>
}
export interface MlSentiment {
  interval: string
  score: number | null
  drivers: Record<string, number>
}
export interface MlModel {
  version: string
  active?: boolean
  promoted?: boolean
  promotion_reason?: string
  [key: string]: unknown
}
export interface MlPrediction {
  time: number
  p_long: number
  p_short: number
  p_wait: number
  sentiment: number | null
  version?: string
}
export type MlAction = 'LONG' | 'SHORT' | 'WAIT'
export interface MlLiveSignal {
  time: number
  p_long?: number
  p_short?: number
  p_wait?: number
  action?: MlAction
  sentiment?: number | null
  closes_at?: number
  ev_pct?: number
  ev_long_pct?: number
  ev_short_pct?: number
  min_edge_pct?: number
  stop_pct?: number
  target_pct?: number
  stop_price?: number
  target_price?: number
  reason?: string
}
export interface MlLiveSource {
  label: string
  status: 'ok' | 'stale' | 'error' | 'catching_up'
  age_seconds: number | null
  newest_time: number | null
  message: string | null
}
export interface MlLiveSnapshot {
  state: 'starting' | 'live'
  symbol?: string
  interval: string
  feed: string
  server_time: number
  sources: Record<string, MlLiveSource>
  computed_at?: number
  price?: number
  price_time?: number
  model_version?: string | null
  model_promoted?: boolean
  promotion_reason?: string | null
  forming?: MlLiveSignal | null
  closed?: MlLiveSignal | null
  sentiment?: MlSentiment & { sources_used: number }
  message?: string | null
}

export type MlMode = 'sandbox' | 'live'

export interface MlSizing {
  ok: boolean
  contracts: number
  notional: number
  margin: number
  leverage: number
  risk_amount: number
  risk_budget: number
  entry_fee: number
  exit_fee_in_window: number
  exit_fee_after_window: number
  voucher_if_in_window: number
  loss_at_stop: number
  profit_at_target: number
  reward_risk_after_fees: number | null
  capped_by_leverage: boolean
  reason: string | null
}

export interface MlSuggestion {
  symbol: string
  openalgo_symbol: string
  interval: string
  mode: MlMode
  action: MlAction
  price: number
  snapshot_age_seconds: number
  model_version: string | null
  model_promoted: boolean
  promotion_reason: string | null
  p_long: number | null
  p_short: number | null
  p_wait: number | null
  ev_pct: number | null
  min_edge_pct: number | null
  stop_pct: number | null
  target_pct: number | null
  hold_minutes: number
  signal_time: number | null
  expires_at: number | null
  message: string | null
  entry_price?: number
  stop_price?: number
  target_price?: number
  balance?: number | null
  balance_source?: string
  contract_value?: number
  sizing: MlSizing | null
  tradable: boolean
}

export interface MlOpenTrade {
  key: string
  strategy_id: number
  run_id: number
  leg_id: number
  mode: MlMode
  symbol: string
  side: 'LONG' | 'SHORT'
  entry_status: string
  contracts: number
  entry_price: number | null
  last_price: number | null
  stop_price: number | null
  target_price: number | null
  trail_active: boolean
  gross_pnl: number
  fees_paid: number
  exit_fee_now: number
  exit_fee_after_window: number
  window_remaining_minutes: number | null
  voucher_now: number
  net_pnl: number
  pnl_pct: number
  held_minutes: number
  interval: string | null
  exit_kind: string | null
}

export interface MlClosedTrade {
  mode: MlMode
  symbol: string
  side: 'LONG' | 'SHORT'
  contracts: number
  entry_price: number
  exit_price: number
  reason: string
  opened_at: string | null
  closed_at: string | null
  move_pct: number
}

export interface MlSettings {
  symbols: string[]
  retrain_enabled: boolean
  retrain_hour_ist: number
  retrain_minute_ist: number
  risk_pct: number
  max_leverage: number
  sandbox_balance_usd: number
  smart_exit_enabled: boolean
  smart_exit_confirmations: number
  max_hold_minutes: number
  daily_loss_limit_pct: number
  breakeven_buffer_pct: number
  fee_gst_pct: number
  fee_scalper_offer: boolean
  fee_scalper_minutes_major: number
  fee_scalper_minutes_other: number
  fee_diwali_offer: boolean
  fee_voucher_earned_month: number
  fee_premium_cap_pct: number
  last_retrain_status: string | null
}

export interface MlTradeResult {
  status: 'success' | 'error'
  message: string
  data?: { ok: boolean; message: string; suggestion?: MlSuggestion }
}

async function getData<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const response = await webClient.get<{ status: string; data?: T; message?: string }>(path, {
    params,
  })
  if (response.data.status !== 'success' || !response.data.data)
    throw new Error(response.data.message || 'ML request failed')
  return response.data.data
}

export const mlSignalsApi = {
  status: () => getData<MlJobStatus>('/ml/api/status'),
  coverage: () => getData<MlCoverage>('/ml/api/coverage'),
  sentiment: (interval: string, symbol?: string) =>
    getData<MlSentiment>('/ml/api/sentiment', { interval, ...(symbol ? { symbol } : {}) }),
  live: (interval: string, symbol?: string) =>
    getData<MlLiveSnapshot>('/ml/api/live', { interval, ...(symbol ? { symbol } : {}) }),
  models: (symbol?: string) =>
    getData<{ models: MlModel[] }>('/ml/api/models', symbol ? { symbol } : undefined),
  labels: (params: Record<string, unknown>) =>
    getData<Record<string, unknown>>('/ml/api/labels/preview', params),
  predict: (params: Record<string, unknown>) =>
    getData<{ data: MlPrediction[] }>('/ml/api/predict', params),
  refresh: (symbol?: string) => webClient.post('/ml/api/data/refresh', symbol ? { symbol } : {}),
  search: (symbol?: string) =>
    webClient.post<{ status: string; data?: Record<string, unknown> }>(
      '/ml/api/search',
      symbol ? { symbol } : {}
    ),
  train: (payload: Record<string, unknown>) => webClient.post('/ml/api/train', payload),
  activate: (version: string, symbol?: string) =>
    webClient.post(
      `/ml/api/models/${encodeURIComponent(version)}/activate`,
      symbol ? { symbol } : {}
    ),
  suggestions: (interval: string, mode: MlMode) =>
    getData<MlSuggestion[]>('/ml/api/suggestions', { interval, mode }),
  trades: () => getData<{ open: MlOpenTrade[]; closed: MlClosedTrade[] }>('/ml/api/trades'),
  /** Resolves with the server's answer whether or not the trade was placed. */
  trade: async (payload: {
    symbol: string
    interval: string
    mode: MlMode
    action: MlAction
    contracts: number
  }): Promise<MlTradeResult> => {
    try {
      const response = await webClient.post<MlTradeResult>('/ml/api/trade', payload)
      return response.data
    } catch (error) {
      const data = (error as { response?: { data?: MlTradeResult } }).response?.data
      if (data?.message) return data
      throw error
    }
  },
  closeTrade: (runId: number, legId: number) =>
    webClient.post<{ status: string; message: string }>(`/ml/api/trades/${runId}/${legId}/close`),
  settings: () => getData<MlSettings>('/ml/api/settings'),
  saveSettings: async (changes: Partial<MlSettings>) => {
    try {
      const response = await webClient.post<{ status: string; message?: string; data: MlSettings }>(
        '/ml/api/settings',
        changes
      )
      return response.data
    } catch (error) {
      const data = (
        error as { response?: { data?: { status: string; message?: string; data: MlSettings } } }
      ).response?.data
      if (data) return data
      throw error
    }
  },
  retrain: (symbol?: string) => webClient.post('/ml/api/retrain', symbol ? { symbol } : {}),
}
