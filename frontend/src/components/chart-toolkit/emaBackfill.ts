import { webClient } from '@/api/client'
export interface EmaState {
  points: { time: number; value: number }[]
  count: number
  sum: number
  value: number | null
}
export type EmaBackfill = Record<'9' | '15', EmaState> & {
  '21'?: EmaState
  alignment_algorithm?: string
  alignment_crosses?: {time:number;value:number;side:'up'|'down'}[]
  algorithm?: string
  direction?: 'up' | 'down' | 'sideways'
  crosses?: {time:number;value:number;side:'up'|'down'}[]
}
export async function loadEmaBackfill(
  candles: { time: number; close: number; open?: number; high?: number; low?: number }[],
  signal: AbortSignal,
  options: { intervalSeconds?: number; allowSessionGaps?: boolean } = {}
): Promise<EmaBackfill> {
  const { data } = await webClient.post(
    '/delta-chart/api/ema',
    { candles, ...(options.intervalSeconds ? { interval_seconds: options.intervalSeconds } : {}), ...(options.allowSessionGaps ? { allow_session_gaps: true } : {}) },
    { signal, timeout: 12000 }
  )
  if (data.status !== 'success' || !data.ema?.['9'] || !data.ema?.['15'])
    throw Error('EMA calculation unavailable')
  return data.ema
}
