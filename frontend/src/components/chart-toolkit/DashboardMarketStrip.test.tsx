import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useLiveQuote } from '@/hooks/useLiveQuote'
import { DashboardMarketStrip } from './DashboardMarketStrip'

vi.mock('@/hooks/useLiveQuote', () => ({ useLiveQuote: vi.fn() }))
const quote = (ltp = 25100, close: number | undefined = 25000) => ({
  data: { ltp, close },
  isLive: true,
  isConnected: true,
  isLoading: false,
  isPaused: false,
  isFallbackMode: false,
  dataSource: 'websocket' as const,
  refresh: vi.fn(),
})
beforeEach(() => {
  vi.mocked(useLiveQuote).mockReturnValue(quote())
})
afterEach(() => {
  vi.useRealTimers()
  vi.clearAllMocks()
})

it('shows a large sticky Nifty price and computes positive daily movement from previous close', () => {
  render(<DashboardMarketStrip />)
  expect(screen.getByLabelText('NIFTY market summary')).toHaveAttribute('data-direction', 'up')
  expect(screen.getByLabelText('Index price')).toHaveTextContent('25,100.00')
  expect(screen.getByLabelText('Index price')).toHaveClass('text-3xl', 'md:text-4xl')
  expect(screen.getByLabelText('Day movement')).toHaveTextContent('+100.00 pts (+0.40%)')
  expect(screen.getByText('UP')).toBeInTheDocument()
  expect(screen.getByText(/Live feed/)).toBeInTheDocument()
  expect(screen.getByLabelText('NIFTY market summary')).toHaveClass(
    'sticky',
    'top-14',
    'z-30',
    'bg-emerald-950'
  )
  expect(useLiveQuote).toHaveBeenCalledWith(
    'NIFTY',
    'NSE_INDEX',
    expect.objectContaining({
      mode: 'Quote',
      useDepthFallback: false,
      refreshInterval: 1000,
      staleThreshold: 5000,
    })
  )
})
it('flips the entire summary to red when price crosses below previous close', () => {
  const view = render(<DashboardMarketStrip />)
  vi.mocked(useLiveQuote).mockReturnValue(quote(24950))
  view.rerender(<DashboardMarketStrip />)
  expect(screen.getByLabelText('NIFTY market summary')).toHaveClass('bg-red-950')
  expect(screen.getByText('DOWN')).toBeInTheDocument()
  expect(screen.getByLabelText('Day movement')).toHaveTextContent('-50.00 pts (-0.20%)')
})
it('preserves zero movement as neutral', () => {
  vi.mocked(useLiveQuote).mockReturnValue(quote(25000))
  render(<DashboardMarketStrip />)
  expect(screen.getByLabelText('Day movement')).toHaveTextContent('0.00 pts (0.00%)')
  expect(screen.getByText('UNCHANGED')).toBeInTheDocument()
  expect(screen.getByLabelText('NIFTY market summary')).toHaveAttribute('data-direction', 'neutral')
})
it('does not invent a day direction without a valid previous close', () => {
  vi.mocked(useLiveQuote).mockReturnValue({ ...quote(), data: { ltp: 25100, change: 100 } })
  render(<DashboardMarketStrip />)
  expect(screen.getByText(/Waiting for previous close/)).toBeInTheDocument()
  expect(screen.getByLabelText('NIFTY market summary')).toHaveAttribute('data-direction', 'neutral')
})
it('shows unavailable price honestly', () => {
  vi.mocked(useLiveQuote).mockReturnValue({
    ...quote(),
    data: {},
    isLive: false,
    dataSource: 'none',
  })
  render(<DashboardMarketStrip />)
  expect(screen.getByLabelText('Index price')).toHaveTextContent('—')
  expect(screen.getByText(/Waiting for broker quote/)).toBeInTheDocument()
})
it('labels REST as a broker snapshot with unverified freshness and neutral styling', () => {
  vi.mocked(useLiveQuote).mockReturnValue({ ...quote(), isLive: false, dataSource: 'rest' })
  render(<DashboardMarketStrip />)
  expect(screen.getByText(/Broker snapshot · freshness unverified/)).toBeInTheDocument()
  expect(screen.getByLabelText('NIFTY market summary')).toHaveAttribute('data-direction', 'neutral')
  expect(screen.queryByText(/Live feed/)).not.toBeInTheDocument()
})
it('ages live feed status even when no new quote causes a render', () => {
  vi.useFakeTimers()
  let live = true
  vi.mocked(useLiveQuote).mockImplementation(() => ({
    ...quote(),
    isLive: live,
    dataSource: live ? 'websocket' : 'none',
  }))
  render(<DashboardMarketStrip />)
  live = false
  act(() => {
    vi.advanceTimersByTime(1000)
  })
  expect(screen.queryByText(/Live feed/)).not.toBeInTheDocument()
  expect(screen.getByLabelText('NIFTY market summary')).toHaveAttribute('data-direction', 'neutral')
  expect(screen.getByText(/Feed unavailable or stale/)).toBeInTheDocument()
})
it('subscribes to the matching Sensex exchange', () => {
  render(<DashboardMarketStrip symbol="SENSEX" />)
  expect(useLiveQuote).toHaveBeenCalledWith('SENSEX', 'BSE_INDEX', expect.anything())
  expect(screen.getByLabelText('SENSEX market summary')).not.toHaveAttribute('aria-live')
})
