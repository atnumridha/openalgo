export type Amount = string | number | null | undefined
export interface Settings {
  provider: string
  model: string | null
  reasoning: string | null
  decision_mode?: string
}
export interface Snapshot {
  profile: string
  asof: number
  feed_fresh: boolean
  mcp_fresh: boolean
  decision_mode: string
  status: {
    running: boolean
    process_alive: boolean
    starting: boolean
    paused: boolean
    pause_reason?: string
    position: Record<string, Amount> | null
    unresolved_intents: unknown[]
    daily: { day: string; net: string; halted: boolean }
    runtime: { heartbeat?: number; ai_pending?: boolean; bid?: string; ask?: string }
    last_scan?: { at: number; reason: string }
  }
  report: {
    trades: number
    net_usd: string
    fees_usd: string
    gross_usd: string
    win_rate_percent: Amount
    net_expectancy_usd: Amount
    max_drawdown_usd: Amount
    mean_holding_seconds: Amount
    entry_maker_fill_rate_percent: Amount
    rest_ack_median_ms: Amount
    trade_details: Record<string, Amount>[]
  }
  ai_settings: Settings
  pending_command?: { action: string }
  paper_balance: {
    ready: boolean
    reason?: string
    cash_usd: string
    available_usd: string
    reserved_margin_usd: string
    captured_at: number
  }
  last_ai_analysis?: {
    at: number
    action: string
    reason: string
    state: string
    proposed_stop?: string
    execution_reason?: string
  }
  events: { id: number; ts: number; kind: string; value: Record<string, unknown> }[]
  runs: {
    id: number
    started: number
    ended: number | null
    state: string
    trades: number
    net_usd: string
    ai: Settings
  }[]
  equity: { closed_at: number; net_usd: string }[]
  rejected_reasons: Record<string, number>
  readiness: {
    ready: boolean
    credentials_ready: boolean
    qualification_ready: boolean
    profile_supported: boolean
    missing: string[]
  }
}
export interface Candle {
  time: number
  open: string
  high: string
  low: string
  close: string
  ema9?: string
  ema20?: string
  ema50?: string
}
export interface Observation {
  market_fresh: boolean
  account_fresh: boolean
  market_error?: string
  account_error?: string
  market: {
    asof: number
    one: Candle[]
    five: Candle[]
    analysis: { trend?: string; ema20_slope?: string; atr14_1m?: string; fresh?: boolean }
  } | null
  account: {
    asof: number
    day: string
    complete: boolean
    net_usd: string | null
    fees_usd: string
    unrealized_gross_usd: string | null
    available_usd: string
    cash_fees_usd: string
    credits_used_usd: string
    promo_credits_usd: string
    funding_usd: string
    issues: string[]
    positions: Record<string, Amount>[]
    orders: Record<string, Amount>[]
    trade_report?: TradeReport
    equity_changes: { at: number; change: string }[]
  } | null
}
export interface Evaluation {
  samples: number
  valid: number
  accuracy: number
  unnecessary_exits: number
  latency: { median: number; p95: number }
}
export interface Research {
  model?: { tag: string }
  at?: number
  note?: string
  training?: { iterations: number; seconds: number; peak_gpu_bytes: number; completed: boolean }
  comparison?: {
    eligible_for_paper: boolean
    failures: string[]
    baseline: Evaluation
    trained: Evaluation
    by_symbol: Record<
      string,
      { samples: number; baseline_accuracy: number; trained_accuracy: number }
    >
    action_recall: Record<string, { cases: number; recall: number }>
  }
}
export interface Models {
  codex: Record<string, { name: string; reasoning: string[] }>
  local: { online: boolean; models: { name: string; selectable: boolean; blocker?: string }[] }
}
export const when = (t?: number | null) =>
  t ? `${new Date(t * 1000).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })} IST` : '—'
export const money = (v: Amount) =>
  v == null
    ? 'Unavailable'
    : `$${Number(v).toFixed(2)} · ₹${(Number(v) * 85).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
export const num = (v: Amount, suffix = '') =>
  v == null ? 'N/A' : `${Number(v).toFixed(2)}${suffix}`

export interface TradeFill {
  fill_id: string
  order_id: string
  at: number
  side: string
  role: string
  liquidity: string
  contracts: string
  price: string
  fee_usd: string
  cash_fee_usd: string
  credits_used_usd: string
  allocation: string
}
export interface LiveTrade {
  id: string
  symbol: string
  direction: string
  status: 'closed' | 'open' | 'incomplete'
  contracts: string | null
  opened_at: number | null
  closed_at: number | null
  first_observed_at?: number
  holding_seconds: number | null
  entry_price: string | null
  exit_price: string | null
  entry_order_ids: string[]
  exit_order_ids: string[]
  gross_usd: string | null
  entry_fees_usd: string
  exit_fees_usd: string
  fees_usd: string
  cash_fees_usd: string
  credits_used_usd: string
  funding_usd: string
  rebates_usd: string
  promo_credits_usd: string
  net_usd: string | null
  cash_net_usd: string | null
  issues: string[]
  fills: TradeFill[]
}
export interface TradeReport {
  day: string
  asof: number
  closed_count: number
  total_rows?: number
  rows: LiveTrade[]
  totals: Record<string, string>
  issues: string[]
  unattributed: { kind: string; amount_usd: string; at: number }[]
  scope?: string
}
