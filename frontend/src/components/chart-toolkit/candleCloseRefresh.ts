import type { TrendSession } from './trendAnalysis'

/** Schedule a fresh source read after a close. This never confirms cached OHLC. */
export function candleCloseRefreshDelay(
  nowMs: number,
  seconds: number,
  session?: TrendSession | null
): number | null {
  if (!Number.isFinite(nowMs) || !Number.isFinite(seconds) || seconds <= 0) return null
  const now = nowMs / 1000
  if (!session || session.end <= session.start) {
    return (Math.floor(now / seconds) + 1) * seconds * 1000 + 50 - nowMs
  }
  const midnight = Math.floor((now + session.offset) / 86400) * 86400 - session.offset
  for (let day = 0; day < 8; day++) {
    const base = midnight + day * 86400
    const weekday = new Date((base + session.offset) * 1000).getUTCDay()
    if (weekday === 0 || weekday === 6) continue
    const start = base + session.start * 60,
      end = base + session.end * 60
    if (now >= end) continue
    const boundary =
      seconds >= 86400
        ? end
        : Math.min(end, start + Math.max(1, Math.floor((now - start) / seconds) + 1) * seconds)
    return boundary * 1000 + 50 - nowMs
  }
  return null
}
