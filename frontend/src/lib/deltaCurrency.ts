/** Delta India uses this fixed settlement conversion, not the spot FX rate.
 * https://www.delta.exchange/support/solutions?articleId=80001200076
 */
export const DELTA_INR_PER_USD = 85
export type DeltaDisplayCurrency = 'INR' | 'USD'
export type MoneyFormatter = (value: number | null | undefined, digits?: number) => string
export function deltaMoney(
  value: number | null | undefined,
  currency: DeltaDisplayCurrency,
  digits = 2
): string {
  if (value == null || !Number.isFinite(value)) return '-'
  return new Intl.NumberFormat(currency === 'INR' ? 'en-IN' : 'en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value * (currency === 'INR' ? DELTA_INR_PER_USD : 1))
}
