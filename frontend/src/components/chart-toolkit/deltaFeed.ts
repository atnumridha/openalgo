import { useEffect, useState } from 'react'
import type { Bar } from './model'
import { isDeltaChartSymbol } from './deltaProducts'
// Public market data only. No API keys, cookies, balances or order endpoints.
export const deltaSeconds: Record<string, number> = {
  '1m': 60,
  '3m': 180,
  '5m': 300,
  '15m': 900,
  '30m': 1800,
  '1h': 3600,
  '1d': 86400,
}
const valid = (b: Bar) =>
  [b.time, b.open, b.high, b.low, b.close, b.volume].every(Number.isFinite) &&
  Math.min(b.open, b.high, b.low, b.close) > 0 &&
  b.high >= Math.max(b.open, b.close) &&
  b.low <= Math.min(b.open, b.close)
export function deltaCandle(input: unknown, symbol: string, interval: string) {
  if (!input || typeof input !== 'object') return null
  const m = input as Record<string, unknown>,
    seconds = deltaSeconds[interval]
  if (!seconds || m.type !== `candlestick_${interval}` || m.sy !== symbol || m.res !== interval)
    return null
  const published = Number(m.ts) / 1e6
  const start = Number(m.cst) / 1e6
  const bar: Bar = {
    time: Number.isFinite(start) && start > 0 ? start : Math.floor(published / seconds) * seconds,
    open: Number(m.o),
    high: Number(m.h),
    low: Number(m.l),
    close: Number(m.c),
    volume: Number(m.v ?? 0),
  }
  return valid(bar) ? { bar, published } : null
}
export async function readDeltaHistory(
  symbol: string,
  interval: string,
  date?: string,
  signal?: AbortSignal
): Promise<{
  status: string
  symbol: string
  exchange: string
  interval: string
  date: string | null
  candles: Bar[]
  message?: string
}> {
  const seconds = deltaSeconds[interval]
  if (!isDeltaChartSymbol(symbol) || !seconds)
    throw Error('Unsupported Delta chart symbol / timeframe')
  // Date pickers use IST; the exchange candle boundaries remain UTC.
  const start = date
    ? Date.parse(`${date}T00:00:00+05:30`) / 1000
    : Math.floor(Date.now() / 1000) - seconds * 1000
  const end = date ? start + 86400 - 1 : Math.floor(Date.now() / 1000)
  const params = new URLSearchParams({
    symbol,
    resolution: interval,
    start: String(start),
    end: String(end),
  })
  const response = await fetch(`https://api.india.delta.exchange/v2/history/candles?${params}`, {
    signal,
    credentials: 'omit',
  })
  if (!response.ok) throw Error(`Delta history unavailable (${response.status})`)
  const data = await response.json()
  if (!data.success || !Array.isArray(data.result)) throw Error('Delta returned no candle history')
  const candles: Bar[] = data.result
    .map((b: Record<string, unknown>) => ({
      time: Number(b.time),
      open: Number(b.open),
      high: Number(b.high),
      low: Number(b.low),
      close: Number(b.close),
      volume: Number(b.volume ?? 0),
    }))
    .filter(valid)
  // NeoMarketChart normalizes its host's legacy IST-shifted transport to UTC.
  return {
    status: 'success',
    symbol,
    exchange: 'DELTA',
    interval,
    date: date ?? null,
    candles: [...new Map(candles.map((b) => [b.time, b])).values()]
      .sort((a, b) => a.time - b.time)
      .map((b) => ({ ...b, time: b.time + 19800 })),
  }
}
export function useDeltaCandle(symbol: string, interval: string, enabled: boolean) {
  const [state, setState] = useState<{
    symbol: string
    interval: string
    connected: boolean
    bar?: Bar
    published?: number
  }>({ symbol, interval, connected: false })
  useEffect(() => {
    if (!enabled || !isDeltaChartSymbol(symbol) || !deltaSeconds[interval]) return
    let stopped = false,
      socket: WebSocket | undefined,
      timer: ReturnType<typeof setTimeout> | undefined,
      retry = 1000
    setState({ symbol, interval, connected: false })
    const connect = () => {
      if (stopped) return
      socket = new WebSocket('wss://public-socket.india.delta.exchange')
      socket.onopen = () => {
        retry = 1000
        socket?.send(
          JSON.stringify({
            type: 'subscribe',
            payload: { channels: [{ name: `candlestick_${interval}`, symbols: [symbol] }] },
          })
        )
        setState((old) => ({ ...old, connected: true }))
      }
      socket.onmessage = (event) => {
        try {
          const update = deltaCandle(JSON.parse(String(event.data)), symbol, interval)
          if (update)
            setState((old) =>
              old.published && old.published > update.published
                ? old
                : { symbol, interval, connected: true, ...update }
            )
        } catch {
          /* Ignore acknowledgements and malformed packets. */
        }
      }
      socket.onerror = () => socket?.close()
      socket.onclose = () => {
        if (stopped) return
        setState((old) => ({ ...old, connected: false }))
        timer = setTimeout(connect, retry)
        retry = Math.min(30000, retry * 2)
      }
    }
    connect()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
      socket?.close()
    }
  }, [symbol, interval, enabled])
  return state.symbol === symbol && state.interval === interval
    ? state
    : { symbol, interval, connected: false, bar: undefined, published: undefined }
}
