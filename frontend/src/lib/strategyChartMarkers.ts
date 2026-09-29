/**
 * BUY/SELL markers and Entry/SL/Target lines from fills, live legs, and signals.
 *
 * Fills are authoritative. A confirmed CE/PE evaluation is labeled Signal, not
 * a fill. Waiting or blocked evaluations draw nothing.
 */

import type { LegState, Order, StrategyEvent } from '@/types/strategy_module'

export const CHART_IST_OFFSET = 19800

export type ChartMarkerKind = 'buy' | 'sell' | 'signal-buy' | 'signal-sell'

export interface ChartMarker {
  time: number
  price: number
  kind: ChartMarkerKind
  label: string
}

export type ChartLevelKind = 'entry' | 'sl' | 'target' | 'ltp'

export interface ChartLevel {
  price: number
  kind: ChartLevelKind
  label: string
}

const WAITING = /waiting|collecting|unavailable|expired|not ready|no matching|no usable/i

export function chartTime(iso: string | null | undefined, intervalSec: number): number | null {
  if (!iso) return null
  const ms = Date.parse(iso)
  if (!Number.isFinite(ms)) return null
  const epochUtc = Math.floor(ms / 1000)
  return Math.floor((epochUtc + CHART_IST_OFFSET) / intervalSec) * intervalSec
}

function isFilled(order: Order): boolean {
  return order.status === 'complete' && order.avg_fill_price != null && order.filled_at != null
}

function isExit(order: Order): boolean {
  return order.kind.startsWith('exit')
}

export function snapToCandle(
  time: number,
  candleTimes: number[],
  intervalSec: number
): number | null {
  if (!candleTimes.length) return time
  let best = candleTimes[0]
  let bestDelta = Math.abs(time - best)
  for (const candleTime of candleTimes) {
    const delta = Math.abs(time - candleTime)
    if (delta < bestDelta) {
      best = candleTime
      bestDelta = delta
    }
  }
  return bestDelta <= intervalSec ? best : null
}

export function fillMarkers(orders: Order[], intervalSec: number): ChartMarker[] {
  const markers: ChartMarker[] = []
  for (const order of orders) {
    if (!isFilled(order)) continue
    const time = chartTime(order.filled_at, intervalSec)
    const price = order.avg_fill_price
    if (time == null || price == null || !Number.isFinite(price)) continue
    const buy = order.action.toUpperCase() === 'BUY'
    const exit = isExit(order)
    markers.push({
      time,
      price,
      kind: buy ? 'buy' : 'sell',
      label: exit ? (buy ? 'EXIT BUY' : 'EXIT SELL') : buy ? 'BUY' : 'SELL',
    })
  }
  return markers
}

export function signalMarker(
  event: StrategyEvent | null | undefined,
  intervalSec: number,
  hasFill: boolean
): ChartMarker | null {
  const markers = confirmedSignalMarkers(event ? [event] : [], intervalSec)
  if (hasFill || !markers.length) return null
  return markers[0]
}

export function confirmedSignalMarkers(
  events: StrategyEvent[],
  intervalSec: number
): ChartMarker[] {
  const markers: ChartMarker[] = []
  const seen = new Set<number>()
  for (const event of events) {
    if (event.kind !== 'signal_evaluation') continue
    const payload = event.payload || {}
    const reason = String(payload.reason ?? event.message ?? '')
    if (WAITING.test(reason)) continue
    const technical = payload.technical as
      | { direction?: string | null; bar_at?: string; data_ready?: boolean }
      | undefined
    const direction = String(technical?.direction || payload.direction || '').toUpperCase()
    if (direction !== 'CE' && direction !== 'PE') continue
    if (technical?.data_ready === false) continue
    const stamp =
      technical?.bar_at || (typeof payload.timestamp === 'string' ? payload.timestamp : event.ts)
    const time = chartTime(stamp, intervalSec)
    if (time == null || seen.has(time)) continue
    const price = Number(payload.close ?? payload.entry)
    seen.add(time)
    markers.push({
      time,
      price: Number.isFinite(price) && price > 0 ? price : 0,
      kind: direction === 'CE' ? 'signal-buy' : 'signal-sell',
      label: direction === 'CE' ? 'BUY' : 'SELL',
    })
  }
  return markers
}

export function visibleLogicalRange(barCount: number, compact: boolean) {
  const want = compact ? 48 : 72
  const from = Math.max(-1, barCount - want)
  return { from, to: barCount + 3 }
}

function finite(value: number | null | undefined): value is number {
  return value != null && Number.isFinite(value)
}

export function legLevels(legs: LegState[]): ChartLevel[] {
  const levels: ChartLevel[] = []
  for (const leg of legs) {
    if (leg.status !== 'open' && leg.entry_status !== 'complete') continue
    const name = leg.symbol || `Leg ${leg.leg_id}`
    if (finite(leg.entry_avg) && leg.entry_avg > 0) {
      levels.push({ price: leg.entry_avg, kind: 'entry', label: `${name} Entry` })
    }
    if (finite(leg.effective_sl)) {
      levels.push({ price: leg.effective_sl, kind: 'sl', label: `${name} SL` })
    }
    if (finite(leg.effective_target)) {
      levels.push({ price: leg.effective_target, kind: 'target', label: `${name} Target` })
    }
    if (finite(leg.ltp)) {
      levels.push({ price: leg.ltp, kind: 'ltp', label: `${name} LTP` })
    }
  }
  return levels
}
