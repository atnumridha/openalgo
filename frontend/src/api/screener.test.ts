import { afterEach, expect, it, vi } from 'vitest'
import { readScreenerDelta } from './screener'
const history = vi.hoisted(() => vi.fn())
vi.mock('@/components/chart-toolkit/deltaFeed', () => ({ readDeltaHistory: history }))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  history.mockReset()
})
it('retains request observation, normalizes legacy Delta UTC transport once and uses actual tick metadata', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(2000000)
  history.mockImplementation(async (symbol, interval) => ({
    symbol,
    interval,
    candles: [{ time: 20800, open: 10, high: 12, low: 9, close: 11, volume: 50 }],
  }))
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ success: true, result: { symbol: 'BTCUSD', tick_size: '0.5' } }),
    }))
  )
  const result = await readScreenerDelta(
    { symbol: 'BTCUSD', exchange: 'DELTA' },
    '5m',
    new AbortController().signal
  )
  expect(result.observedAt).toBe(2000)
  expect(result.candles[0].time).toBe(1000)
  expect(result.daily[0].time).toBe(1000)
  expect(result.tickSize).toBe(0.5)
})
it('makes missing contract metadata explicit instead of inventing a tick', async () => {
  history.mockResolvedValue({ candles: [] })
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ success: true, result: { symbol: 'ETHUSD', tick_size: 1 } }),
    }))
  )
  const result = await readScreenerDelta(
    { symbol: 'BTCUSD', exchange: 'DELTA' },
    '1d',
    new AbortController().signal
  )
  expect(result.error).toMatch(/metadata/)
  expect(result.tickSize).toBeUndefined()
  expect(result.candles).toEqual([])
})
