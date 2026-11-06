import type { DeltaChartState } from '@/api/deltaChart'
import type { Bar } from '../chart-toolkit/model'
import type { readDeltaHistory } from '../chart-toolkit/deltaFeed'
import { readEmaCrossTrend } from '../chart-toolkit/emaCross'
import type { EmaBackfill } from '../chart-toolkit/emaBackfill'
import { supportResistanceLevels } from '../chart-toolkit/TrendLineLayer'
import type { DeltaRiskContext } from './deltaRisk'

export type DeltaScalpHistory = Awaited<ReturnType<typeof readDeltaHistory>> & {
  observedAt: number
  ema?: EmaBackfill | null
}
export const DELTA_SCALP_STRATEGY = 'scalp-1m-5m-v1'
const positive = (n: number) => Number.isFinite(n) && n > 0

/** Transport timestamps are IST-shifted; all execution evidence is real UTC.
 * A clock change can request a new read, but cannot close previously observed OHLC.
 */
export function verifiedSource(
  symbol: string,
  interval: '1m' | '5m',
  history: DeltaScalpHistory | null,
  now: number
): Bar[] | null {
  const seconds = interval === '1m' ? 60 : 300
  if (
    !history ||
    history.status !== 'success' ||
    history.symbol !== symbol ||
    history.exchange !== 'DELTA' ||
    history.interval !== interval ||
    !positive(history.observedAt) ||
    history.observedAt > now + 5 ||
    now - history.observedAt > 30 ||
    !Array.isArray(history.candles)
  )
    return null
  const closed = history.candles
    .map((b) => ({ ...b, time: b.time - 19800 }))
    .filter((b) => b.time + seconds <= history.observedAt && b.time + seconds <= now)
  if (closed.at(-1)?.time !== (Math.floor(now / seconds) - 1) * seconds) return null
  // A recent gap invalidates confirmation. A sufficiently long fresh segment recovers naturally.
  const segment: Bar[] = []
  for (let i = closed.length - 1; i >= 0 && segment.length < 300; i--) {
    const b = closed[i],
      next = segment[0]
    if (
      ![b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) ||
      !positive(b.time) ||
      b.time % seconds !== 0 ||
      Math.min(b.open, b.high, b.low, b.close) <= 0 ||
      b.high < Math.max(b.open, b.low, b.close) ||
      b.low > Math.min(b.open, b.close) ||
      (next && next.time - b.time !== seconds)
    )
      break
    segment.unshift(b)
  }
  return segment.length >= 55 ? segment : null
}
export function buildDeltaScalpContext(
  symbol: string,
  fast: DeltaScalpHistory | null,
  slow: DeltaScalpHistory | null,
  now = Date.now() / 1000
): DeltaRiskContext | null {
  if (!positive(now)) return null
  const bars = verifiedSource(symbol, '1m', fast, now)
  const higher = verifiedSource(symbol, '5m', slow, now)
  if (!bars) return null
  const reading = readEmaCrossTrend(fast?.ema, bars.at(-1)!.time, bars.length)
  const filter = higher ? readEmaCrossTrend(slow?.ema, higher.at(-1)!.time, higher.length) : null
  const aligned =
    (reading.direction === 'up' || reading.direction === 'down') &&
    filter?.direction === reading.direction
  const summary = `1m: ${reading.label} · 5m: ${filter?.label ?? 'Checking candles'}`
  return {
    symbol,
    intervalSeconds: 60,
    sourceTime: bars.at(-1)!.time,
    observedAt: fast!.observedAt,
    direction: reading.direction,
    entryAligned: aligned,
    trendSummary: summary,
    entryExpiresAt: Math.min(fast!.observedAt, higher ? slow!.observedAt : fast!.observedAt) + 30,
    trendReason: !['up', 'down'].includes(reading.direction)
      ? `1m: ${reading.reason}`
      : !aligned
        ? `5m filter: ${filter?.reason ?? 'Waiting for fresh verified candles. New entries are paused; 1m position protection continues.'}`
        : reading.reason,
    bars,
    ...supportResistanceLevels(bars, 60, undefined, false),
  }
}

/** Conservative cash-profit floor; promotional credits/waivers are never assumed. */
export function scalpTargetPauseReason(
  side: 'buy' | 'sell',
  entry: number,
  target: number,
  tick: number,
  fees: DeltaChartState['sizing']
): string | null {
  const maker = fees?.maker_fee_rate,
    taker = fees?.taker_fee_rate,
    tax = fees?.fee_tax_rate
  if (
    !fees ||
    fees.currency !== 'USD' ||
    !fees.version ||
    [maker, taker, tax].some((n) => typeof n !== 'number' || !Number.isFinite(n) || n < 0)
  )
    return 'Waiting for verified Delta entry and exit fees.'
  if (![entry, target, tick].every(positive))
    return 'A valid scalp entry, target and tick size are required.'
  const reward = (target - entry) * (side === 'buy' ? 1 : -1)
  const costs = (entry * maker! + target * taker!) * (1 + tax!)
  if (reward < costs + tick)
    return `Scalp target leaves ${reward.toFixed(2)} points; estimated entry/exit fees need ${costs.toFixed(2)} points plus a price tick. Waiting for enough room after fees.`
  return null
}
