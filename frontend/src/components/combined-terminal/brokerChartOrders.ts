import type { CombinedSnapshot } from '@/api/combinedTerminal'
import { brokerName } from '@/api/combinedTerminal'

export interface BrokerChartOrder {
  key: string
  connectionId: string
  confirmed: boolean
  name: string
  side: string
  remaining: number | null
  price: number | null
  kind: 'SL' | 'Limit' | 'Market' | 'Order'
  status: string
}
export interface BrokerChartLevel { price: number; title: string; color: string }
const number = (value: unknown): number | null => {
  if (typeof value !== 'number' && (typeof value !== 'string' || !value.trim())) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}
const positive = (value: unknown) => { const n = number(value); return n != null && n > 0 ? n : null }
const active = new Set(['open', 'pending', 'trigger pending', 'trigger_pending', 'partially filled', 'partially_filled'])
const terminal = new Set(['complete', 'completed', 'cancelled', 'canceled', 'rejected'])

/** Read-only account observations. No adoption, cancellation or order mutations. */
export function brokerChartOrders(snapshot: CombinedSnapshot | undefined, symbol: string, exchange: string, now: number) {
  const orders: BrokerChartOrder[] = [], levels: BrokerChartLevel[] = []
  if (!snapshot || exchange === 'DELTA') return { orders, levels, checkedAt: null, complete: false }
  const accounts = snapshot.connections.filter(c => c.connection.mode === snapshot.mode)
  const fresh = new Map(accounts.filter(c => c.books_complete && now - c.captured_at >= -1 && now - c.captured_at <= 10).map(c => [c.connection.id, c]))
  const seen = new Set<string>()
  for (const row of snapshot.orders ?? []) {
    const id = typeof row.connection_id === 'string' ? row.connection_id : ''
    const account = fresh.get(id)
    const orderId = row.orderid == null ? '' : String(row.orderid).trim()
    const status = String(row.order_status ?? '').trim().toLowerCase()
    if (!account || row.mode != null && row.mode !== snapshot.mode || row.symbol !== symbol || row.exchange !== exchange || row.data_fresh !== true || !orderId || terminal.has(status)) continue
    const key = `${id}:${orderId}`
    if (seen.has(key)) continue
    seen.add(key)
    const side = String(row.action ?? '').toUpperCase()
    const size = positive(row.quantity), filled = number(row.filled_quantity), pending = number(row.pending_quantity)
    const remaining = size != null && Number.isSafeInteger(size) && filled != null && Number.isSafeInteger(filled) && filled >= 0 && filled <= size
      ? size - filled : size != null && pending != null && Number.isSafeInteger(pending) && pending >= 0 && pending <= size ? pending : null
    if (remaining === 0) continue
    const type = String(row.pricetype ?? '').toUpperCase()
    const kind = type.startsWith('SL') ? 'SL' : type === 'LIMIT' ? 'Limit' : type === 'MARKET' ? 'Market' : 'Order'
    const price = kind === 'SL' ? positive(row.trigger_price) : kind === 'Limit' ? positive(row.price) : null
    const name = brokerName(account.connection.broker)
    const confirmed = active.has(status) && remaining != null && price != null && ['BUY', 'SELL'].includes(side)
    orders.push({ key, connectionId: id, confirmed, name, side, remaining, price, kind, status: status || 'status unconfirmed' })
    if (confirmed && remaining != null && price != null) {
      levels.push({ price, title: `${name} ${kind === 'SL' ? 'SL' : 'limit'} ${side} ${remaining}`, color: kind === 'SL' ? '#ef5350' : '#2962ff' })
    }
  }
  for (const row of snapshot.positions) {
    const account = fresh.get(row.connection_id)
    if (!account || row.symbol !== symbol || row.exchange !== exchange || !Number.isSafeInteger(row.quantity) || row.quantity === 0) continue
    const name = brokerName(account.connection.broker)
    const average = row.average_entry_verified === false ? null : positive(row.average_entry)
    if (average != null) levels.push({ price: average, title: `${name} position avg · ${Math.abs(row.quantity)}`, color: '#2962ff' })
    // Only the actual orderbook can establish a broker SL. Saved controller
    // status may lag a cancellation; server targets are labelled separately.
    if (row.managed && row.status === 'protected') {
      const target = positive(row.target)
      if (target != null) levels.push({ price: target, title: `${name} target (server)`, color: '#26a69a' })
    }
  }
  return { orders, levels, complete: accounts.length > 0 && fresh.size === accounts.length,
    checkedAt: fresh.size ? Math.min(...Array.from(fresh.values(), c => c.captured_at)) : null }
}
