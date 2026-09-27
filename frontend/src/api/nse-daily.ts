import { webClient } from './client'

export interface DailyArchiveStatus {
  status:
    | 'empty'
    | 'running'
    | 'completed'
    | 'completed_with_gaps'
    | 'blocked'
    | 'interrupted'
    | 'failed'
  session_count: number
  start: string | null
  end: string | null
  requested_start?: string
  requested_end?: string
  processed_dates: number
  total_dates: number
  unavailable_count: number
  error_count: number
  option_rows: number
  message?: string | null
  intraday_eligible: false
}

export interface DailySnapshot {
  session: string | null
  age_calendar_days: number | null
  contracts: Array<{
    expiry: string
    strike: number
    option_type: 'CE' | 'PE'
    close: number
    traded_contracts: number
    open_interest_units: number
  }>
}

export const dailyBase = '/strategy/api/research/daily-options'
export const dailyKey = ['nse-daily-history'] as const
export const getDailyArchive = async (): Promise<DailyArchiveStatus> =>
  (await webClient.get<{ data: DailyArchiveStatus }>(dailyBase)).data.data
export const updateDailyArchive = async (): Promise<DailyArchiveStatus> =>
  (await webClient.post<{ data: DailyArchiveStatus }>(dailyBase, {})).data.data
export const cancelDailyArchive = async (): Promise<DailyArchiveStatus> =>
  (await webClient.post<{ data: DailyArchiveStatus }>(`${dailyBase}/cancel`, {})).data.data
export const getDailySnapshot = async (): Promise<DailySnapshot> =>
  (await webClient.get<{ data: DailySnapshot }>(`${dailyBase}/snapshot`)).data.data
