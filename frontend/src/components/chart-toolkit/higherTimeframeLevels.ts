import type { Bar } from './model'

export interface TimeframePriceLevel {
  title: '1H HIGH' | '1H LOW' | '4H HIGH' | '4H LOW'
  price: number
  color: string
  start: number
  end: number
}
/** Crypto exchange candles use UTC boundaries. Only the immediately preceding
 * completed block is eligible; incomplete/invalid blocks never fall back silently. */
export function higherTimeframeLevels(hours: readonly Bar[], asOf: number): TimeframePriceLevel[] {
  if (!Number.isFinite(asOf) || asOf <= 0) return []
  const output: TimeframePriceLevel[] = []
  for (const count of [1, 4] as const) {
    const duration = count * 3600
    const end = Math.floor(asOf / duration) * duration,
      start = end - duration
    const bars = hours
      .filter((bar) => bar.time >= start && bar.time < end)
      .sort((a, b) => a.time - b.time)
    if (
      bars.length !== count ||
      bars.some(
        (bar, index) =>
          bar.time !== start + index * 3600 ||
          ![bar.open, bar.high, bar.low, bar.close].every(Number.isFinite) ||
          Math.min(bar.open, bar.low, bar.close) <= 0 ||
          bar.high < Math.max(bar.open, bar.close, bar.low) ||
          bar.low > Math.min(bar.open, bar.close)
      )
    )
      continue
    const color = count === 1 ? '#f59e0b' : '#a78bfa'
    output.push(
      {
        title: count === 1 ? '1H HIGH' : '4H HIGH',
        price: Math.max(...bars.map((bar) => bar.high)),
        color,
        start,
        end,
      },
      {
        title: count === 1 ? '1H LOW' : '4H LOW',
        price: Math.min(...bars.map((bar) => bar.low)),
        color,
        start,
        end,
      }
    )
  }
  return output
}
