import { webClient } from './client'
export interface HistoryRow {
  symbol: string
  quantity: number
  entry_time: string
  exit_time: string
  entry_price: string
  exit_price: string
  gross_pnl: string | null
  fees: string | null
  net_pnl: string | null
  status: string
  estimated_fees?: string | null
  estimated_net_pnl?: string | null
  trade_id: string
}
export interface HistoryView {
  rows: HistoryRow[]
  symbols: string[]
  total: number
  open_inventory: Array<{ symbol: string; quantity: number; status: string }>
  summary: {
    gross_pnl: string | null
    gross_known_count?: number
    closed_count?: number
    actual_fees: string | null
    estimated_fees: string | null
    net_pnl: string | null
    fill_count: number
    fees_known_fill_count: number
  }
  coverage: { fill_count: number; recorded_dates: string[]; lifetime_complete: boolean }
  fee_estimate: {
    breakdown: Record<string, string>
    source: string
    assumption?: string
    cost_plan?: string
    fill_count?: number
    executed_order_count?: number
    recorded_dates?: string[]
  }
}
export const neoReportsApi = {
  history: async (
    symbol = '',
    start = '',
    end = '',
    cursor = 0,
    cost_plan = 'trade_free'
  ): Promise<HistoryView> =>
    (
      await webClient.get('/neodesk/api/history', {
        params: { symbol, start, end, cursor, cost_plan },
      })
    ).data,
  refresh: async () => (await webClient.post('/neodesk/api/history/refresh')).data,
  importCSV: async (csv: string) =>
    (await webClient.post('/neodesk/api/history/import', { csv })).data,
}
