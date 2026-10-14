import { webClient } from './client'
import type { ReplayTrade } from './neoResearch'
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
export interface ChartCoverage {
  symbol: string
  exchange: string
  interval: string
  start: string
  end: string
  count: number
  last_saved?: string
}
export interface StorageStatus {
  backend: string
  live_fills: number
  paper_fills: number
  history_events: number
  charts: ChartCoverage[]
  last_backup?: string
  last_capture?: string
  backup_error?: string | null
  sync_error?: string | null
  trade_chart_error?: string | null
  chart_backfill_error?: string | null
}
export const neoReportsApi = {
  replay: async (
    trade_id: string,
    mode: string
  ): Promise<{
    source: string
    trade: ReplayTrade
    coverage: { complete: boolean; gaps: string[] }
  }> => (await webClient.get('/neodesk/api/history/replay', { params: { trade_id, mode } })).data,
  storage: async (): Promise<StorageStatus> => (await webClient.get('/neodesk/api/storage')).data,
  chart: async (symbol: string, exchange: string, interval: string, start: string, end: string) =>
    (
      await webClient.get('/neodesk/api/charts/saved', {
        params: { symbol, exchange, interval, start, end },
      })
    ).data,
  history: async (
    symbol = '',
    start = '',
    end = '',
    cursor = 0,
    cost_plan = 'trade_free',
    mode = 'live'
  ): Promise<HistoryView> =>
    (
      await webClient.get('/neodesk/api/history', {
        params: { symbol, start, end, cursor, cost_plan, mode },
      })
    ).data,
  refresh: async () => (await webClient.post('/neodesk/api/history/refresh')).data,
  importCSV: async (csv: string) =>
    (await webClient.post('/neodesk/api/history/import', { csv })).data,
}
