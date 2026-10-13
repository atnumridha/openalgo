import { webClient } from './client'
export interface DatasetView {
  id: string
  start: string
  end: string
  expiries: string[]
  source: { name: string; synthetic: boolean }
  gaps: string[]
}
export interface ReplayTrade {
  symbol: string
  direction: string
  entry_time: string
  exit_time?: string
  quantity: number
  entry_price: string
  exit_price?: string
  net?: string
  status: string
  reason?: string
  initial_index_stop: string
  index_target: string
  index_reference: string
  option_bars: Array<{
    time: number
    open: number
    high: number
    low: number
    close: number
    volume: number
  }>
  index_bars: ReplayTrade['option_bars']
  trail: Array<{ time: number; option_stop: string | null; index_stop: string }>
}
export interface ReplayReport {
  profile: string
  trades: ReplayTrade[]
  known_realized_net: string
  net_complete: string | null
  fees_estimate: string
  closed_count: number
  unresolved_count: number
  wins: number
  drawdown: string
  coverage: { complete: boolean; gaps: string[] }
  assumptions: string[]
}
export interface ResearchJob {
  id: string
  status: string
  error: string | null
  result: ReplayReport | null
}
export const neoResearchApi = {
  datasets: async (): Promise<DatasetView[]> =>
    (await webClient.get('/neodesk/api/datasets')).data.datasets,
  start: async (body: Record<string, unknown>): Promise<ResearchJob> =>
    (await webClient.post('/neodesk/api/research', body)).data,
  job: async (id: string): Promise<ResearchJob> =>
    (await webClient.get('/neodesk/api/research/' + id)).data,
}
