import { beforeEach, expect, it } from 'vitest'
import { readHistorySnapshot, saveHistorySnapshot } from './historySnapshot'
const now = Date.parse('2026-10-27T05:00:00Z')
const value = {
  status: 'success',
  symbol: 'NIFTY',
  exchange: 'NSE_INDEX',
  interval: '15m',
  date: '2026-10-27',
  candles: [{ time: now / 1000, open: 100, high: 102, low: 99, close: 101, volume: 0 }],
}
beforeEach(() => localStorage.clear())
it('restores a recent successful chart immediately without mixing markets, timeframes or users', () => {
  saveHistorySnapshot('userA', 'live', value, now)
  expect(readHistorySnapshot('userA', 'live', 'NIFTY', 'NSE_INDEX', '15m', now + 1000)).toEqual(
    value
  )
  expect(readHistorySnapshot('userB', 'live', 'NIFTY', 'NSE_INDEX', '15m', now)).toBeUndefined()
  expect(readHistorySnapshot('userA', 'live', 'SENSEX', 'BSE_INDEX', '15m', now)).toBeUndefined()
  expect(readHistorySnapshot('userA', 'live', 'NIFTY', 'NSE_INDEX', '5m', now)).toBeUndefined()
  expect(readHistorySnapshot('userA', 'analyzer', 'NIFTY', 'NSE_INDEX', '15m', now)).toBeUndefined()
})
it('does not reuse expired, corrupt or invalid candles as a chart snapshot', () => {
  saveHistorySnapshot('userA', 'live', value, now)
  expect(
    readHistorySnapshot('userA', 'live', 'NIFTY', 'NSE_INDEX', '15m', now + 86400001)
  ).toBeUndefined()
  saveHistorySnapshot(
    'userA',
    'live',
    { ...value, candles: [{ ...value.candles[0], high: 90 }] },
    now
  )
  expect(readHistorySnapshot('userA', 'live', 'NIFTY', 'NSE_INDEX', '15m', now)).toEqual(value)
  localStorage.setItem(localStorage.key(0)!, '{broken')
  expect(readHistorySnapshot('userA', 'live', 'NIFTY', 'NSE_INDEX', '15m', now)).toBeUndefined()
})
it('bounds snapshots rather than accumulating unlimited candle history', () => {
  saveHistorySnapshot(
    'userA',
    'live',
    {
      ...value,
      candles: Array.from({ length: 3000 }, (_, i) => ({
        ...value.candles[0],
        time: now / 1000 + i * 900,
      })),
    },
    now
  )
  expect(
    readHistorySnapshot('userA', 'live', 'NIFTY', 'NSE_INDEX', '15m', now)?.candles
  ).toHaveLength(1200)
})
