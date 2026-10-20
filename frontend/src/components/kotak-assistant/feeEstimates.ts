import type { OrderTicket, Quote, Trade } from '@/api/kotakAssistant'
import { executableQuote } from './model'

// Same premium-turnover schedule as services/kotak_assistant/analysis.py.
// NSE/FA/73061 (1 Mar 2026), STT from 1 Apr 2026; BSE Sensex ₹3,250/crore.
export const FEE_VERIFIED = '2026-10-15'
export function feeDay(now = Date.now()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(now))
}
function cents(value: number) {
  // Match Python round(value, 2), including exactly representable half-paisa ties.
  const n = Math.abs(value),
    scaled = n * 100,
    floor = Math.floor(scaled)
  if (Number.isInteger(n * 8) && scaled - floor === 0.5)
    return (Math.sign(value) * (floor + (floor % 2))) / 100
  return Number(value.toFixed(2))
}
export function optionFees(
  buy: number,
  sell: number,
  exchange: string,
  brokerage = 0,
  day = feeDay()
) {
  const parsed = new Date(`${day}T00:00:00Z`)
  if (
    !['NFO', 'BFO'].includes(exchange) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(day) ||
    !Number.isFinite(parsed.getTime()) ||
    parsed.toISOString().slice(0, 10) !== day ||
    day < '2026-04-01' ||
    day > '2026-12-31' ||
    ![buy, sell, brokerage].every((v) => Number.isFinite(v) && v >= 0)
  )
    return null
  const turnover = buy + sell
  const tx = (turnover * (exchange === 'NFO' ? 3552.99 : 3250)) / 10_000_000
  const ipft = exchange === 'NFO' ? (turnover * 0.01) / 10_000_000 : 0
  const sebi = turnover / 1_000_000
  const values = {
    stt: sell * 0.0015,
    stamp: buy * 0.00003,
    exchange: tx,
    sebi,
    ipft,
    brokerage: 2 * brokerage,
    gst: 0.18 * (tx + sebi + ipft + 2 * brokerage),
  }
  return {
    ...Object.fromEntries(Object.entries(values).map(([key, value]) => [key, cents(value)])),
    total: cents(Object.values(values).reduce((a, b) => a + b, 0)),
  } as Record<keyof typeof values | 'total', number>
}
export function ticketCosts(
  order: Pick<OrderTicket, 'entry' | 'sl' | 'target' | 'quantity'> | null,
  exchange: string,
  brokerage = 0,
  slippage = 0,
  day = feeDay()
) {
  if (
    !order ||
    ![order.entry, order.sl, order.target, order.quantity, slippage].every(Number.isFinite) ||
    !Number.isInteger(order.quantity) ||
    order.quantity <= 0 ||
    slippage < 0 ||
    !(0 < order.sl && order.sl < order.entry && order.entry < order.target)
  )
    return null
  const premium = order.entry * order.quantity
  const stop = Math.max(0, order.sl - slippage),
    target = Math.max(0, order.target - slippage)
  const slFees = optionFees(premium, stop * order.quantity, exchange, brokerage, day)
  const targetFees = optionFees(premium, target * order.quantity, exchange, brokerage, day)
  if (!slFees || !targetFees) return null
  const netSL = cents((stop - order.entry) * order.quantity - slFees.total)
  const netTarget = cents((target - order.entry) * order.quantity - targetFees.total)
  return {
    premium: cents(premium),
    grossSL: cents((stop - order.entry) * order.quantity),
    grossTarget: cents((target - order.entry) * order.quantity),
    chargesSL: slFees.total,
    chargesTarget: targetFees.total,
    netSL,
    netTarget,
    netRR: cents(netTarget / -netSL),
    slFees,
    targetFees,
    slippage,
  }
}
export function openTradeCosts(trade: Trade, quote?: Quote, brokerage = 0, day = feeDay()) {
  if (
    !executableQuote(quote) ||
    trade.average_entry_verified === false ||
    !Number.isFinite(trade.average_entry) ||
    !(trade.average_entry! > 0) ||
    !Number.isInteger(trade.remaining) ||
    trade.remaining <= 0
  )
    return null
  const breakdown = optionFees(
    trade.average_entry! * trade.remaining,
    quote!.bid! * trade.remaining,
    trade.exchange,
    brokerage,
    day
  )
  if (!breakdown) return null
  const gross = cents((quote!.bid! - trade.average_entry!) * trade.remaining)
  return { gross, charges: breakdown.total, net: cents(gross - breakdown.total), breakdown }
}
