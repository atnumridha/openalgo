/**
 * Build the position book for the scalping terminal.
 *
 * Combines, per (symbol, exchange, product):
 *  - today's BUY/SELL trades (qty + weighted avg)  -> realized P&L, buy/sell cols
 *  - the current open position (net qty, LTP, avg)  -> unrealized P&L
 *  - the active stop-loss                           -> SL column
 *
 * Pure function (no React/network) so it is unit-testable against the acceptance
 * cases. Rows with netQty 0 are retained when there were trades today so realized
 * P&L stays visible until the session/day resets.
 */
import { findLegSL, type SLState } from '@/hooks/useTrailingSL'
import type { ScalpingPositionRow, ScalpingProduct } from '@/types/scalping'
import type { Position, Trade } from '@/types/trading'

interface Agg {
  symbol: string
  exchange: string
  product: string
  buyQty: number
  sellQty: number
  buyValue: number
  sellValue: number
  posQty?: number
  ltp?: number
  posAvg?: number
  multiplier?: number
  fills: Trade[]
}

const keyOf = (s: string, e: string, p: string) => `${e}:${s}:${p}`

// Delta supplies the position size after each fill. Require continuity from a
// known flat starting point; today's VWAP cannot reconstruct carried-in cost.
function cryptoRealized(fills: Trade[]): number | null {
  let quantity = 0, average = 0, gross = 0
  const unique = new Map<string, Trade>()
  for (const fill of fills) {
    if (!fill.fill_id) return null
    unique.set(fill.fill_id, fill)
  }
  const remaining = [...unique.values()].sort((a, b) => a.timestamp.localeCompare(b.timestamp))
  while (remaining.length) {
    const time = remaining[0].timestamp
    // Equal-time partial fills must follow position continuity, not UUID order.
    const index = remaining.findIndex((f) => f.timestamp === time && f.position_after != null &&
      Number(f.position_after) - (f.action === 'BUY' ? 1 : -1) * Number(f.quantity) === quantity)
    if (index < 0) return null
    const f = remaining.splice(index, 1)[0]
    const size = Number(f.quantity), price = Number(f.average_price), multiplier = Number(f.contract_value)
    if (!['BUY', 'SELL'].includes(f.action) || ![size, price, multiplier].every(v => Number.isFinite(v) && v > 0)) return null
    const signed = (f.action === 'BUY' ? 1 : -1) * size
    if (!quantity || Math.sign(quantity) === Math.sign(signed)) {
      average = (average * Math.abs(quantity) + price * size) / (Math.abs(quantity) + size)
    } else {
      const closed = Math.min(Math.abs(quantity), size)
      gross += (price - average) * closed * Math.sign(quantity) * multiplier
      if (size > Math.abs(quantity)) average = price
      else if (size === Math.abs(quantity)) average = 0
    }
    quantity += signed
  }
  return Number(gross.toFixed(10))
}

