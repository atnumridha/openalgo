import { webClient } from './client'

export type DeskMode = 'live' | 'analyze'
export type SetupStrategy = 'trend' | 'opening_reversal'
export type SetupMode = 'confirmed' | 'early'
export type SetupDirection = 'CE' | 'PE'
export interface SetupLevel {
  price: number
  time?: number
  known_at?: number
  kind?: string
  source?: string
}
export interface SetupCandle {
  time: number
  open: number
  high: number
  low: number
  close: number
  closed_at?: number
}
export interface SetupSwing extends SetupLevel {
  kind: 'high' | 'low'
  ordinal: number
}
export interface SetupResult {
  strategy: SetupStrategy | 'opening_swing_reversal'
  version: string
  mode: SetupMode | 'literal'
  stage: string
  direction?: SetupDirection | null
  reason: string
  evidence: string[]
  setup_id?: string | null
  index_entry?: number | null
  trigger?: number | null
  reference?: SetupLevel | null
  signal_candle?: SetupCandle | null
  expires?: number | null
  entry_zone?: { lower: number; upper: number } | null
  invalidation?: number | null
  index_target?: number | null
  projected?: boolean
  directions?: Partial<Record<SetupDirection, SetupResult>>
  numbered_swings?: SetupSwing[]
  source?: string
  chart_fresh?: boolean
  read_only?: boolean
  eligible?: boolean
  consumed?: boolean
  triggered_at?: number
}
export type ExecutionReadiness =
  | string
  | { name?: string; label?: string; reason?: string; ready?: boolean; ok?: boolean }
export type RiskPolicy =
  | { kind: 'cash_budget'; loss_budget: number; target_multiple: number; net_target?: number }
  | { kind: 'structural_premium'; planned_sl: number; planned_target: number }
export interface CashPlanRequest {
  entry: number
  quantity: number
  tick: number
  exchange: string
  loss_budget: number
  target_multiple: number
  lot: number
}
interface CashPlanBase {
  entry: number
  quantity: number
  loss_budget: number
  target_multiple: number
  net_target: number
  reason: string
  costs?: number
  max_lots?: number | null
  fee_verified?: string
  fee_source?: string
  fee_breakdown?: Record<string, number>
  risk_policy?: RiskPolicy
  cost_basis?: Record<string, unknown>
}
export type CashPlan = CashPlanBase &
  (
    | {
        fits: true
        sl: number
        target: number
        risk: number
        reward: number
        net_rr: number | null
      }
    | {
        fits: false
        sl: number | null
        target: number | null
        risk: number | null
        reward: number | null
        net_rr: number | null
      }
  )
