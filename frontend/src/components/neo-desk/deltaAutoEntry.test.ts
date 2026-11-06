import { beforeEach, expect, it } from 'vitest'
import { claimDeltaAutoEntry } from './deltaAutoEntry'
beforeEach(() => sessionStorage.clear())
it('allows one attempt per candle across remounts and toggle cycles, then accepts the next candle', () => {
  expect(claimDeltaAutoEntry(sessionStorage, 'account', 'BTCUSD', 60, 120)).toBe(true)
  expect(claimDeltaAutoEntry(sessionStorage, 'account', 'BTCUSD', 60, 120)).toBe(false)
  expect(claimDeltaAutoEntry(sessionStorage, 'account', 'BTCUSD', 60, 60)).toBe(false)
  expect(claimDeltaAutoEntry(sessionStorage, 'account', 'BTCUSD', 60, 180)).toBe(true)
})
it('separates accounts, symbols and intervals', () => {
  expect(claimDeltaAutoEntry(sessionStorage, 'a', 'BTCUSD', 60, 120)).toBe(true)
  expect(claimDeltaAutoEntry(sessionStorage, 'b', 'BTCUSD', 60, 120)).toBe(true)
  expect(claimDeltaAutoEntry(sessionStorage, 'a', 'ETHUSD', 60, 120)).toBe(true)
  expect(claimDeltaAutoEntry(sessionStorage, 'a', 'BTCUSD', 300, 120)).toBe(true)
})
it('fails closed on malformed persistent tracking', () => {
  sessionStorage.setItem('delta-chart:auto-entry:v1:a:BTCUSD:60', '{}')
  expect(() => claimDeltaAutoEntry(sessionStorage, 'a', 'BTCUSD', 60, 120)).toThrow()
})