export function buildPositionRows(
  positions: Position[],
  trades: Trade[],
  slMap: Record<string, SLState>,
  liveLtp?: (symbol: string, exchange: string) => number | undefined,
  // When provided, only instruments in the scalping list (exchange:symbol:product)
  // are included — scopes the book to the scalping strategy, not the whole account.
  trackedKeys?: Set<string>,
  availability: { positionsComplete: boolean; tradesComplete: boolean } = { positionsComplete: true, tradesComplete: true }
): ScalpingPositionRow[] {
  const map = new Map<string, Agg>()

  const ensure = (symbol: string, exchange: string, product: string): Agg => {
    const k = keyOf(symbol, exchange, product)
    let rec = map.get(k)
    if (!rec) {
      rec = { symbol, exchange, product, buyQty: 0, sellQty: 0, buyValue: 0, sellValue: 0, fills: [] }
      map.set(k, rec)
    }
    return rec
  }

  // Aggregate today's trades into buy/sell qty + value (for weighted averages).
  const seen = new Set<string>()
  for (const t of trades) {
    if (t.fill_id && seen.has(t.fill_id)) continue
    if (t.fill_id) seen.add(t.fill_id)
    const product = (t.product || '').toUpperCase()
    const rec = ensure(t.symbol, t.exchange, product)
    rec.fills.push(t)
    // Coerce broker numeric fields: live brokers can return these as strings.
    const qty = Math.abs(Number(t.quantity) || 0)
    const px = Number(t.average_price) || 0
    if ((t.action || '').toUpperCase() === 'BUY') {
      rec.buyQty += qty
      rec.buyValue += qty * px
    } else if ((t.action || '').toUpperCase() === 'SELL') {
      rec.sellQty += qty
      rec.sellValue += qty * px
    }
  }

  // Merge open positions (authoritative net qty, live LTP, broker avg).
  for (const p of positions) {
    const product = (p.product || '').toUpperCase()
    const rec = ensure(p.symbol, p.exchange, product)
    // Coerce broker numeric fields. The PositionBook API contract returns these
    // as strings (e.g. "83.74") for live brokers, which previously left
    // row.avgPrice a string and crashed the table on avgPrice.toFixed() (#1532).
    // Sandbox returns numbers, where Number() is a no-op.
    rec.posQty = Number(p.quantity) || 0
    rec.ltp = Number(p.ltp) || 0
    rec.posAvg = Number(p.average_price) || 0
    rec.multiplier = p.lot_size == null ? undefined : Number(p.lot_size)
  }

  const rows: ScalpingPositionRow[] = []
  for (const rec of map.values()) {
    if (trackedKeys && !trackedKeys.has(keyOf(rec.symbol, rec.exchange, rec.product))) {
      continue // not part of the scalping list — exclude account-wide positions
    }
    const buyAvg = rec.buyQty > 0 ? rec.buyValue / rec.buyQty : 0
    const sellAvg = rec.sellQty > 0 ? rec.sellValue / rec.sellQty : 0
    // The broker positionbook is authoritative for net qty. Open positions ALWAYS
    // appear in it; a closed position is DROPPED from it (posQty undefined) and must
    // read as flat (0). Deriving net from today's trade imbalance (buyQty - sellQty)
    // would show a PHANTOM open position after a close/F6 when the day's trades are
    // unbalanced (e.g. a carried-over position squared off today) — even though
    // /positions correctly shows flat. So trust the positionbook: absent => 0.
    const netQty = availability.positionsComplete ? rec.posQty ?? 0 : null
    const ltp = liveLtp?.(rec.symbol, rec.exchange) ?? rec.ltp ?? 0

    const realizedQty = Math.min(rec.buyQty, rec.sellQty)
    const crypto = rec.exchange === 'CRYPTO'
    const realizedPnl = !availability.tradesComplete ? null : crypto ? cryptoRealized(rec.fills)
      : realizedQty > 0 ? (sellAvg - buyAvg) * realizedQty : 0
    const multiplier = crypto ? rec.multiplier : 1
    const validMultiplier = multiplier != null && Number.isFinite(multiplier) && multiplier > 0

    let side: 'BUY' | 'SELL' | '-' = '-'
    let avgPrice = 0
    let unrealizedPnl: number | null = netQty == null ? null : 0
    // Use the BROKER position average for open positions (authoritative for
    // carried-over / partially-closed legs). Today's trade VWAP (buyAvg/sellAvg)
    // is only a fallback when the broker avg is missing — using it for unrealized
    // P&L would misprice positions opened on a prior day or partially closed today.
    if (netQty != null && netQty > 0) {
      side = 'BUY'
      avgPrice = rec.posAvg && rec.posAvg > 0 ? rec.posAvg : buyAvg
      unrealizedPnl = validMultiplier && ltp > 0 && avgPrice > 0 ? (ltp - avgPrice) * netQty * multiplier! : null
    } else if (netQty != null && netQty < 0) {
      side = 'SELL'
      avgPrice = rec.posAvg && rec.posAvg > 0 ? rec.posAvg : sellAvg
      unrealizedPnl = validMultiplier && ltp > 0 && avgPrice > 0 ? (avgPrice - ltp) * Math.abs(netQty) * multiplier! : null
    }

    const saved = findLegSL(slMap, rec.symbol, rec.exchange, rec.product as ScalpingProduct)
    const sl = netQty != null && netQty !== 0 && saved?.active && saved.side === side ? saved : undefined

    rows.push({
      symbol: rec.symbol,
      exchange: rec.exchange,
      product: rec.product as ScalpingProduct,
      side,
      netQty,
      currency: crypto ? 'USD' : 'INR',
      ltp,
      sl: sl ? sl.currentSl : null,
      target: sl && sl.target > 0 ? sl.target : null,
      trailingStep: sl?.trailingEnabled && sl.trailingStep > 0 ? sl.trailingStep : null,
      realizedPnl,
      unrealizedPnl,
      totalPnl: realizedPnl == null || unrealizedPnl == null ? null : realizedPnl + unrealizedPnl,
      avgPrice,
      buyQty: rec.buyQty,
      buyAvg,
      sellQty: rec.sellQty,
      sellAvg,
    })
  }

  // Open rows first, then alphabetical — keeps the active positions at the top.
  rows.sort(
    (a, b) =>
      (b.netQty !== 0 ? 1 : 0) - (a.netQty !== 0 ? 1 : 0) || a.symbol.localeCompare(b.symbol)
  )
  return rows
}
