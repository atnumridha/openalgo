import { describe, expect, it } from 'vitest'
import { MatchMonitor } from './alerts'
import type { ScanRow } from './model'
const row = (state: ScanRow['state'], time = 100, fresh = true): ScanRow => ({
  symbol: 'BTCUSD',
  exchange: 'DELTA',
  state,
  fresh,
  time,
  observedAt: time + 60,
  source: 'Delta',
  direction: 'LONG setup',
  reason: 'Rule',
  values: {},
})
describe('visible screen match monitoring', () => {
  it('silently baselines and preserves matches across unknown observations', () => {
    const m = new MatchMonitor()
    expect(m.update([row('match')])).toEqual([])
    expect(m.update([row('unavailable', 200, false)])).toEqual([])
    expect(m.update([row('match', 300)])).toEqual([])
    m.update([row('no-match', 400)])
    expect(m.update([row('match', 500)])).toHaveLength(1)
    expect(m.update([row('match', 500)])).toEqual([])
    m.reset()
    expect(m.update([row('match', 600)])).toEqual([])
  })
  it('silently baselines a symbol first becoming available', () => {
    const m = new MatchMonitor()
    m.update([row('unavailable', 100, false)])
    expect(m.update([row('match', 200)])).toEqual([])
  })
})
