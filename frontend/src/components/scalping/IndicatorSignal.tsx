import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { analyzeSignal, type Candle } from '@/lib/scalpingSignal'
import type { SelectedLeg } from '@/types/scalping'

interface IndicatorHistory { one: Candle[]; five: Candle[] }

// Retain the warm-up across IST midnight, replacing updated bars by timestamp.
// A bounded buffer keeps enough prior sessions for the 5m EMA50 calculation.
function mergeCandles(previous: Candle[], latest: Candle[]): Candle[] {
  return [...new Map([...previous, ...latest].map((bar) => [bar.time, bar])).values()]
    .sort((a, b) => a.time - b.time)
    .slice(-2000)
}

export function IndicatorSignal({ leg, onAtr }: { leg: SelectedLeg | null; onAtr?: (value: { symbol: string; exchange: string; atr?: number; asof?: number }) => void }) {
  const queryClient = useQueryClient()
  const queryKey = ['scalping-indicators', leg?.symbol, leg?.exchange]
  const [now, setNow] = useState(Date.now() / 1000)
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(id)
  }, [])
  const query = useQuery({
    queryKey,
    enabled: !!leg,
    queryFn: async () => {
      const previous = queryClient.getQueryData<IndicatorHistory>(queryKey)
      // The endpoint accepts IST trading dates. Load multi-day history once,
      // then request only today instead of reloading days of bars every second.
      const date = previous
        ? new Date(Date.now() + 19800_000).toISOString().slice(0, 10)
        : undefined
      const [one, five] = await Promise.all([
        scalpingApi.getHistory(leg!.symbol, leg!.exchange, '1m', date, 'utc'),
        scalpingApi.getHistory(leg!.symbol, leg!.exchange, '5m', date, 'utc'),
      ])
      if (one.status !== 'success' || five.status !== 'success')
        throw new Error('Candle feed unavailable')
      return {
        one: mergeCandles(previous?.one ?? [], one.candles),
        five: mergeCandles(previous?.five ?? [], five.candles),
      }
    },
    refetchInterval: 1000,
    staleTime: 1000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
  const signal = analyzeSignal(
    query.isError ? [] : (query.data?.one ?? []),
    query.isError ? [] : (query.data?.five ?? []),
    now
  )
  useEffect(() => {
    if (leg) onAtr?.({ symbol: leg.symbol, exchange: leg.exchange, atr: signal.atr, asof: signal.asof })
  }, [leg?.symbol, leg?.exchange, signal.atr, signal.asof, onAtr])
  const number = (value?: number) => (value == null ? '—' : value.toFixed(2))
  return (
    <section
      className="space-y-2 rounded-lg border bg-card p-3"
      aria-label="Indicator recommendation"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium">
          Indicator recommendation · {leg?.symbol ?? 'Select a contract'}
        </h3>
        <Badge variant={signal.action === 'HOLD' ? 'secondary' : 'default'}>{signal.action}</Badge>
        <span className="text-xs text-muted-foreground">5m bias: {signal.bias}</span>
        <Button
          className="ml-auto"
          variant="ghost"
          size="sm"
          disabled={!leg || query.isFetching}
          onClick={() => query.refetch()}
        >
          {query.isFetching ? 'Updating…' : 'Refresh'}
        </Button>
      </div>
      <p className="text-sm">{query.isError ? 'HOLD — candle feed unavailable.' : signal.reason}</p>
      <div className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-xs">
        <span>5m EMA20 {number(signal.ema20)}</span>
        <span>5m EMA50 {number(signal.ema50)}</span>
        <span>1m EMA9 {number(signal.ema9)}</span>
        <span>RSI14 {number(signal.rsi)}</span>
        <span>ATR14 {number(signal.atr)}</span>
      </div>
      <p className="text-xs text-muted-foreground">
        Completed candles · refreshes every second
        {query.dataUpdatedAt ? ` · updated ${new Date(query.dataUpdatedAt).toLocaleTimeString()}` : ''}
        {signal.asof ? ` · candle closed ${new Date(signal.asof * 1000).toLocaleTimeString()}` : ''}
        . Indicator guidance only; fees, spread and SL risk still need to fit before entry. This
        panel does not submit orders.
      </p>
    </section>
  )
}
