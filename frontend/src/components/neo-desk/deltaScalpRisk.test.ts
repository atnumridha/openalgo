import { serverEmaFixture } from '../../test/fixtures/serverEma'
import { expect, it } from 'vitest'
import {
  buildDeltaScalpContext,
  scalpTargetPauseReason,
  type DeltaScalpHistory,
} from './deltaScalpRisk'
import { buildDeltaProtection } from './deltaRisk'
const now = Date.UTC(2026, 10, 2, 3) / 1000 + 1
const history = (interval: '1m' | '5m', down = false): DeltaScalpHistory => {
  const seconds = interval === '1m' ? 60 : 300
  const end = Math.floor(now / seconds) * seconds
  const result: DeltaScalpHistory = {
    status: 'success',
    symbol: 'BTCUSD',
    exchange: 'DELTA',
    interval,
    date: null,
    observedAt: now,
    candles: Array.from({ length: 101 }, (_, i) => {
      const value = down ? 2000 - i * 5 : 1000 + i * 5
      return {
        time: end - (100 - i) * seconds + 19800,
        open: value,
        high: value + (down ? 2 : 7),
        low: value - (down ? 7 : 2),
        close: value + (down ? -5 : 5),
        volume: 10,
      }
    }),
  }
  result.ema = serverEmaFixture(result.candles.slice(0,-1).map(b=>({...b,time:b.time-19800})))
  return result
}
it('builds fixed 1m risk from only completed 1m/5m candles, normalized to UTC', () => {
  const c = buildDeltaScalpContext('BTCUSD', history('1m'), history('5m'), now)
  expect(c).toMatchObject({
    symbol: 'BTCUSD',
    intervalSeconds: 60,
    sourceTime: now - 61,
    observedAt: now,
    direction: 'up',
    entryAligned: true,
  })
  expect(c?.bars.at(-1)).toMatchObject({ time: now - 61, close: 1500 })
  expect(c?.bars).toHaveLength(100)
  expect(c?.trendSummary).toContain('1m: Uptrend')
  expect(c?.trendSummary).toContain('5m: Uptrend')
  expect(buildDeltaProtection(c, 'buy', 1500, 0.5, now)).not.toBeNull()
})
it('requires confirmed agreement instead of silently skipping a missing higher filter', () => {
  const c = buildDeltaScalpContext('BTCUSD', history('1m'), history('5m', true), now)
  expect(c?.entryAligned).toBe(false)
  expect(buildDeltaProtection(c, 'buy', 1500, 0.5, now)).toBeNull()
  expect(buildDeltaScalpContext('BTCUSD', history('1m'), null, now)?.entryAligned).toBe(false)
  const slow = history('5m')
  slow.candles = slow.candles.map((b) => ({ ...b, open: 100, high: 101, low: 99, close: 100 }))
  slow.ema = serverEmaFixture(slow.candles.slice(0,-1).map(b=>({...b,time:b.time-19800})))
  expect(buildDeltaScalpContext('BTCUSD', history('1m'), slow, now)?.entryAligned).toBe(false)
})
it('fails closed for stale, wrong-contract, wrong-timeframe, forming-only and invalid recent evidence', () => {
  const fast = history('1m'),
    slow = history('5m')
  for (const bad of [
    { ...slow, symbol: 'ETHUSD' },
    { ...slow, exchange: 'NSE' },
    { ...slow, interval: '15m' },
    { ...slow, status: 'error' },
    { ...slow, observedAt: now - 31 },
    { ...slow, observedAt: now + 6 },
    { ...slow, candles: slow.candles.slice(-1) },
    { ...slow, candles: slow.candles.filter((_, i) => i !== 95) },
    { ...slow, candles: slow.candles.map((b, i) => (i === 95 ? { ...b, low: b.high + 1 } : b)) },
  ])
    expect(buildDeltaScalpContext('BTCUSD', fast, bad, now)?.entryAligned).toBe(false)
  expect(buildDeltaScalpContext('BTCUSD', fast, slow, now + 60)).toBeNull()
})
it('cannot confirm an old forming candle just by advancing the clock', () => {
  const fast = history('1m')
  fast.observedAt = now - 2
  expect(buildDeltaScalpContext('BTCUSD', fast, history('5m'), now)).toBeNull()
})
it('recovers after sufficient contiguous evidence following an old gap', () => {
  const fast = history('1m')
  fast.candles = fast.candles.filter((_, i) => i !== 10)
  fast.ema = serverEmaFixture(fast.candles.slice(10,-1).map(b=>({...b,time:b.time-19800})))
  expect(buildDeltaScalpContext('BTCUSD', fast, history('5m'), now)?.entryAligned).toBe(true)
})
const fees = {
  available_balance: 10,
  currency: 'USD',
  maker_fee_rate: 0.0002,
  taker_fee_rate: 0.0005,
  fee_tax_rate: 0.18,
  version: 'verified',
}
it('requires the target to cover verified maker-entry/market-exit fees plus a tick', () => {
  expect(scalpTargetPauseReason('buy', 78410, 78430, 0.5, fees)).toMatch(/fees/i)
  expect(scalpTargetPauseReason('sell', 78410, 78390, 0.5, fees)).toMatch(/fees/i)
  expect(scalpTargetPauseReason('buy', 78410, 78510, 0.5, fees)).toBeNull()
  expect(scalpTargetPauseReason('sell', 78410, 78310, 0.5, fees)).toBeNull()
  expect(scalpTargetPauseReason('buy', 78410, 78475, 0.5, fees)).not.toBeNull()
  expect(scalpTargetPauseReason('buy', 78410, 78475.5, 0.5, fees)).toBeNull()
})
it('does not fabricate or waive unavailable fees', () => {
  expect(scalpTargetPauseReason('buy', 78410, 78510, 0.5, null)).toMatch(/fee/i)
  expect(
    scalpTargetPauseReason('buy', 78410, 78510, 0.5, { ...fees, taker_fee_rate: undefined })
  ).not.toBeNull()
  expect(
    scalpTargetPauseReason('buy', 78410, 78510, 0.5, { ...fees, maker_fee_rate: -1 })
  ).not.toBeNull()
  expect(scalpTargetPauseReason('buy', 78410, 78400, 0.5, fees)).not.toBeNull()
})

it('retains fresh 1m protection context through a 5m-only outage while blocking new entries', async () => {
  const { deltaTrailingStop } = await import('./deltaRisk')
  const c = buildDeltaScalpContext('BTCUSD', history('1m'), null, now)
  expect(c?.entryAligned).toBe(false)
  expect(c?.sourceTime).toBe(now - 61)
  expect(buildDeltaProtection(c, 'buy', 1500, 0.5, now)).toBeNull()
  expect(deltaTrailingStop(c, 'buy', 1500, 1480, 1480, 1520, 0.5, 2, now)).toBeGreaterThan(1500)
})

it('revalidates the scalp data deadline at order preflight even if the UI has not rendered again', () => {
  const c = buildDeltaScalpContext('BTCUSD', history('1m'), history('5m'), now)
  expect(buildDeltaProtection(c, 'buy', 1500, 0.5, now)).not.toBeNull()
  expect(buildDeltaProtection(c, 'buy', 1500, 0.5, now + 31)).toBeNull()
  expect(buildDeltaProtection(c, 'buy', 1500, 0.5, now + 31, 'manual')).toBeNull()
})
