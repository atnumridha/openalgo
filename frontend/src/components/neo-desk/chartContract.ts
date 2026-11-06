import type { PlanSession } from './chartTradePlan'
import { useQuery } from '@tanstack/react-query'
import { webClient } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
export interface ChartContract {
  symbol: string
  exchange: string
  tick_size: number
  lotsize?: number | null
  session?: PlanSession | null
}
export function useChartContract(
  symbol: string,
  exchange: string,
  provided?: ChartContract
): ChartContract | undefined {
  const owner = useAuthStore((s) => s.user?.username),
    mode = useThemeStore((s) => s.appMode)
  const exact =
    provided?.symbol === symbol && provided.exchange === exchange && provided.tick_size > 0
      ? provided
      : undefined
  const reference = ['NSE_INDEX', 'BSE_INDEX'].includes(exchange)
    ? { symbol, exchange, tick_size: 0.01 }
    : undefined
  const query = useQuery({
    queryKey: ['chart-contract-metadata', owner, mode, symbol, exchange],
    enabled: !!symbol,
    queryFn: async ({ signal }) => {
      if (exchange === 'DELTA') {
        const response = await fetch(
          `https://api.india.delta.exchange/v2/products/${encodeURIComponent(symbol)}`,
          { signal: AbortSignal.any([signal, AbortSignal.timeout(10000)]), credentials: 'omit' }
        )
        if (!response.ok) throw Error('Contract details unavailable')
        const payload = await response.json(),
          p = payload.result
        if (!payload.success || p?.symbol !== symbol || !(Number(p.tick_size) > 0))
          throw Error('Contract details unavailable')
        return { symbol, exchange, tick_size: Number(p.tick_size) } as ChartContract
      }
      const response = await webClient.get('/neodesk/api/chart/contract', {
        params: { symbol, exchange },
        signal,
        timeout: 10000,
      })
      const p = response.data
      if (p.symbol !== symbol || p.exchange !== exchange || !(Number(p.tick_size) > 0))
        throw Error('Contract metadata unavailable or mismatched')
      return { ...p, tick_size: Number(p.tick_size) } as ChartContract
    },
    staleTime: 600000,
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: (q) => (q.state.status === 'error' ? 15000 : false),
  })
  return exact
    ? { ...query.data, ...exact, lotsize: exact.lotsize ?? query.data?.lotsize }
    : reference
      ? { ...query.data, ...reference }
      : query.data
}
