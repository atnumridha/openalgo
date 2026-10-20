import type {
  ExpiryResponse,
  FuturesContract,
  OptionChainResponse,
  ScalpingOrderRequest,
  ScalpingOrderResponse,
  ScalpingSLState,
  SearchInstrument,
  SLStatesResponse,
  UnderlyingsResponse,
} from '@/types/scalping'
import { webClient } from './client'

export interface MLPlan {
  symbol?: string
  quantity?: number
  leverage?: number
  action: 'LONG' | 'SHORT' | 'HOLD'
  reason: string
  updated_at?: number
  signal_time?: number
  server_time: number
  quote_time?: number
  inference_ms?: number
  model_version?: string
  research_qualified?: boolean
  threshold?: number
  test?: { trades: number; win_rate: number; net_usd: number; fees_usd?: number }
  plans: Array<{
    side: 'LONG' | 'SHORT'; probability: number; expected_net_usd: number
    entry?: number; stop?: number; target?: number; net_risk?: number; net_target?: number
    entry_fee?: number; target_fee?: number; target_fees?: number; stop_fees?: number
    margin?: number; net_rr?: number; eligible: boolean; fits_risk?: boolean; reason: string
  }>
}

// Scalping terminal API. Endpoints are served by blueprints/scalping.py under
// the root path (not /api/v1), so we use webClient (session + CSRF aware).
export const scalpingApi = {
  getMLPlan: async (symbol: string, quantity: number, leverage: number): Promise<{ status: string; data: MLPlan }> => {
    const response = await webClient.get('/scalping/api/ml-plan', { params: { symbol, quantity, leverage } })
    return response.data
  },
  getUnderlyings: async (): Promise<UnderlyingsResponse> => {
    const response = await webClient.get<UnderlyingsResponse>('/scalping/api/underlyings')
    return response.data
  },

  // All F&O underlyings for an exchange (indices first), like /search/token.
  getAllUnderlyings: async (
    exchange: string,
    instrumenttype: 'options' | 'futures' = 'options'
  ): Promise<{ status: string; data: string[] }> => {
    const response = await webClient.get('/scalping/api/all_underlyings', {
      params: { exchange, instrumenttype },
    })
    return response.data
  },

  getExpiry: async (
    underlying: string,
    exchange: string,
    instrumenttype: 'options' | 'futures' = 'options'
  ): Promise<ExpiryResponse> => {
    const response = await webClient.get<ExpiryResponse>('/scalping/api/expiry', {
      params: { underlying, exchange, instrumenttype },
    })
    return response.data
  },

  search: async (
    exchange: string,
    query: string
  ): Promise<{ status: string; data: SearchInstrument[] }> => {
    const response = await webClient.get('/scalping/api/search', {
      params: { exchange, query },
    })
    return response.data
  },

  futures: async (
    underlying: string,
    exchange: string
  ): Promise<{
    status: string
    data: FuturesContract[]
  }> => {
    const response = await webClient.get('/scalping/api/futures', {
      params: { underlying, exchange },
    })
    return response.data
  },

  getStrikes: async (
    underlying: string,
    exchange: string,
    expiry: string,
    strikeCount = 10
  ): Promise<OptionChainResponse> => {
    const response = await webClient.get<OptionChainResponse>('/scalping/api/strikes', {
      params: { underlying, exchange, expiry, strike_count: strikeCount },
    })
    return response.data
  },

  // Historical candles for the scalping charts. interval is an OpenAlgo interval
  // (1m/5m/15m); lookback scales 1m=1 day, 5m=3, 15m=9. Pass `date` (the trading
  // date learned on first load) so the periodic reconcile pulls a single day.
  // The route adds 19,800 seconds for charts to display IST on a UTC axis.
  // Indicators must undo that display offset before comparing to Date.now().
  getHistory: async (
    symbol: string,
    exchange: string,
    interval: string,
    date?: string,
    timeBasis: 'chart' | 'utc' = 'chart'
  ): Promise<{
    status: string
    symbol: string
    exchange: string
    interval: string
    date: string | null
    candles: Array<{
      time: number
      open: number
      high: number
      low: number
      close: number
      volume: number
    }>
    message?: string
  }> => {
    const params: Record<string, string> = { symbol, exchange, interval }
    if (date) params.date = date
    const response = await webClient.get('/scalping/api/history', { params })
    if (timeBasis === 'utc' && Array.isArray(response.data.candles)) {
      return {
        ...response.data,
        candles: response.data.candles.map((candle: { time: number }) => ({
          ...candle,
          time: candle.time - 19800,
        })),
      }
    }
    return response.data
  },

  placeOrder: async (req: ScalpingOrderRequest): Promise<ScalpingOrderResponse> => {
    const response = await webClient.post<ScalpingOrderResponse>('/scalping/api/order', req)
    return response.data
  },

  // Risk-reducing single-leg exit (trailing-SL). Bypasses the entry lot cap and
  // splits oversized exits on the server, so a >20-lot position can always flatten.
  closeLeg: async (req: ScalpingOrderRequest): Promise<ScalpingOrderResponse> => {
    const response = await webClient.post<ScalpingOrderResponse>('/scalping/api/close_leg', req)
    return response.data
  },

  closeAll: async (): Promise<ScalpingOrderResponse> => {
    const response = await webClient.post<ScalpingOrderResponse>('/scalping/api/close_all', {})
    return response.data
  },

  cancelAll: async (): Promise<ScalpingOrderResponse> => {
    const response = await webClient.post<ScalpingOrderResponse>('/scalping/api/cancel_all', {})
    return response.data
  },

  getTracked: async (): Promise<{
    status: string
    data: Array<{ symbol: string; exchange: string; product: string }>
  }> => {
    const response = await webClient.get('/scalping/api/tracked')
    return response.data
  },

  resetTracked: async (): Promise<{ status: string; cleared?: boolean }> => {
    const response = await webClient.delete('/scalping/api/tracked')
    return response.data
  },

  getSLStates: async (): Promise<SLStatesResponse> => {
    const response = await webClient.get<SLStatesResponse>('/scalping/api/sl')
    return response.data
  },

  saveSL: async (
    sl: Partial<ScalpingSLState> & Pick<ScalpingSLState, 'symbol' | 'exchange' | 'product'>
  ): Promise<{ status: string; data?: ScalpingSLState; message?: string }> => {
    const response = await webClient.post('/scalping/api/sl', sl)
    return response.data
  },

  deleteSL: async (
    symbol: string,
    exchange: string,
    product: string
  ): Promise<{ status: string; deleted?: boolean }> => {
    const response = await webClient.delete('/scalping/api/sl', {
      data: { symbol, exchange, product },
    })
    return response.data
  },
}
