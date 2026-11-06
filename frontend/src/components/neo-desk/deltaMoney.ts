/** User-selected fixed display conversion; Delta order and wallet amounts remain USD. */
export const DELTA_USD_INR = 85
const inr = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
})
export function formatDeltaINR(amountUSD: number | null | undefined): string {
  if (typeof amountUSD !== 'number' || !Number.isFinite(amountUSD)) return '—'
  const converted = amountUSD * DELTA_USD_INR
  if (!Number.isFinite(converted)) return '—'
  const rounded = Number(converted.toFixed(4))
  return inr.format(Object.is(rounded, -0) ? 0 : rounded)
}
