import type { scalpingApi } from '@/api/scalping'
type History = Awaited<ReturnType<typeof scalpingApi.getHistory>>
const prefix = 'neo.chart.snapshot.v1:'
const ttl = 86400000
const key = (
  user: string | undefined,
  mode: string,
  symbol: string,
  exchange: string,
  interval: string
) => prefix + JSON.stringify([user ?? 'signed-out', mode, symbol, exchange, interval])
const valid = (b: History['candles'][number]) =>
  b &&
  [b.time, b.open, b.high, b.low, b.close, b.volume].every(Number.isFinite) &&
  b.time > 0 &&
  b.low > 0 &&
  b.volume >= 0 &&
  b.low <= Math.min(b.open, b.close) &&
  b.high >= Math.max(b.open, b.close)
export function readHistorySnapshot(
  user: string | undefined,
  mode: string,
  symbol: string,
  exchange: string,
  interval: string,
  now = Date.now()
): History | undefined {
  try {
    const cached = JSON.parse(
      localStorage.getItem(key(user, mode, symbol, exchange, interval)) || 'null'
    )
    const data = cached?.data as History | undefined
    if (
      !data ||
      !Number.isFinite(cached.savedAt) ||
      now < cached.savedAt ||
      now - cached.savedAt > ttl ||
      data.status !== 'success' ||
      data.symbol !== symbol ||
      data.exchange !== exchange ||
      data.interval !== interval ||
      !Array.isArray(data.candles) ||
      !data.candles.length ||
      data.candles.length > 1200 ||
      !data.candles.every(valid)
    )
      return undefined
    return data
  } catch {
    return undefined
  }
}
export function saveHistorySnapshot(
  user: string | undefined,
  mode: string,
  data: History,
  now = Date.now()
) {
  if (data.status !== 'success' || !data.candles.length || !data.candles.every(valid)) return
  try {
    const candles = data.candles.slice(-1200)
    localStorage.setItem(
      key(user, mode, data.symbol, data.exchange, data.interval),
      JSON.stringify({ savedAt: now, data: { ...data, candles } })
    )
    const snapshots = Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i))
      .filter((k): k is string => !!k?.startsWith(prefix))
      .map((k) => {
        try {
          return { key: k, time: Number(JSON.parse(localStorage.getItem(k)!).savedAt) || 0 }
        } catch {
          return { key: k, time: 0 }
        }
      })
      .sort((a, b) => a.time - b.time)
    for (const old of snapshots.slice(0, Math.max(0, snapshots.length - 16)))
      localStorage.removeItem(old.key)
  } catch {
    /* A blocked or full browser store must never interrupt the live chart. */
  }
}
