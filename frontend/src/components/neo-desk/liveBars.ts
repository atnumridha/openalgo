import type { Bar } from 'openalgo-charts'
export function feedTimeMs(value: unknown): number | null {
  let ms: number
  if (typeof value === 'number') ms = value > 1e12 ? value : value * 1000
  else if (typeof value === 'string') ms = Date.parse(value)
  else return null
  return Number.isFinite(ms) && ms > 0 ? ms : null
}
const seconds: Record<string, number> = {
  '1m': 60,
  '3m': 180,
  '5m': 300,
  '15m': 900,
  '30m': 1800,
  '1h': 3600,
  '1d': 86400,
}
export function nextLiveBar(
  previous: Bar | undefined,
  price: number,
  timestamp: unknown,
  interval: string,
  now: number,
  sessionQuote?: { open?: number; high?: number; low?: number; volume?: number }
): Bar | null {
  const ms = feedTimeMs(timestamp),
    sec = seconds[interval]
  if (
    ms == null ||
    !sec ||
    !Number.isFinite(price) ||
    price <= 0 ||
    now - ms < 0 ||
    now - ms > 15000
  )
    return null
  const local = new Date(ms + 19800000),
    minute = local.getUTCHours() * 60 + local.getUTCMinutes(),
    day = local.getUTCDay()
  if (day === 0 || day === 6 || minute < 555 || minute >= 930) return null
  if (interval === '1d') {
    const localDay = Math.floor((ms / 1000 + 19800) / 86400)
    if (previous && Math.floor((previous.time + 19800) / 86400) === localDay)
      return {
        ...previous,
        high: Math.max(previous.high, price),
        low: Math.min(previous.low, price),
        close: price,
      }
    const open = sessionQuote?.open,
      high = sessionQuote?.high,
      low = sessionQuote?.low
    if (
      open == null ||
      high == null ||
      low == null ||
      ![open, high, low].every((v) => Number.isFinite(v) && v > 0) ||
      high < open ||
      low > open
    )
      return null
    const anchor = previous ? (((previous.time + 19800) % 86400) + 86400) % 86400 : 33300
    return {
      time: localDay * 86400 - 19800 + anchor,
      open,
      high: Math.max(high, price),
      low: Math.min(low, price),
      close: price,
      volume: sessionQuote?.volume ?? 0,
    }
  }
  const sessionStart =
    (Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate(), 9, 15) - 19800000) /
    1000
  const time = sessionStart + Math.floor((ms / 1000 - sessionStart) / sec) * sec
  if (previous && time < previous.time) return null
  return previous && time === previous.time
    ? {
        ...previous,
        high: Math.max(previous.high, price),
        low: Math.min(previous.low, price),
        close: price,
      }
    : { time, open: price, high: price, low: price, close: price, volume: 0 }
}
