import { expect, it } from 'vitest'
import { candleCloseRefreshDelay } from './candleCloseRefresh'

it('requests verified history just after the next BTCUSD candle close', () => {
  const now = Date.UTC(2026, 10, 1, 4, 34, 59, 900)
  expect(candleCloseRefreshDelay(now, 300)).toBe(150)
  expect(candleCloseRefreshDelay(now + 151, 300)).toBe(299999)
})
it('uses the exchange session anchor for hourly candles and its final shortened candle', () => {
  const session = { start: 555, end: 930, offset: 19800 }
  expect(candleCloseRefreshDelay(Date.parse('2026-11-02T10:14:59.900+05:30'), 3600, session)).toBe(
    150
  )
  expect(candleCloseRefreshDelay(Date.parse('2026-11-02T15:29:59.900+05:30'), 3600, session)).toBe(
    150
  )
})
it('schedules daily session data after the session closes and rejects invalid intervals', () => {
  const session = { start: 555, end: 930, offset: 19800 }
  expect(candleCloseRefreshDelay(Date.parse('2026-11-02T15:29:59.900+05:30'), 86400, session)).toBe(
    150
  )
  expect(candleCloseRefreshDelay(Date.now(), 0)).toBeNull()
})
