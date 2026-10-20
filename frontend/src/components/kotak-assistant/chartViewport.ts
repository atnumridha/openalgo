export interface ChartRange {
  from: number
  to: number
}
export function chartWindow(
  length: number,
  width: number,
  previous: ChartRange | null,
  follow: boolean
): ChartRange {
  if (previous && !follow) return previous
  const to = Math.max(0, length - 1) + 3
  const span = previous
    ? previous.to - previous.from
    : Math.max(20, Math.min(80, Math.floor((width - 70) / 10)))
  return { from: to - span, to }
}
export function recentTickEpoch(
  timestamp: string | number | undefined,
  now: number
): number | null {
  if (timestamp == null || timestamp === '') return null
  const numeric =
    typeof timestamp === 'number'
      ? timestamp
      : /^\d+(\.\d+)?$/.test(timestamp)
        ? Number(timestamp)
        : NaN
  const epoch = Number.isFinite(numeric)
    ? numeric > 1e12
      ? numeric / 1000
      : numeric
    : Date.parse(String(timestamp)) / 1000
  return Number.isFinite(epoch) && now - epoch >= -3 && now - epoch <= 10 ? Math.floor(epoch) : null
}
