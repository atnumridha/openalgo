import type { CombinedSnapshot } from '@/api/combinedTerminal'

/** Expire a cached response even when no new HTTP response can reach the browser. */
export function synchronizedSnapshot(source: CombinedSnapshot, now: number, refreshFailed = false): CombinedSnapshot {
  if (!refreshFailed && source.connections.every(c => now - c.captured_at >= -1 && now - c.captured_at <= 5)) return source
  const connections = source.connections.map(c => {
    const age = now - c.captured_at
    const books = !refreshFailed && c.books_complete && age >= -1 && age <= 10
    const quotes = books && c.quotes_fresh && age <= 5
    const realized = books ? c.realized_net ?? null : null
    const open = quotes ? c.estimated_open_net ?? null : null
    return { ...c, books_complete: books, quotes_fresh: quotes, entry_ready: c.entry_ready && quotes,
      realized_net: realized, estimated_open_net: open, charges: books ? c.charges ?? null : null, estimated_exit_charges: quotes ? c.estimated_exit_charges ?? null : null,
      estimated_total_net: realized != null && open != null ? realized + open : null,
      funds: books ? c.funds : null, open_positions: books ? c.open_positions : null,
      pending_orders: books ? c.pending_orders : null, filled_entries: books ? c.filled_entries : null,
      error: !books ? c.error || 'Account refresh delayed · last-known trades retained' : !quotes ? c.error || 'Live price refresh delayed' : c.error }
  })
  const fresh = new Map(connections.map(c => [c.connection.id, c]))
  const allReal = connections.length > 0 && connections.every(c => c.realized_net != null)
  const allOpen = connections.length > 0 && connections.every(c => c.estimated_open_net != null)
  const realized = allReal ? connections.reduce((s, c) => s + (c.realized_net ?? 0), 0) : null
  const open = allOpen ? connections.reduce((s, c) => s + (c.estimated_open_net ?? 0), 0) : null
  return { ...source, connections,
    summary: { ...source.summary, complete: allReal && allOpen, realized_net: realized, estimated_open_net: open,
      estimated_total_net: realized != null && open != null ? realized + open : null,
      reason: 'Account refresh delayed · combined net unavailable until accounts synchronize' },
    positions: source.positions.map(p => fresh.get(p.connection_id)?.quotes_fresh ? p : { ...p, data_fresh: false, ltp: null, gross_open: null, net_open: null }),
    orders: source.orders?.map(o => ({ ...o, data_fresh: fresh.get(String(o.connection_id))?.books_complete === true })),
    day: { ...source.day, entry_allowed: false, net: null, pnl_available: false, count_verified: false, blocked_reason: 'Fresh synchronized account data required' } }
}
