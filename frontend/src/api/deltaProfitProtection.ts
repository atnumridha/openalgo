import { webClient } from './client'

export interface ProfitProtectionPlan {
  symbol: string
  side: number
  quantity: number
  remaining_quantity?: number
  entry: number
  initial_stop: number
  stop: number
  target: number
  gap: number
  trailing_mode?: 'price' | 'net_usd'
  profit_arm_usd?: number
  profit_lock_usd?: number
  profit_gap_usd?: number
  peak_net_usd?: number
  protected_net_usd?: number
  conservative_net_usd?: number
  profit_armed?: boolean
  tick: number
  reward_multiple: number
  opened_at: string
  stop_id: string
  eligible: boolean
  exit_at: number
  window_end: number
  checked_at?: number
  estimated_net?: number
  enabled?: boolean
  state?: string
  message?: string
  preview_id: string
}

export interface ProtectionInputs {
  symbol: string
  mode: 'live'
  reward_multiple: number
  initial_stop?: number
  gap?: number
  trailing_mode?: 'price' | 'net_usd'
  profit_arm_usd?: number
  profit_lock_usd?: number
  profit_gap_usd?: number
}

export const deltaProfitApi = {
  status: async () =>
    (
      await webClient.get<{
        status: string
        data: { plans: ProfitProtectionPlan[]; heartbeat: number }
      }>('/delta-profit-protection/api/status')
    ).data.data,
  preview: async (data: ProtectionInputs) =>
    (
      await webClient.post<{ data: ProfitProtectionPlan }>(
        '/delta-profit-protection/api/preview',
        data
      )
    ).data.data,
  enable: async (data: ProtectionInputs & { preview_id: string }) =>
    (
      await webClient.post<{ data: ProfitProtectionPlan }>(
        '/delta-profit-protection/api/enable',
        data
      )
    ).data.data,
  pause: async (symbol: string) =>
    (await webClient.post('/delta-profit-protection/api/pause', { symbol, mode: 'live' })).data,
}
