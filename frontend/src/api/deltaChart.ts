import { isAxiosError } from 'axios'
import { webClient } from './client'

export interface DeltaChartOrder {
  id: string
  side: 'buy' | 'sell'
  size: number
  unfilled: number
  type: 'limit_order' | 'market_order'
  kind: 'entry' | 'sl' | 'target'
  price: number | null
  post_only: boolean
  reduce_only: boolean
  state: string
  version: string
}
export interface DeltaAutoProtection {
  stop: number
  target: number
  source_time: number
  interval_seconds: number
  reason: string
}
export interface DeltaManagedPlan extends Omit<DeltaAutoProtection, 'reason'> {
  target_mode?: 'fixed' | 'trend' 
  id: string
  status:
    | 'awaiting_entry'
    | 'partial_fill'
    | 'placing_protection'
    | 'active'
    | 'closing'
    | 'cleanup'
    | 'pending'
    | 'blocked'
    | 'completed'
    | 'cancelled'
    | 'rejected'
  message: string
  side: 'buy' | 'sell'
  entry_order_id: string | null
  entry_request_id?: string
  placed_at?: number | null
  entry_price: number | null
  initial_stop: number
  stop_order_id?: string | null
  target_order_id?: string | null
  first_fill_at?: number | null
  manual_entry?: boolean
  smart_profit_tracking?: boolean
  peak_net_inr?: number | null
}
export interface DeltaManageAction {
  plan_id: string
  decision: 'sync' | 'cancel_entry' | 'trail' | 'reduce_risk' | 'exit'
  source_time: number
  stop?: number
}
export interface DeltaManageResult {
  status: 'confirmed' | 'pending' | 'rejected'
  message: string
  plan_id: string
  plan_status: DeltaManagedPlan['status']
  order_id?: string
}
export interface DeltaBackendAutomation {
  owner: 'backend'
  enabled: boolean
  account: string
  symbol: string
  leverage: number
  balance_fraction: number | null
  manual_quantity: number
  generation: string
  status: string
  message: string
  checked_at: number | null
  next_check_at: number | null
  context: {
    source_time?: number
    direction?: string
    higher_direction?: string
    trend_summary?: string
    patterns?: unknown[]
    [key: string]: unknown
  } | null
  events: Array<{
    id: number
    at: number
    kind: string
    source_time?: number | null
    details: Record<string, unknown>
  }>
}
export interface DeltaAutomationRequest {
  symbol: string
  account: string
  enabled: boolean
  leverage?: number
  balance_fraction?: number | null
  manual_quantity?: number
}
export interface DeltaAutomationResult {
  status: 'confirmed'
  automation: DeltaBackendAutomation
}
export interface DeltaChartState {
  connected: boolean
  environment: 'india_prod'
  asof: number
  symbol: string
  account: string
  product: {
    id: number
    symbol: string
    tick_size: number
    contract_value: number
    max_leverage: number
  }
  ticker: { mark: number | null; last: number | null; bid: number | null; ask: number | null }
  sizing?: {
    available_balance: number
    currency: string
    taker_fee_rate?: number
    maker_fee_rate: number
    fee_tax_rate: number
    version: string
  } | null
  accounting?: {
    currency: 'USD'
    balance: number | null
    available_balance: number | null
    position_gross_pnl: number | null
    position_entry_fees: number | null
    standard_exit_fee?: number | null
    scalper_fee_valid_until?: number | null
    estimated_exit_fee?: number | null
    exit_fee_basis?: 'taker' | 'maker'
    estimated_maker_exit_fee: number | null
    position_net_after_fees: number | null
    fee_status: 'verified' | 'incomplete' | 'flat' | 'unavailable'
    message: string
  } | null
  leverage: number | null
  position: {
    version: string
    size: number
    entry: number
    mark: number
    pnl: number | null
    liquidation: number | null
  } | null
  orders: DeltaChartOrder[]
  fills: {
    id: string
    side: 'buy' | 'sell'
    price: number
    size: number
    created_at: string | number
  }[]
  automation?: DeltaBackendAutomation
  managed_plans?: DeltaManagedPlan[]
  receipts?: { request_id: string; status: 'confirmed' | 'rejected'; message: string }[]
  pending?: { request_id: string; action: string; message: string }[]
  message?: string
}
export interface DeltaOrderReference {
  id: string
  version: string
}
export interface DeltaChartAction {
  request_id: string
  symbol: string
  account: string
  action: 'entry' | 'close' | 'protect' | 'edit' | 'cancel' | 'adopt'
  entry_mode?: 'manual'
  target_mode?: 'fixed' | 'trend'
  side?: 'buy' | 'sell'
  size?: number
  order_type?: 'limit_order' | 'market_order'
  price?: number
  existing_stop?: DeltaOrderReference | null
  existing_target?: DeltaOrderReference | null
  auto_protection?: DeltaAutoProtection
  balance_fraction?: 0.1 | 0.25 | 0.5 | 0.75 | 1
  sizing_version?: string
  leverage?: number
  stop?: number
  target?: number
  order_id?: string
  version?: string
  position_version?: string
}
export interface DeltaChartActionResult {
  status: 'confirmed' | 'pending' | 'rejected'
  message: string
  request_id: string
  order_id?: string
  plan_id?: string
  placed_at?: number | null
}
export const deltaChartApi = {
  async automation(body: DeltaAutomationRequest): Promise<DeltaAutomationResult> {
    return (await webClient.post<DeltaAutomationResult>('/delta-chart/api/automation', body)).data
  },
  async state(symbol: string, signal?: AbortSignal): Promise<DeltaChartState> {
    return (
      await webClient.get<DeltaChartState>('/delta-chart/api/state', { params: { symbol }, signal })
    ).data
  },
  async action(body: DeltaChartAction): Promise<DeltaChartActionResult> {
    try {
      return (await webClient.post<DeltaChartActionResult>('/delta-chart/api/action', body)).data
    } catch (error) {
      if (isAxiosError<DeltaChartActionResult>(error)) {
        const result = error.response?.data
        if (result?.status === 'rejected' && result.request_id === body.request_id) return result
      }
      throw error
    }
  },
  async manage(body: DeltaManageAction): Promise<DeltaManageResult> {
    try {
      return (await webClient.post<DeltaManageResult>('/delta-chart/api/manage', body)).data
    } catch (error) {
      if (isAxiosError<DeltaManageResult>(error)) {
        const result = error.response?.data
        if (result?.status === 'rejected' && result.plan_id === body.plan_id) return result
      }
      throw error
    }
  },
  async connection(
    api_key: string,
    api_secret: string
  ): Promise<{ connected: boolean; message?: string }> {
    return (await webClient.post('/delta-chart/api/connection', { api_key, api_secret })).data
  },
}
