import { useEffect } from 'react'
import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { usePageVisibility } from '@/hooks/usePageVisibility'
import { MarketDataProvider, useMarketDataContext } from './MarketDataContext'

const mocks = vi.hoisted(() => ({
  manager: {
    getState: vi.fn(() => ({
      connectionState: 'authenticated',
      isConnected: true,
      isAuthenticated: true,
      isPaused: false,
      isFallbackMode: false,
      connectionEpoch: 1,
      error: null,
    })),
    addStateListener: vi.fn(() => vi.fn()),
    pauseConnection: vi.fn(),
    resumeConnection: vi.fn(),
  },
}))
vi.mock('@/lib/MarketDataManager', () => ({
  MarketDataManager: { getInstance: () => mocks.manager },
}))
vi.mock('@/hooks/usePageVisibility', () => ({ usePageVisibility: vi.fn() }))

function TabQuote() {
  const { retainBackgroundUpdates } = useMarketDataContext()
  useEffect(() => retainBackgroundUpdates?.(), [retainBackgroundUpdates])
  return null
}
const visibility = (isVisible: boolean) => ({ isVisible }) as ReturnType<typeof usePageVisibility>
beforeEach(() => {
  vi.useFakeTimers()
  vi.mocked(usePageVisibility).mockReturnValue(visibility(true))
})
afterEach(() => {
  vi.useRealTimers()
  vi.clearAllMocks()
})

it('keeps a tab quote live while hidden and resumes ordinary pausing when it leaves', () => {
  const view = render(
    <MarketDataProvider>
      <TabQuote />
    </MarketDataProvider>
  )
  vi.mocked(usePageVisibility).mockReturnValue(visibility(false))
  view.rerender(
    <MarketDataProvider>
      <TabQuote />
    </MarketDataProvider>
  )
  act(() => {
    vi.advanceTimersByTime(6000)
  })
  expect(mocks.manager.pauseConnection).not.toHaveBeenCalled()
  view.rerender(
    <MarketDataProvider>
      <span>Another page</span>
    </MarketDataProvider>
  )
  act(() => {
    vi.advanceTimersByTime(5000)
  })
  expect(mocks.manager.pauseConnection).toHaveBeenCalledTimes(1)
})

it('keeps background updates until the last tab quote consumer leaves', () => {
  const view = render(
    <MarketDataProvider>
      <TabQuote key="one" />
      <TabQuote key="two" />
    </MarketDataProvider>
  )
  vi.mocked(usePageVisibility).mockReturnValue(visibility(false))
  view.rerender(
    <MarketDataProvider>
      <TabQuote key="two" />
    </MarketDataProvider>
  )
  act(() => {
    vi.advanceTimersByTime(6000)
  })
  expect(mocks.manager.pauseConnection).not.toHaveBeenCalled()
  view.rerender(
    <MarketDataProvider>
      <span>Another page</span>
    </MarketDataProvider>
  )
  act(() => {
    vi.advanceTimersByTime(5000)
  })
  expect(mocks.manager.pauseConnection).toHaveBeenCalledTimes(1)
})

it('resumes an already paused feed when a background quote starts watching', () => {
  mocks.manager.getState.mockReturnValueOnce({
    ...mocks.manager.getState(),
    connectionState: 'paused',
    isPaused: true,
    isConnected: false,
    isAuthenticated: false,
  })
  vi.mocked(usePageVisibility).mockReturnValue(visibility(false))
  render(
    <MarketDataProvider>
      <TabQuote />
    </MarketDataProvider>
  )
  expect(mocks.manager.resumeConnection).toHaveBeenCalledTimes(1)
})
