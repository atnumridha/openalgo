import type { Zone } from './model'
import { layoutChartLabels } from '../kotak-assistant/chartLabels'
export interface LevelName {
  title: string
  price: number
  color: string
  y: number
}
export function mergeCoincidentNames(names: LevelName[]) {
  const result: LevelName[] = []
  for (const name of [...names].sort((a, b) => a.y - b.y)) {
    const prior = result.at(-1)
    if (
      prior &&
      Math.abs(prior.price - name.price) <= Math.max(Math.abs(name.price) * 1e-12, 1e-12) &&
      prior.title.length + name.title.length < 48
    )
      prior.title += ` / ${name.title}`
    else result.push({ ...name })
  }
  return result
}
export const formatLevelPrice = (value: number) =>
  value.toLocaleString('en-IN', {
    minimumFractionDigits: 1,
    maximumFractionDigits: value >= 1 ? 2 : 8,
  })

// The engine orders validated zones nearest-first within each side.
export function nearestZones(zones: Zone[]): Zone[] {
  return [false, true].flatMap((above) => {
    const nearest = zones.find((zone) => zone.above === above)
    return nearest ? [nearest] : []
  })
}

export function layoutLevelNames(names: LevelName[], height: number, topInset = 0) {
  const inset = Math.max(0, Math.min(topInset, height - 24))
  return layoutChartLabels(
    names.map((n) => ({ ...n, y: Math.max(0, n.y - inset) })),
    height - inset
  ).map((n) => ({
    ...n,
    y: names.find((original) => original.title === n.title && original.price === n.price)!.y,
    top: n.top + inset,
  }))
}
