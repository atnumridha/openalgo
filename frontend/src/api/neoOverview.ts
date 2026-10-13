import { webClient } from './client'
export interface Overview {
  price: string | null
  change: string | null
  change_pct: string | null
  rsi14: string | null
  advances: number
  declines: number
  unchanged: number
  covered: number
  missing: number
  market_session: string
  observed_at: string
  exchange_time: string | null
  timestamp_note: string | null
  source: string
  errors: string[]
}
export interface Health {
  activation: string
  mode: string
  waiting_reason: string
  account: {
    value: Record<string, string> | null
    observed_at: string | null
    error: string | null
    age_seconds: number | null
    stale: boolean
  }
  proxy: { alive: boolean | null }
  blockers: string[]
  observed_at: string
  note: string
}
export const neoOverviewApi = {
  overview: async (): Promise<Overview> => (await webClient.get('/neodesk/api/overview')).data,
  health: async (): Promise<Health> => (await webClient.get('/neodesk/api/health')).data,
}
