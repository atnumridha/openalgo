const IST_OFFSET = 19800
const INTERVAL_SECONDS: Record<string, number> = { '1m': 60, '5m': 300, '15m': 900 }

/** Chart bars use IST-shifted Unix seconds; now is ordinary UTC Unix seconds.
 * Never roll over without a real next bar: old history must not look live.
 */
export function barCountdown(barTime: number | null, interval: string, now: number) {
  const seconds = INTERVAL_SECONDS[interval]
  if (barTime == null || !Number.isFinite(barTime) || !Number.isFinite(now) || !seconds)
    return { state: 'waiting', text: '—', closesAt: null } as const
  const start = barTime - IST_OFFSET
  if (now < start) return { state: 'waiting', text: '—', closesAt: null } as const
  const closesAt = start + seconds
  if (now >= closesAt) return { state: 'closed', text: 'Closed', closesAt } as const
  const remaining = Math.ceil(closesAt - now)
  return {
    state: 'forming',
    text: `${String(Math.floor(remaining / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`,
    closesAt,
  } as const
}
