import { useEffect, useMemo, useRef, useState } from 'react'
import { useMarketDataContextOptional } from '@/contexts/MarketDataContext'
import { MarketDataManager, type SymbolData } from '@/lib/MarketDataManager'
import { feedTimeMs } from './liveBars'
import type { StrikeChoiceLeg, StrikeChoiceRow } from './strikeRanking'

const EMPTY_QUOTES: ReadonlyMap<string, SymbolData> = new Map()
const freshQuote = (quote: SymbolData, now: number, epoch: number) => {
  const stamp = feedTimeMs(quote.data.timestamp), received = quote.lastUpdate
  return quote.updateSource === 'websocket' && quote.connectionEpoch === epoch &&
    received != null && Number.isFinite(received) && received <= now && now - received <= 15000 &&
    stamp != null && stamp <= now && now - stamp <= 15000
}

/** Share the existing Quote subscriptions and publish one batch per second. */
export function useStrikeQuotes(scope: string, exchange: string, symbols: string[], active: boolean) {
  const context = useMarketDataContextOptional()
  const manager = useRef(context?.manager ?? MarketDataManager.getInstance()).current
  const [snapshot, setSnapshot] = useState<{ scope: string; quotes: ReadonlyMap<string, SymbolData> } | null>(null)
  const symbolsKey = useMemo(() => JSON.stringify([...new Set(symbols)].sort()), [symbols])
  useEffect(() => {
    if (!active) return
    const quotes = new Map<string, SymbolData>()
    const names: string[] = JSON.parse(symbolsKey)
    const state = manager.getState()
    if (names.length && !state.isConnected && !state.isPaused) void manager.connect().catch(() => {})
    const unsubscribes = names.map(symbol => {
      const receive = (quote: SymbolData) => {
        if (quote.symbol === symbol && quote.exchange === exchange) quotes.set(symbol, quote)
      }
      const cached = manager.getCachedData(symbol, exchange)
      if (cached) receive(cached)
      return manager.subscribe(symbol, exchange, 'Quote', receive)
    })
    const publish = () => {
      const state = manager.getState(), now = Date.now()
      const fresh = state.isConnected && state.isAuthenticated && !state.isPaused
        ? new Map([...quotes].filter(([, quote]) => freshQuote(quote, now, state.connectionEpoch)))
        : EMPTY_QUOTES
      setSnapshot(previous => {
        if (previous?.scope === scope && previous.quotes.size === fresh.size &&
          [...fresh].every(([symbol, quote]) => previous.quotes.get(symbol) === quote)) return previous
        return { scope, quotes: fresh }
      })
    }
    publish()
    const timer = setInterval(publish, 1000)
    return () => { clearInterval(timer); unsubscribes.forEach(unsubscribe => unsubscribe()) }
  }, [active, scope, exchange, symbolsKey, manager])
  return active && snapshot?.scope === scope ? snapshot.quotes : EMPTY_QUOTES
}

/** A later REST snapshot wins over an older tick, including a still-fresh cache tick. */
export function mergeStrikeQuotes(rows: StrikeChoiceRow[], quotes: ReadonlyMap<string, SymbolData>, snapshotAt: number): StrikeChoiceRow[] {
  if (!quotes.size) return rows
  const positive = (value: number | undefined): value is number => value != null && Number.isFinite(value) && value > 0
  const merge = (leg: StrikeChoiceLeg | null | undefined) => {
    if (!leg?.symbol) return leg
    const quote = quotes.get(leg.symbol)
    if (!quote || (quote.lastUpdate ?? 0) <= snapshotAt) return leg
    // Quote cache timestamps do not prove book/volume field freshness. Keep
    // spread, activity and OI on the independently refreshed chain snapshot.
    return positive(quote.data.ltp) ? { ...leg, ltp: quote.data.ltp } : leg
  }
  return rows.map(row => ({ ...row, ce: merge(row.ce), pe: merge(row.pe) }))
}
