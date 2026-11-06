import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { scalpingApi } from '@/api/scalping'
import { useMarketDataContextOptional } from '@/contexts/MarketDataContext'
import { MarketDataManager, type SymbolData } from '@/lib/MarketDataManager'
import { StrikeRsiCalculator, type StrikeHistory, type StrikeRsiSnapshot } from './strikeRsi'

const pause = (ms: number, signal: AbortSignal) => new Promise<void>(resolve => {
  if (signal.aborted) { resolve(); return }
  const finish = () => { clearTimeout(timer); signal.removeEventListener('abort', finish); resolve() }
  const timer = setTimeout(finish, ms)
  signal.addEventListener('abort', finish, { once: true })
})
type Loaded = { calculator: StrikeRsiCalculator; attemptedAt: number; failed: boolean }
/** Quote events stay in refs; the full strike menu receives at most one update per second. */
export function StrikeRsiData({ scope, exchange, interval, symbols, active, loadPaused, onSnapshot }: {
  scope: string; exchange: string; interval: string; symbols: string[]; active: boolean; loadPaused: boolean
  onSnapshot: (snapshot: StrikeRsiSnapshot) => void
}) {
  const client = useQueryClient()
  const loaded = useRef(new Map<string, Loaded>())
  const priorities = useRef(symbols)
  const paused = useRef(loadPaused)
  priorities.current = symbols
  paused.current = loadPaused
  const context = useMarketDataContextOptional()
  const manager = useRef(context?.manager ?? MarketDataManager.getInstance()).current
  useEffect(() => {
    if (!active) return
    const controller = new AbortController(), signal = controller.signal
    const inFlight = new Set<string>()
    let retryAfter = 0
    const quotes = new Map<string, SymbolData>()
    const subscriptions = new Map<string, () => void>()
    const subscribe = (symbol: string) => {
      if (subscriptions.has(symbol)) return
      const cached = manager.getCachedData(symbol, exchange)
      if (cached) quotes.set(symbol, cached)
      subscriptions.set(symbol, manager.subscribe(symbol, exchange, 'Quote', quote => quotes.set(symbol, quote)))
    }
    const state = manager.getState()
    if (!state.isConnected && !state.isPaused) void manager.connect().catch(() => {})
    let previousSnapshot = ''
    const publish = () => {
      const feed = manager.getState(), now = Date.now()
      const values: StrikeRsiSnapshot['values'] = {}
      for (const symbol of priorities.current) {
        const record = loaded.current.get(symbol)
        if (record) {
          values[symbol] = record.calculator.value(quotes.get(symbol), now, !!feed.isAuthenticated && !!feed.isConnected && !feed.isPaused, feed.connectionEpoch)
          // Add streams progressively once RSI can be calculated. New menu ordering
          // must not tear down and re-subscribe every existing contract.
          if (values[symbol].value != null) subscribe(symbol)
        }
      }
      const snapshot = { scope, values, attempted: loaded.current.size, total: priorities.current.length }
      const key = JSON.stringify(snapshot)
      if (key !== previousSnapshot) { previousSnapshot = key; onSnapshot(snapshot) }
    }
    const eligible = (symbol: string) => {
      const row = loaded.current.get(symbol)
      return !inFlight.has(symbol) && (!row || Date.now() - row.attemptedAt >= (row.failed ? 300000 : 60000))
    }
    const worker = async () => {
      while (!signal.aborted) {
        if (paused.current || Date.now() < retryAfter) { await pause(500, signal); continue }
        const all = priorities.current
        const symbol = all.slice(0, 2).find(eligible)
          ?? all.find(symbol => !loaded.current.has(symbol) && eligible(symbol))
          ?? all.find(eligible)
        if (!symbol) { await pause(1000, signal); continue }
        inFlight.add(symbol)
        try {
          const primary = client.getQueryData<StrikeHistory>(['neo-tv-history', exchange, symbol, interval, undefined, undefined])
          const history = primary?.observedAt && primary.observedAt <= Date.now()/1000 && Date.now()/1000 - primary.observedAt < 20
            ? primary
            : await client.fetchQuery({
                queryKey: ['strike-rsi-history', scope, symbol, exchange, interval],
                queryFn: async ({ signal: querySignal }) => {
                  const observedAt = Date.now()/1000
                  // Let the broker's 60s timeout finish before scheduling more
                  // work; aborting at 12s left those server requests running.
                  const result = await scalpingApi.getHistory(symbol, exchange, interval, undefined, { signal: AbortSignal.any([signal, querySignal]), timeoutMs: 65000 })
                  if (result.status !== 'success') throw Error(result.message || 'Contract history unavailable')
                  return { ...result, observedAt }
                },
                staleTime: 60000, retry: false,
              })
          if (!signal.aborted) {
            const calculator = new StrikeRsiCalculator(symbol, exchange, interval)
            const valid = calculator.load(history, history.observedAt ?? 0)
            loaded.current.set(symbol, { calculator, attemptedAt: Date.now(), failed: !valid || !history.candles.length })
            if (calculator.value(undefined, Date.now(), false, 0).value != null) subscribe(symbol)
          }
        } catch {
          if (!signal.aborted) {
            retryAfter = Date.now() + 60000
            loaded.current.set(symbol, { calculator: loaded.current.get(symbol)?.calculator ?? new StrikeRsiCalculator(symbol, exchange, interval), attemptedAt: Date.now(), failed: true })
          }
        } finally { inFlight.delete(symbol) }
        await pause(250, signal)
      }
    }
    publish()
    const timer = setInterval(publish, 1000)
    void worker(); void worker()
    return () => {
      controller.abort(); clearInterval(timer)
      for (const unsubscribe of subscriptions.values()) unsubscribe()
    }
  }, [active, scope, exchange, interval, client, manager, onSnapshot])
  return null
}
