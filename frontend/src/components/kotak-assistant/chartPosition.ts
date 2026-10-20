export interface ChartPosition {
  status: 'unavailable' | 'flat' | 'open'
  currency: 'USD' | 'INR'
  entry?: number
  quantity?: number
  gross: number | null
  sl: number | null
  target: number | null
  slGross: number | null
  targetGross: number | null
  protectionAvailable: boolean
}

export function grossLabel(value: number | null, currency: 'USD' | 'INR'): string {
  if (value == null) return 'unavailable'
  const number = (n: number) =>
    `${n >= 0 ? '+' : '−'}${Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false })}`
  return currency === 'USD' ? `$${number(value)} / ₹${number(value * 85)}` : `₹${number(value)}`
}
