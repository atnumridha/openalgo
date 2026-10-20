import { rememberDeltaFeeProfile } from '@/lib/deltaFeeProfile'
import { useAuthStore } from '@/stores/authStore'
import type { FeeProfile } from '@/lib/cryptoFees'
import { webClient } from './client'

/** One running Python strategy's open trade, as it publishes it. */
export interface StrategyRiskPosition {
  side: 'LONG' | 'SHORT'
  entry: number
  opened_at: string | null
  notional_usd: number
  margin_usd: number | null
  stop_pct: number
  stop_price: number
  initial_stop_price: number
  trailing: boolean
  trail_arm_price: number
  trail_gap_pct: number
  best_move_pct: number
  risk_usd: number
  fees_usd_round_trip: number
  time_exit_at: string | null
  live: number | null
  /** 'fixed' when the strategy closes at one price; absent or 'trailing' otherwise. */
  target_type?: 'fixed' | 'trailing'
  target_price?: number
}

export interface StrategyRiskState {
  strategy: string
  strategy_id: string
  symbol: string
  exchange: string
  product: string
  mode: 'analyze' | 'live'
  updated_at: string
  age_seconds: number | null
  running: boolean
  leverage: number | null
  liquidation_move_pct: number | null
  contract_btc: number
  quantity: number
  fees: { taker_pct_per_side: number; gst_pct: number; round_trip_pct: number; funding: string }
  rules: {
    entry: string
    stop: string
    take_profit: string
    max_hold_hours: number
    daily_loss_cap_pct: number
  }
  day: { trades: number; wins: number; net_pct: number; fees_usd: number; halted: boolean }
  next_stop_pct: number | null
  rsi: number | null
  /** What the entry rule is watching right now, e.g. "EMA20 84,700 above EMA50 84,500". */
  indicator?: string | null
  position: StrategyRiskPosition | null
}

export interface RiskOverview {
  leverage: number | null
  liquidation_move_pct: number | null
  maintenance_margin_pct: number
  fees: { taker_pct: number; maker_pct: number; gst_pct: number; round_trip_taker_pct: number }
  /** The operator's fee profile (GST, Scalper Offer, Diwali voucher); absent from older servers. */
  fee_profile?: FeeProfile
  broker_positions?: {
    symbol: string
    quantity: number
    entry: number
    leverage: number | null
    stops: number[]
    targets: number[]
    checked_at: number
    leverage_error?: string
    protection_error?: string
  }[]
  broker_risk_error?: string | null
  strategies: StrategyRiskState[]
}

export const riskApi = {
  getOverview: async (): Promise<RiskOverview | null> => {
    const response = await webClient.get<{ status: string; data?: RiskOverview }>(
      '/leverage/api/risk'
    )
    const overview =
      response.data.status === 'success' && response.data.data ? response.data.data : null
    rememberDeltaFeeProfile(useAuthStore.getState?.()?.user?.username, overview?.fee_profile)
    return overview
  },
}
