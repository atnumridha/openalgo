interface PriceCandle {
  time: number
  open: number
  high: number
  low: number
  close: number
}
/** Bar times carry the same IST shift as the chart history endpoint. */
export function optionStructure(
  input: PriceCandle[],
  seconds: number,
  nowUtc: number,
  price: number
) {
  const empty = { support: null, resistance: null } as {
    support: number | null
    resistance: number | null
  }
  if (!Number.isFinite(price) || price <= 0 || !Number.isFinite(seconds) || seconds <= 0)
    return empty
  const bars = [...input]
    .filter(
      (b) =>
        [b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) &&
        b.low > 0 &&
        b.low <= Math.min(b.open, b.close) &&
        b.high >= Math.max(b.open, b.close) &&
        b.time + seconds <= nowUtc + 19800
    )
    .sort((a, b) => a.time - b.time)
    .slice(-300)
  const lows: number[] = [],
    highs: number[] = []
  for (let i = 2; i < bars.length - 2; i++) {
    const b = bars[i],
      left = bars.slice(i - 2, i),
      right = bars.slice(i + 1, i + 3),
      near = [...left, ...right]
    if (
      near.every((n) => b.low <= n.low) &&
      left.some((n) => b.low < n.low) &&
      right.some((n) => b.low < n.low) &&
      b.low <= price
    )
      lows.push(b.low)
    if (
      near.every((n) => b.high >= n.high) &&
      left.some((n) => b.high > n.high) &&
      right.some((n) => b.high > n.high) &&
      b.high >= price
    )
      highs.push(b.high)
  }
  return {
    support: lows.length ? Math.max(...lows) : null,
    resistance: highs.length ? Math.min(...highs) : null,
  }
}
