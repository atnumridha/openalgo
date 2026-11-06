import { loadEmaBackfill } from '../chart-toolkit/emaBackfill'
import { serverEmaFixture } from '../../test/fixtures/serverEma'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { readDeltaHistory } from '../chart-toolkit/deltaFeed'
import { useDeltaScalpRisk } from './useDeltaScalpRisk'
vi.mock('../chart-toolkit/deltaFeed', () => ({ readDeltaHistory: vi.fn() }))
vi.mock('../chart-toolkit/emaBackfill', () => ({ loadEmaBackfill: vi.fn(async (candles) => serverEmaFixture(candles)) }))
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.resetAllMocks()
})
const now = Date.UTC(2026, 10, 2, 3) + 1000
function setup() {
  vi.mocked(loadEmaBackfill).mockImplementation(async candles=>serverEmaFixture(candles))
  vi.spyOn(Date, 'now').mockReturnValue(now)
  vi.mocked(readDeltaHistory).mockImplementation(async (symbol, interval) => {
    const seconds = interval === '5m' ? 300 : 60,
      end = Math.floor(Date.now() / 1000 / seconds) * seconds
    return {
      status: 'success',
      symbol,
      exchange: 'DELTA',
      interval,
      date: null,
      candles: Array.from({ length: 101 }, (_, i) => ({
        time: end - (100 - i) * seconds + 19800,
        open: 1000 + i * 5,
        high: 1007 + i * 5,
        low: 998 + i * 5,
        close: 1005 + i * 5,
        volume: 1,
      })),
    }
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return {
    client,
    wrapper: ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  }
}
it('loads the independent 1m/5m sources and clears risk if either source fails', async () => {
  const { client, wrapper } = setup()
  const { result } = renderHook(() => useDeltaScalpRisk('BTCUSD', true), { wrapper })
  await waitFor(() => expect(result.current?.entryAligned).toBe(true))
  expect(
    vi
      .mocked(readDeltaHistory)
      .mock.calls.map((c) => c[1])
      .sort()
  ).toEqual(['1m', '5m'])
  vi.mocked(readDeltaHistory).mockRejectedValue(new Error('Offline'))
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['delta-scalp-history', 'BTCUSD'] })
  })
  await waitFor(() => expect(result.current).toBeNull())
})
it('does not expose cached execution context when disabled for replay or non-live views', async () => {
  const { wrapper } = setup()
  const view = renderHook(({ active }) => useDeltaScalpRisk('BTCUSD', active), {
    wrapper,
    initialProps: { active: false },
  })
  expect(view.result.current).toBeNull()
  expect(readDeltaHistory).not.toHaveBeenCalled()
  view.rerender({ active: true })
  await waitFor(() => expect(view.result.current).not.toBeNull())
  view.rerender({ active: false })
  expect(view.result.current).toBeNull()
})
it('rejects old-symbol context during a symbol switch', async () => {
  const { wrapper } = setup()
  const view = renderHook(({ symbol }) => useDeltaScalpRisk(symbol, true), {
    wrapper,
    initialProps: { symbol: 'BTCUSD' },
  })
  await waitFor(() => expect(view.result.current?.symbol).toBe('BTCUSD'))
  vi.mocked(readDeltaHistory).mockImplementation(() => new Promise(() => {}))
  view.rerender({ symbol: 'ETHUSD' })
  expect(view.result.current).toBeNull()
})
it('refreshes at the minute close without a chart stream and stops timers after unmount', async () => {
  const { wrapper } = setup()
  vi.mocked(Date.now).mockRestore()
  vi.useFakeTimers()
  vi.setSystemTime(now)
  try {
    const view = renderHook(() => useDeltaScalpRisk('BTCUSD', true), { wrapper })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(view.result.current?.sourceTime).toBe(now / 1000 - 61)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(59060)
    })
    expect(view.result.current?.sourceTime).toBe(now / 1000 - 1)
    view.unmount()
    const count = vi.mocked(readDeltaHistory).mock.calls.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000)
    })
    expect(readDeltaHistory).toHaveBeenCalledTimes(count)
  } finally {
    vi.useRealTimers()
  }
})

it('keeps verified fast management evidence when only the higher source fails', async () => {
  const { wrapper, client } = setup()
  const { result } = renderHook(() => useDeltaScalpRisk('BTCUSD', true), { wrapper })
  await waitFor(() => expect(result.current?.entryAligned).toBe(true))
  const original = vi.mocked(readDeltaHistory).getMockImplementation()!
  vi.mocked(readDeltaHistory).mockImplementation((symbol, interval, date, signal) =>
    interval === '5m'
      ? Promise.reject(new Error('5m offline'))
      : original(symbol, interval, date, signal)
  )
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['delta-scalp-history', 'BTCUSD', '5m'] })
  })
  await waitFor(() => expect(result.current?.entryAligned).toBe(false))
  expect(result.current?.intervalSeconds).toBe(60)
  expect(result.current?.direction).toBe('up')
})

it('expires cached entry approval while offline/background refetches are paused', async () => {
  const { onlineManager } = await import('@tanstack/react-query')
  const { wrapper } = setup()
  vi.mocked(Date.now).mockRestore()
  vi.useFakeTimers()
  vi.setSystemTime(now)
  try {
    const view = renderHook(() => useDeltaScalpRisk('BTCUSD', true), { wrapper })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(view.result.current?.entryAligned).toBe(true)
    onlineManager.setOnline(false)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31000)
    })
    expect(view.result.current).toBeNull()
    view.unmount()
  } finally {
    onlineManager.setOnline(true)
    vi.useRealTimers()
  }
})
