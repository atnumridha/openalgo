import { expect, it, vi } from 'vitest'
import { deltaCandle, readDeltaHistory } from './deltaFeed'
it('decodes current compact Delta candles in UTC and rejects another symbol or resolution', () => {
  const message = {
    type: 'candlestick_5m',
    sy: 'BTCUSD',
    res: '5m',
    ts: 1792987800123456,
    o: 79000,
    h: 79010,
    l: 78990,
    c: 79005,
    v: 120,
  }
  expect(deltaCandle(message, 'BTCUSD', '5m')).toEqual({
    bar: { time: 1792987800, open: 79000, high: 79010, low: 78990, close: 79005, volume: 120 },
    published: 1792987800.123456,
  })
  expect(deltaCandle(message, 'ETHUSD', '5m')).toBeNull()
  expect(deltaCandle(message, 'BTCUSD', '1m')).toBeNull()
  expect(deltaCandle({ ...message, h: 78000 }, 'BTCUSD', '5m')).toBeNull()
  expect(
    deltaCandle({ ...message, cst: 1792987800000000, ts: 1792988101123456 }, 'BTCUSD', '5m')?.bar
      .time
  ).toBe(1792987800)
})
it('normalizes public history to the existing host contract exactly once and sends no credentials', async () => {
  const fetcher = vi.fn(async () => ({
    ok: true,
    json: async () => ({
      success: true,
      result: [{ time: 1792987800, open: 100, high: 101, low: 99, close: 100, volume: 5 }],
    }),
  }))
  vi.stubGlobal('fetch', fetcher)
  try {
    const result = await readDeltaHistory('BTCUSD', '5m')
    expect(result.candles[0].time).toBe(1793007600)
    expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: 'omit' })
  } finally {
    vi.unstubAllGlobals()
  }
})

it('loads SOL and JUP histories and rejects unsafe or non-USD symbols before requesting', async () => {
  const fetcher = vi.fn(async () => ({
    ok: true,
    json: async () => ({ success: true, result: [] }),
  }))
  vi.stubGlobal('fetch', fetcher)
  try {
    expect((await readDeltaHistory('SOLUSD', '5m')).exchange).toBe('DELTA')
    expect((await readDeltaHistory('JUPUSD', '1m')).symbol).toBe('JUPUSD')
    for (const symbol of ['../BTCUSD', 'BTCUSDT', 'solusd', 'USD', 'BTCUSD&symbol=ETHUSD'])
      await expect(readDeltaHistory(symbol, '5m')).rejects.toThrow('Unsupported Delta')
    expect(fetcher).toHaveBeenCalledTimes(2)
  } finally {
    vi.unstubAllGlobals()
  }
})
