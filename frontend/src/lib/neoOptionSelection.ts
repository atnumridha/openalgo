const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
export function expiryDate(value: string): string | null {
  const m = /^(\d{2})([A-Z]{3})(\d{2})$/.exec(value)
  if (!m || !months.includes(m[2])) return null
  const month = months.indexOf(m[2])
  const year = 2000 + Number(m[3]),
    day = Number(m[1])
  const date = new Date(Date.UTC(year, month, day))
  if (date.getUTCMonth() !== month || date.getUTCDate() !== day) return null
  return date.toISOString().slice(0, 10)
}
export function activeExpiries(dates: string[], now = new Date()): string[] {
  const ist = new Date(now.getTime() + 19800000)
  const today = ist.toISOString().slice(0, 10)
  const closed = ist.getUTCHours() * 60 + ist.getUTCMinutes() >= 930
  return [...new Set(dates)]
    .filter((value) => {
      const day = expiryDate(value)
      return day != null && (day > today || (day === today && !closed))
    })
    .sort((a, b) => expiryDate(b)!.localeCompare(expiryDate(a)!))
}
export function nearestExpiry(dates: string[]): string {
  return (
    [...dates].sort((a, b) => (expiryDate(a) || '').localeCompare(expiryDate(b) || ''))[0] || ''
  )
}


export function underlyingPriceExchange(symbol: string, derivativesExchange: string, reported?: string | null): string {
  if (reported) return reported
  if (derivativesExchange === 'NFO' && ['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','NIFTYNXT50'].includes(symbol)) return 'NSE_INDEX'
  if (derivativesExchange === 'BFO' && ['SENSEX','BANKEX'].includes(symbol)) return 'BSE_INDEX'
  return ''
}
