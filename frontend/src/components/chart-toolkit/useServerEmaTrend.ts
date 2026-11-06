import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { Bar } from './model'
import { loadEmaBackfill } from './emaBackfill'
import { readEmaCrossTrend, contiguousEmaBars } from './emaCross'
const EMPTY: readonly Bar[] = []
/** Backend owns averaging; the exact closed OHLC prefix owns the cache identity. */
export function useServerEmaTrend(bars: readonly Bar[], enabled: boolean, seconds: number) {
  const source=useMemo(()=>enabled?contiguousEmaBars(bars,seconds):EMPTY,[bars,seconds,enabled])
  const input=useMemo(()=>source.map(({time,close})=>({time,close})),[source])
  const query=useQuery({queryKey:['delta-ema-cross-trend',seconds,input],enabled:enabled&&input.length>=16,
    queryFn:({signal})=>loadEmaBackfill(input,signal),staleTime:Infinity,retry:false})
  return useMemo(()=>readEmaCrossTrend(enabled&&!query.isError&&!query.isPlaceholderData?query.data:null,source.at(-1)?.time??null,source.length),[enabled,query.isError,query.isPlaceholderData,query.data,source])
}
