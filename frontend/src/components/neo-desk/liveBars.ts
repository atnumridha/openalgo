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
}
export function nextLiveBar(
  previous: Bar | undefined,
  price: number,
  timestamp: unknown,
  interval: string,
  now: number
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
  const time = Math.floor(ms / 1000 / sec) * sec
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
