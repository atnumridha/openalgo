import type { EvaluationInput, StrategySession } from './types'
export function strategySession(
  exchange: string | undefined,
  supplied?: StrategySession | null
): StrategySession | undefined {
  if (supplied === null) return
  if (
    supplied &&
    [supplied.start, supplied.end, supplied.offset].every(Number.isFinite) &&
    supplied.start >= 0 &&
    supplied.end > supplied.start &&
    supplied.end <= 1440
  )
    return supplied
  if (['NSE', 'NSE_INDEX', 'NFO', 'BSE', 'BSE_INDEX', 'BFO'].includes(exchange ?? ''))
    return { start: 555, end: 930, offset: 19800 }
  if (['DELTA', 'CRYPTO'].includes(exchange ?? '')) return { start: 0, end: 1440, offset: 0 }
}
/** Expected completed source bucket, including the short final exchange-session bar. */
export function expectedHourlyClose(a: EvaluationInput, asOf: number): number | undefined {
  const s = strategySession(a.context.exchange, a.extras.session)
  if (!s) return
  const day = Math.floor((asOf + s.offset) / 86400),
    midnight = day * 86400 - s.offset,
    start = midnight + s.start * 60,
    end = midnight + s.end * 60
  if (asOf >= end) return end
  if (asOf >= start + 3600) return start + Math.floor((asOf - start) / 3600) * 3600
  // Before today's first hourly close, verified main-chart session ends identify
  // the last observed trading session without guessing weekends or holidays.
  for (let i = a.index - 1; i >= 0; i--) {
    const b = a.frames[i].bar,
      d = Math.floor((b.time + s.offset) / 86400),
      close =
        b.closeTime ??
        Math.min(b.time + a.context.intervalSeconds, d * 86400 - s.offset + s.end * 60)
    if (d < day && close === d * 86400 - s.offset + s.end * 60) return close
  }
}
