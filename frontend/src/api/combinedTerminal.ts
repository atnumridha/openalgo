import { webClient } from './client'
import type { DailyDisciplineState, DeskMode, SetupResult } from './kotakAssistant'
export interface ConnectionRef { id: string; owner: string; broker: 'kotak' | 'flattrade'; account: string; mode: DeskMode }
export interface Quote { ltp?: number; bid?: number; ask?: number; time: number; source?: string; volume?: number; observed_time?: number }
export interface ConnectionState { connection: ConnectionRef; entry_ready: boolean; books_complete: boolean; quotes_fresh: boolean; captured_at: number; funds: { availablecash: number } | null; error: string | null; charges?: number | null; estimated_exit_charges?: number | null; realized_net?: number | null; estimated_open_net?: number | null; estimated_total_net?: number | null; open_positions?: number | null; pending_orders?: number | null; filled_entries?: number | null }
export interface ManagedPosition { trade_id?: string; connection_id: string; broker: 'kotak' | 'flattrade'; account?: string; symbol: string; exchange?: string; product?: string; managed: boolean; quantity: number; remaining?: number; entry?: number; average_entry?: number; average_entry_verified?: boolean; current_sl?: number; sl?: number; target?: number; ltp?: number | null; net_open?: number | null; gross_open?: number | null; status: string; reason?: string; data_fresh: boolean; created?: number }
export interface CombinedSnapshot { mode: DeskMode; setup_required: boolean; connections: ConnectionState[]; positions: ManagedPosition[]; history: ManagedPosition[]; fills: Array<Record<string, unknown>>; orders?: Array<Record<string, unknown>>; day: DailyDisciplineState & { entry_allowed: boolean; reserved_entries: number; blocked_reason?: string | null }; summary: { complete: boolean; realized_net: number | null; estimated_open_net: number | null; estimated_total_net: number | null; reason?: string | null; partial_realized_net?: number }; settings: { reminder_seconds: number }; updated_at: number }
export interface PremiumPlan { entry: number; sl: number; target: number; quantity: number; risk: number; reward: number; costs: number; net_rr: number; fits: boolean; reason?: string }
export interface OptionLeg { symbol: string }
export interface StrikeRow { strike: number; ce?: OptionLeg | null; pe?: OptionLeg | null }
export interface MarketSnapshot { underlying: string; exchange: string; expiries: string[]; expiry: string; symbol: string; strike?: number; chain: { atm_strike: number; chain: StrikeRow[] } | null; ce?: OptionLeg | null; pe?: OptionLeg | null; quote: Quote | null; quotes: Record<string, Quote>; index_quote: Quote; metadata: { lot: number; tick: number; freeze: number } | null; template: PremiumPlan | null; setup: SetupResult }
export interface EntryPreview { preview_id: string; connection: ConnectionRef; expires: number; plan: Partial<PremiumPlan> }
export interface Receipt { operation_id?: string; state: string; error?: string | null }
export interface ChartHistory { status: string; symbol: string; exchange: string; interval: string; date: string | null; candles: Array<{ time: number; open: number; high: number; low: number; close: number; volume: number }>; message?: string }
async function get<T>(path: string, params?: Record<string, string | number>) { const r = await webClient.get(`/combined-terminal/api/${path}`, { params }); return r.data.data as T }
async function post<T>(path: string, payload: unknown) { const r = await webClient.post(`/combined-terminal/api/${path}`, payload); return r.data.data as T }
export const combinedTerminalApi = {
  config: () => get<{ enabled: boolean }>('config'),
  snapshot: (mode: DeskMode) => get<CombinedSnapshot>('snapshot', { mode }),
  market: (connectionId: string, params: Record<string, string | number>) => get<MarketSnapshot>('market', { ...params, connection_id: connectionId }),
  chart: async (connectionId: string, symbol: string, exchange: string, interval: string, date?: string): Promise<ChartHistory> => { const r = await webClient.get('/combined-terminal/api/chart', { params: { connection_id: connectionId, symbol, exchange, interval, ...(date ? { date } : {}) } }); return r.data },
  select: (contextId: string, connectionId: string) => post('selection', { context_id: contextId, connection_id: connectionId }),
  preview: (connectionId: string, ticket: Record<string, unknown>) => post<EntryPreview>('preview', { connection_id: connectionId, ticket }),
  enter: (previewId: string, operationId: string, connectionId: string) => post<Receipt>('entry', { preview_id: previewId, operation_id: operationId, connection_id: connectionId }),
  mutateTrade: (tradeId: string, action: 'exit' | 'stop', payload: Record<string, unknown>) => post<Receipt>('trade-action', { trade_id: tradeId, action, payload }),
  configure: (mode: DeskMode, seconds: number) => post('settings', { mode, settings: { reminder_seconds: seconds } }),
}
export const brokerName = (broker?: string) => broker === 'flattrade' ? 'Flattrade' : 'Kotak Neo'
export const rupees = (value?: number | null) => value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const terminalError = (error: unknown) => { const e = error as { response?: { data?: { message?: string } }; message?: string }; return e.response?.data?.message || e.message || 'Request unavailable' }
