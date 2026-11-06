import { expect, it, vi } from 'vitest'
import { webClient } from '@/api/client'
import { loadEmaBackfill } from './emaBackfill'
vi.mock('@/api/client', () => ({ webClient: { post: vi.fn() } }))
it('sends full closed OHLC and interval while retaining the close-only trend contract', async () => {
  const state = { points: [], count: 0, sum: 0, value: null }
  const ema = { '9': state, '15': state, alignment_algorithm: 'ema-9-15-21-alignment-v1', alignment_crosses: [] }
  vi.mocked(webClient.post).mockResolvedValue({ data: { status: 'success', ema } })
  const signal = new AbortController().signal
  const candles = [{ time: 60, open: 100, high: 104, low: 99, close: 103 }]
  expect(await loadEmaBackfill(candles, signal, { intervalSeconds: 60 })).toEqual(ema)
  expect(webClient.post).toHaveBeenLastCalledWith('/delta-chart/api/ema', { candles, interval_seconds: 60 }, { signal, timeout: 12000 })
  await loadEmaBackfill(candles, signal, { intervalSeconds: 900, allowSessionGaps: true })
  expect(webClient.post).toHaveBeenLastCalledWith('/delta-chart/api/ema', { candles, interval_seconds: 900, allow_session_gaps: true }, { signal, timeout: 12000 })
  const trend = [{ time: 60, close: 103 }]
  await loadEmaBackfill(trend, signal)
  expect(webClient.post).toHaveBeenLastCalledWith('/delta-chart/api/ema', { candles: trend }, { signal, timeout: 12000 })
})
