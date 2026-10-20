import type { TrackingTrade } from './trackingStore'

export function serializeTrackingBackup(scope: string, rows: TrackingTrade[]) {
  return JSON.stringify(
    {
      format: 'openalgo-tracking-only',
      version: 1,
      scope,
      trades: rows.filter((r) => r.scope === scope),
    },
    null,
    2
  )
}

export function parseTrackingBackup(scope: string, json: string): TrackingTrade[] {
  const data = JSON.parse(json)
  if (
    data?.format !== 'openalgo-tracking-only' ||
    data.version !== 1 ||
    !Array.isArray(data.trades)
  )
    throw new Error('Invalid tracking backup')
  if (data.scope !== scope) throw new Error('This backup belongs to another account')
  const ids = new Set<string>()
  for (const r of data.trades) {
    if (
      !r ||
      typeof r.id !== 'string' ||
      !r.id ||
      ids.has(r.id) ||
      r.scope !== scope ||
      typeof r.symbol !== 'string' ||
      !/^[A-Z0-9][A-Z0-9 ._-]{0,79}$/.test(r.symbol) ||
      !['NFO', 'BFO'].includes(r.exchange) ||
      ![r.lot, r.lots, r.lot * r.lots].every((n) => Number.isSafeInteger(n) && n > 0) ||
      ![r.entry, r.created].every((n) => typeof n === 'number' && Number.isFinite(n) && n > 0) ||
      ['tick', 'sl', 'target', 'reward_ratio', 'closed', 'exit'].some(
        (key) =>
          r[key] != null && !(typeof r[key] === 'number' && Number.isFinite(r[key]) && r[key] > 0)
      ) ||
      (r.automatic_sl != null && typeof r.automatic_sl !== 'boolean') ||
      (r.closed != null) !== (r.exit != null) ||
      (r.sl != null && r.sl >= r.entry) ||
      (r.target != null && r.target <= r.entry)
    )
      throw new Error('Invalid trade in tracking backup; nothing was imported')
    ids.add(r.id)
  }
  return data.trades
}
