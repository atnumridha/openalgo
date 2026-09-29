/**
 * What a managed strategy draws on its live chart.
 *
 * Symbol, exchange and session come from the saved underlying — never NIFTY by
 * default. Indicator names match the completed-bar rules the engine evaluates.
 */

export type StrategyChartIndicator =
  | 'ema9'
  | 'ema15'
  | 'ema5'
  | 'ema50'
  | 'ema200'
  | 'sma5'
  | 'sma34'
  | 'bollinger'
  | 'macd'
  | 'openingRange'

export type StrategyChartInterval = '1m' | '5m' | '15m'
export type StrategyChartSession = 'index' | 'mcx'

export interface StrategyChartInput {
  underlying?: string | null
  underlying_exchange?: string | null
  scalp_profile?: string | null
}

export interface StrategyChartProfile {
  symbol: string
  exchange: string
  session: StrategyChartSession
  interval: StrategyChartInterval
  confirmationInterval: StrategyChartInterval | null
  indicators: StrategyChartIndicator[]
  label: string
}

const PROFILE_INDICATORS: Record<string, StrategyChartIndicator[]> = {
  ema915: ['ema9', 'ema15'],
  macd200: ['macd', 'ema200'],
  ema5: ['ema5'],
  regime50200: ['ema50', 'ema200'],
  box15: ['openingRange'],
  sma_macd: ['sma5', 'sma34'],
  bollinger: ['bollinger'],
  ml_forest: ['ema9', 'ema15'],
  receiver_trend: ['ema9', 'ema15'],
  receiver_retest: [],
  receiver_momentum: [],
}

const PROFILE_INTERVAL: Record<string, StrategyChartInterval> = {
  box15: '1m',
  ema5: '1m',
}

export function chartSession(exchange: string | null | undefined): StrategyChartSession {
  return (exchange || '').toUpperCase() === 'MCX' ? 'mcx' : 'index'
}

export function chartSymbol(input: StrategyChartInput): { symbol: string; exchange: string } {
  const symbol = (input.underlying || '').trim().toUpperCase()
  const exchange = (input.underlying_exchange || '').trim().toUpperCase()
  return { symbol, exchange }
}

export function strategyChartProfile(input: StrategyChartInput): StrategyChartProfile | null {
  const { symbol, exchange } = chartSymbol(input)
  if (!symbol || !exchange) return null
  const profile = input.scalp_profile || ''
  const interval = PROFILE_INTERVAL[profile] ?? '5m'
  const confirmationInterval = profile.startsWith('receiver_') ? '15m' : null
  const indicators = PROFILE_INDICATORS[profile] ?? []
  return {
    symbol,
    exchange,
    session: chartSession(exchange),
    interval,
    confirmationInterval,
    indicators,
    label: `${symbol} · ${exchange} · ${interval}`,
  }
}
