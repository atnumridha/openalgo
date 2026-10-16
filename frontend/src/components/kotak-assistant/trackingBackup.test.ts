import { expect, it } from 'vitest'
import { parseTrackingBackup, serializeTrackingBackup } from './trackingBackup'
import type { TrackingTrade } from './trackingStore'

const row: TrackingTrade = {
  id: 'record-1',
  scope: 'alice:kotak',
  symbol: 'NIFTY19OCT2623100CE',
  exchange: 'NFO',
  lot: 65,
  lots: 1,
  entry: 100,
  sl: 90,
  target: 130,
  reward_ratio: 3,
  automatic_sl: true,
  tick: 0.05,
  created: 1792026000,
}
it('round-trips open and closed records with their original prices, levels and IDs', () => {
  const closed = { ...row, id: 'record-2', exit: 125, closed: row.created + 100 }
  const json = serializeTrackingBackup(row.scope, [row, closed])
  expect(parseTrackingBackup(row.scope, json)).toEqual([row, closed])
})
it('rejects another account, malformed prices and partial invalid files before writing anything', () => {
  expect(() => parseTrackingBackup('bob:kotak', serializeTrackingBackup(row.scope, [row]))).toThrow(
    /account/
  )
  const bad = JSON.parse(serializeTrackingBackup(row.scope, [row]))
  bad.trades.push({ ...row, id: 'bad', entry: -1 })
  expect(() => parseTrackingBackup(row.scope, JSON.stringify(bad))).toThrow(/Invalid/)
  expect(() => parseTrackingBackup(row.scope, '{')).toThrow()
})
