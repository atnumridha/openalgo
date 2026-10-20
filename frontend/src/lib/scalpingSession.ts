/** Keep broker books on the current India trading day. */
export function isTradingDay(ts?: string, now = new Date()): boolean {
  if (!ts) return true
  const day = (date: Date) => date.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
  const todayKey = day(now)
  // Legacy broker timestamps have no offset and already represent IST. Delta
  // uses UTC ISO timestamps: convert those before comparing calendar dates.
  if (/^\d{4}-\d{2}-\d{2}/.test(ts) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(ts)) return ts.slice(0, 10) === todayKey
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return true
  return day(date) === todayKey
}
