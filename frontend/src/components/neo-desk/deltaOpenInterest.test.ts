import { expect, it, vi } from 'vitest'
import { deltaOiSignal, readDeltaOpenInterest } from './deltaOpenInterest'
const t = 1793332800,
  prices = [
    { time: t, open: 100, high: 101, low: 99, close: 100 },
    { time: t + 300, open: 101, high: 103, low: 100, close: 102 },
  ]
const source = {
  symbol: 'BTCUSD',
  interval: '5m',
  observedAt: t + 600,
  bars: [
    { time: t, open: 1000, high: 1010, low: 990, close: 1000 },
    { time: t + 300, open: 1050, high: 1110, low: 1040, close: 1100 },
  ],
}
it('derives LONG/SHORT context only from matched completed OI and own price candles', () => {
  expect(deltaOiSignal(source, prices, 300, t + 600, t + 600).side).toBe('CALL')
  expect(
    deltaOiSignal(source, [prices[0], { ...prices[1], close: 99 }], 300, t + 600, t + 600).side
  ).toBe('PUT')
  expect(
    deltaOiSignal(
      { ...source, bars: [source.bars[0], { ...source.bars[1], close: 900 }] },
      prices,
      300,
      t + 600,
      t + 600
    ).side
  ).toBe('WAIT')
})
it('rejects stale, unmatched and still-forming OI rather than guessing a signal', () => {
  expect(deltaOiSignal(source, prices, 300, t + 599, t + 600).side).toBe('WAIT')
  expect(deltaOiSignal(source, prices, 300, t + 600, t + 1200).value).toBeNull()
  expect(
    deltaOiSignal({ ...source, bars: source.bars.slice(1) }, prices, 300, t + 600, t + 600).side
  ).toBe('WAIT')
})
it('reads public OI history with no credentials and preserves UTC timestamps', async () => {
  const fetcher = vi.fn(async () => ({
    ok: true,
    json: async () => ({ success: true, result: source.bars }),
  }))
  vi.stubGlobal('fetch', fetcher)
  try {
    const r = await readDeltaOpenInterest('BTCUSD', '5m', new AbortController().signal)
    expect(fetcher.mock.calls[0][0]).toContain('symbol=OI%3ABTCUSD')
    expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: 'omit' })
    expect(r.bars[0].time).toBe(t)
  } finally {
    vi.unstubAllGlobals()
  }
})
