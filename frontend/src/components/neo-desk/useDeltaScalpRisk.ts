import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { readDeltaHistory } from '../chart-toolkit/deltaFeed'
import { isDeltaChartSymbol } from '../chart-toolkit/deltaProducts'
import { candleCloseRefreshDelay } from '../chart-toolkit/candleCloseRefresh'
import { buildDeltaScalpContext, verifiedSource, type DeltaScalpHistory } from './deltaScalpRisk'
import { loadEmaBackfill } from '../chart-toolkit/emaBackfill'

/** Public execution history is independent of the displayed chart and its indicators. */
export function useDeltaScalpRisk(symbol: string, enabled: boolean) {
  const active = enabled && isDeltaChartSymbol(symbol)
  const client = useQueryClient()
  const [clock, setClock] = useState(Date.now())
  const read = async (interval: '1m' | '5m', signal: AbortSignal): Promise<DeltaScalpHistory> => {
    const observedAt = Date.now() / 1000
    const response = await readDeltaHistory(
      symbol,
      interval,
      undefined,
      AbortSignal.any([signal, AbortSignal.timeout(12000)])
    )
    const history = { ...response, observedAt }
    const source = verifiedSource(symbol, interval, history, observedAt)
    const ema = source ? await loadEmaBackfill(source.map(({time,close})=>({time,close})), signal) : null
    return { ...history, ema }
  }
  const fast = useQuery({
    queryKey: ['delta-scalp-history', symbol, '1m'],
    enabled: active,
    queryFn: ({ signal }) => read('1m', signal),
    staleTime: 10000,
    refetchInterval: active ? 15000 : false,
    refetchOnWindowFocus: 'always',
    refetchOnReconnect: 'always',
    retry: false,
  })
  const slow = useQuery({
    queryKey: ['delta-scalp-history', symbol, '5m'],
    enabled: active,
    queryFn: ({ signal }) => read('5m', signal),
    staleTime: 10000,
    refetchInterval: active ? 15000 : false,
    refetchOnWindowFocus: 'always',
    refetchOnReconnect: 'always',
    retry: false,
  })
  useEffect(() => {
    if (!active) return
    let stopped = false,
      timer: ReturnType<typeof setTimeout>
    const schedule = () => {
      timer = setTimeout(() => {
        if (stopped) return
        setClock(Date.now())
        void client.invalidateQueries(
          { queryKey: ['delta-scalp-history', symbol] },
          { cancelRefetch: false }
        )
        schedule()
      }, candleCloseRefreshDelay(Date.now(), 60) ?? 60000)
    }
    schedule()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [active, symbol, client])
  // Expire cached evidence even when React Query pauses background/offline polling.
  // Submission also checks the context deadline, so a throttled timer cannot authorize entry.
  useEffect(() => {
    if (!active) return
    const now = Date.now()
    const deadlines = [fast.data?.observedAt, slow.data?.observedAt]
      .filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
      .map((v) => v * 1000 + 30001)
      .filter((v) => v > now)
    if (!deadlines.length) return
    const timer = setTimeout(() => setClock(Date.now()), Math.min(...deadlines) - now)
    return () => clearTimeout(timer)
  }, [active, fast.data?.observedAt, slow.data?.observedAt, clock])
  return useMemo(
    () =>
      active && !fast.isError
        ? buildDeltaScalpContext(
            symbol,
            fast.data ?? null,
            slow.isError ? null : (slow.data ?? null),
            Date.now() / 1000
          )
        : null,
    [active, symbol, fast.data, slow.data, fast.isError, slow.isError, clock]
  )
}
