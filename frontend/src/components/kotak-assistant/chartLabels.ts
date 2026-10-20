export interface VisibleChartLabel {
  title: string
  price: number
  color: string
  y: number
}
export function layoutChartLabels(labels: VisibleChartLabel[], height: number) {
  if (!Number.isFinite(height) || height < 24) return []
  const result = labels
    .filter(
      (l) =>
        Number.isFinite(l.y) && Number.isFinite(l.price) && l.price > 0 && l.y >= 0 && l.y <= height
    )
    .sort((a, b) => a.y - b.y)
    .slice(0, Math.floor(height / 24))
    .map((l) => ({ ...l, top: Math.max(0, Math.min(height - 22, l.y - 11)) }))
  for (let i = 1; i < result.length; i++)
    result[i].top = Math.max(result[i].top, result[i - 1].top + 24)
  const overflow = Math.max(0, (result.at(-1)?.top || 0) + 22 - height)
  if (overflow) for (const l of result) l.top -= overflow
  return result
}