export interface RiskSettings {
  risk: number | null
  daily_loss: number | null
  giveback: number | null
  premium: number | null
  spread: number
  slippage: number
  brokerage: number
  cooldown: number
  cutoff: string
}
export interface Quote {
  observed_time?: number
  timestamp?: string | number
  ltp?: number
  volume?: number
  buy_quantity?: number
  sell_quantity?: number
  buy_levels?: number
  sell_levels?: number
  prev_close?: number
  close?: number
  bid?: number
  ask?: number
  time: number
  source?: string
}
export interface Leg {
  symbol: string
  lotsize: number
  tick_size: number
  ltp?: number
  bid?: number
  ask?: number
  volume?: number
  oi?: number
  bid_qty?: number
  ask_qty?: number
}
export interface Plan {
  entry: number
  sl: number
  target: number
  quantity: number
  risk: number
  reward: number
  costs: number
  net_rr: number
  fits: boolean
  reason: string
  max_lots: number | null
  fee_verified: string
  fee_source: string
  fee_breakdown: Record<string, number>
}
export interface Trade {
  auto_target?: boolean
  id: string
  mode: DeskMode
  symbol: string
  exchange: string
  product: string
  lot: number
  tick: number
  quantity: number
  entry: number
  average_entry_verified?: boolean
  average_entry?: number
  entry_quantity: number
  remaining: number
  sl: number
  current_sl?: number
  desired_sl?: number
  target: number
  status: string
  reason: string
  quote?: Quote
  net_open?: number | null
  gross_open?: number | null
  peak_net?: number | null
  created: number
  lifecycle?: Array<{
    at: number
    status: string
    reason: string
    filled: number
    remaining: number
    sl?: number | null
    orders: Array<{
      role: string
      orderid?: string | null
      state?: string
      broker_status?: string
      filled?: number
    }>
  }>
  ops: Array<{
    role: string
    broker_status?: string
    orderid?: string
    state: string
    message?: string
    http_status?: number | null
    broker_code?: number | string | null
    broker_error?: string
    trigger_price?: number
    price?: number
  }>
}
export interface OrderTicket {
  strategy?: SetupStrategy
  strategy_version?: string
  risk_policy?: RiskPolicy
  manual_entry?: boolean
  symbol: string
  exchange: string
  product: string
  quantity: number
  entry: number
  sl: number
  target: number
  auto_target: boolean
  auto_invalidation: boolean
  auto_risk: boolean
  trailing: boolean
  profit_activation?: number
  retention?: number
  underlying?: string
  index_invalidation?: number
  setup_id?: string
}
export interface DailyDisciplineState {
  date: string
  entries: number
  max_entries: number
  count_verified?: boolean
  remaining_entries: number
  excess_entries: number
  profit_target: number
  loss_limit: number
  profit_reached: boolean
  loss_reached: boolean
  entry_limit_reached_at?: number
  profit_reached_at?: number
  loss_reached_at?: number
  profit_reached_net?: number
  loss_reached_net?: number
  net?: number | null
  updated_at: number
  pnl_available?: boolean
  pnl_error?: string
}
export interface Snapshot {
  setup?: SetupResult | null
  execution_readiness?: ExecutionReadiness[]
  scope: string
  mode: DeskMode
  settings: RiskSettings
  trades: Trade[]
  live_trades?: Trade[]
  heartbeat?: number
  book_time?: number
  error?: string | null
  positions?: Array<{
    symbol: string
    exchange: string
    product: string
    quantity: number
    average_price: number
    ltp: number
  }>
  orders?: Array<{
    orderid: string
    symbol: string
    exchange: string
    product: string
    action: string
    order_status: string
    quantity: number
  }>
  day?: {
    discipline?: DailyDisciplineState
    date?: string
    halt?: string
    peak?: number
    net?: number
    cooldown_until?: number
    risk_error?: string
    risk_available?: boolean
    entry_limits?: {
      entries?: number
      losses?: number
      max_entries?: number
      max_losses?: number
      blocked_reason?: string | null
    }
    journal?: {
      complete: boolean
      reason: string
      gross_realised: number | null
      net_realised: number | null
      charges: number | null
      cycles: Array<{ symbol: string; net: number; gross: number; duration: number }>
      fills: Array<{ symbol: string; action: string; epoch: number; average_price: number }>
    }
  }
  underlying: string
  exchange: string
  index_quote?: Quote | null
  chain_time?: number
  chain?: { atm_strike: number; chain: Array<{ strike: number; ce: Leg | null; pe: Leg | null }> }
  analysis: {
    action: 'CALL' | 'PUT' | 'WAIT'
    reason: string
    experimental?: boolean
    setup_id?: string
    invalidation?: number
    index_target?: number
    checks?: {
      checked_at: number
      one_closed_at: number | null
      five_closed_at: number | null
      history: 'fresh' | 'insufficient' | 'stale' | 'gap'
      state:
        | 'waiting_history'
        | 'stale_history'
        | 'history_gap'
        | 'waiting_trend'
        | 'waiting_trigger'
        | 'no_target'
        | 'low_reward'
        | 'conflict'
        | 'confirmed'
      trend: 'CALL' | 'PUT' | 'NEUTRAL' | null
      pattern_confirmed: boolean
      target_available: boolean
      reward_risk: number | null
    }
    zones: Array<{ price: number; kind: string; source: string; touches: number }>
  }
  recommendation?: {
    symbol: string
    strike: number
    side: string
    lot: number
    tick: number
    plan: Plan
    reason: string
  }
  selected_contract?: {
    symbol: string
    side: SetupDirection
    strike: number
    expiry: string
    strategy: SetupStrategy
    quote?: Quote
    plan?: Plan | CashPlan
    reason: string
  }
  selected_plan?: Plan
}
export interface Preview {
  ticket: string
  expires: number
  plan: Plan
  mode: DeskMode
}
export interface BrokerPosition {
  symbol: string
  exchange: string
  product: string
  quantity: number
  average_price?: number | string | null
  average_price_basis?: string | null
  average_entry?: number | string | null
  average_entry_verified: boolean
  entry_basis: string
  ltp?: number | string | null
  pnl?: number | string | null
  lot?: number
  tick?: number
}
export interface BrokerOrder {
  symbol: string
  exchange: string
  product: string
  action: string
  orderid: string
  order_status: string
  quantity: number | string
  filled_quantity?: number | string | null
  price?: number | string | null
  trigger_price?: number | string | null
  pricetype: string
}
export interface BrokerFill {
  symbol: string
  exchange: string
  product: string
  action: string
  quantity: number | string
  average_price: number | string
  orderid: string
  tradeid: string
  timestamp: string | number
  epoch?: number | null
}
export interface BrokerMonitorDay {
  day?: string
  book_time?: number
  positions: BrokerPosition[]
  orders: BrokerOrder[]
  fills: BrokerFill[]
}
export interface BrokerMonitorSnapshot extends BrokerMonitorDay {
  discipline?: DailyDisciplineState
  scope: string
  mode: 'live'
  error?: string | null
  days: Record<string, BrokerMonitorDay>
}
async function result<T>(
  request: Promise<{ data: { status: string; message?: string; data: T } }>
): Promise<T> {
  const { data } = await request
  if (data.status !== 'success') throw new Error(data.message || 'Request failed')
  return data.data
}
export interface EntryDecisionSignal {
  strategy: 'breakout_retest' | 'daily_sweep' | 'pivot_rejection' | 'pivot_retest'
  stage: string
  direction?: SetupDirection | null
  eligible: boolean
  reason: string
  reference?: { price: number; name?: string } | null
  pattern?: string
  invalidation?: number
  index_target?: number | null
  trigger?: number | null
  expires?: number | null
  directions?: Partial<Record<SetupDirection, EntryDecisionSignal>>
}
export interface PivotOverlay {
  underlying: string
  session_date: string
  reference_date: string
  previous: { high: number; low: number; close: number }
  levels: Record<'P' | 'R1' | 'R2' | 'R3' | 'S1' | 'S2' | 'S3', number>
}
export interface EntryDecisions {
  advisory_only: true
  generated_at: number
  symbol: string
  side: SetupDirection | null
  candidates: Record<'breakout_retest' | 'daily_sweep' | 'pivot_rejection' | 'pivot_retest', EntryDecisionSignal>
  pivots?: PivotOverlay | null
  pivot_evidence?: string
  plan: (Plan & { source: string }) | { fits: false; reason: string } | null
  plan_fresh: boolean
  plan_reason: string
  evidence: string
}
export const kotakAssistantApi = {
  entryDecisions: (params: Record<string, string | number>) =>
    result<EntryDecisions>(webClient.get('/kotak-assistant/api/entry-decisions', { params })),
  setupReplay: (params: Record<string, string | number>) =>
    result<SetupResult>(webClient.get('/kotak-assistant/api/setup-replay', { params })),
  cashPlan: (input: CashPlanRequest) =>
    result<CashPlan>(webClient.post('/kotak-assistant/api/cash-plan', input)),
  brokerMonitor: () =>
    result<BrokerMonitorSnapshot>(webClient.get('/kotak-assistant/api/broker-monitor')),
  snapshot: (params: Record<string, string | number>) =>
    result<Snapshot>(webClient.get('/kotak-assistant/api/snapshot', { params })),
  configure: (mode: DeskMode, settings: RiskSettings) =>
    result<RiskSettings>(webClient.post('/kotak-assistant/api/config', { mode, settings })),
  preview: (mode: DeskMode, order: OrderTicket) =>
    result<Preview>(webClient.post('/kotak-assistant/api/preview', { mode, order })),
  enter: (mode: DeskMode, ticket: string) =>
    result<Trade>(webClient.post('/kotak-assistant/api/entry', { mode, ticket })),
  exit: (mode: DeskMode, trade_id: string, request_id: string, quantity?: number) =>
    result<Trade>(
      webClient.post('/kotak-assistant/api/exit', { mode, trade_id, request_id, quantity })
    ),
  adopt: (mode: DeskMode, position: Record<string, unknown>) =>
    result<Trade>(webClient.post('/kotak-assistant/api/adopt', { mode, position })),
  stop: (mode: DeskMode, trade_id: string, sl: number) =>
    result<Trade>(webClient.post('/kotak-assistant/api/stop', { mode, trade_id, sl })),
}
