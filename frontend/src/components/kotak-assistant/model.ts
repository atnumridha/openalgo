import type { Quote, Snapshot } from '@/api/kotakAssistant'
const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
export function expiryTime(value: string): number {
  const m = value
    .replaceAll('-', '')
    .toUpperCase()
    .match(/^(\d{2})([A-Z]{3})(\d{2}|\d{4})$/)
  if (!m) return Number.NaN
  const month = MONTHS.indexOf(m[2])
  const year = Number(m[3]) + (m[3].length === 2 ? 2000 : 0)
  const day = Number(m[1])
  const date = new Date(Date.UTC(year, month, day))
  return month >= 0 && date.getUTCMonth() === month && date.getUTCDate() === day
    ? date.getTime()
    : Number.NaN
}
export function expiryAscending(values: string[]): string[] {
  return [...new Set(values)]
    .filter((v) => Number.isFinite(expiryTime(v)))
    .sort((a, b) => expiryTime(a) - expiryTime(b))
}
export function executableQuote(q: Quote | undefined, now = Date.now() / 1000): boolean {
  return (
    !!q &&
    q.bid != null &&
    q.ask != null &&
    q.bid > 0 &&
    q.ask >= q.bid &&
    now - q.time >= 0 &&
    now - q.time <= 5
  )
}
export function money(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v)
    ? 'Unavailable'
    : v.toLocaleString('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 })
}
export function estimatedNet(
  gross: number | null,
  recordedGross: number | null | undefined,
  recordedNet: number | null | undefined
): number | null {
  if (gross == null || recordedGross == null || recordedNet == null) return null
  const result = gross - (recordedGross - recordedNet)
  return Number.isFinite(result) ? result : null
}
export function errorMessage(e: unknown): string {
  const error = e as { response?: { data?: { message?: string } }; message?: string }
  return (
    error?.response?.data?.message || error?.message || 'Operation failed; refresh account state'
  )
}

export function deskPlaceholder(
  previous: Snapshot | undefined,
  previousKey: readonly unknown[] | undefined,
  nextKey: readonly unknown[]
): Snapshot | undefined {
  if (
    !previous ||
    !previousKey ||
    nextKey.length < 7 ||
    !nextKey.slice(0, 6).every((v, i) => v === previousKey[i])
  )
    return undefined
  const strategyChanged = nextKey[7] !== previousKey[7] || nextKey[8] !== previousKey[8]
  return {
    ...previous,
    selected_plan: undefined,
    ...(strategyChanged ? { setup: undefined, recommendation: undefined } : {}),
  }
}

export function rewardTarget(
  entry: number,
  stop: number,
  multiple: number,
  tick: number
): number | null {
  if (
    ![entry, stop, multiple, tick].every(Number.isFinite) ||
    stop <= 0 ||
    entry <= stop ||
    multiple <= 0 ||
    tick <= 0
  )
    return null
  return Number(
    (Math.ceil(Number(((entry + (entry - stop) * multiple) / tick).toFixed(8))) * tick).toFixed(8)
  )
}

export function automaticStop(entry: number, tick: number, distance = entry * 0.1): number | null {
  if (![entry, tick, distance].every(Number.isFinite) || entry <= 0 || tick <= 0 || distance <= 0)
    return null
  const price = Number(
    (Math.floor(Number(((entry - distance) / tick).toFixed(8))) * tick).toFixed(8)
  )
  return price > 0 && price < entry ? price : null
}

export function draftEntry(leg: { ask?: number; ltp?: number; tick_size: number } | null) {
  const tick = leg?.tick_size || 0
  const ask = leg?.ask || 0,
    ltp = leg?.ltp || 0
  const value = ask > 0 ? ask : ltp
  if (!Number.isFinite(value) || !Number.isFinite(tick) || value <= 0 || tick <= 0)
    return { price: null, source: 'unavailable' } as const
  const price = Number((Math.ceil(Number((value / tick).toFixed(8))) * tick).toFixed(8))
  return { price, source: ask > 0 ? 'ask' : 'last traded price' } as const
}
