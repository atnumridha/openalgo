import { setDeltaDisplayCurrency } from '@/hooks/useDeltaDisplayCurrency'
import { deltaMoney } from '@/lib/deltaCurrency'
/**
 * The navbar badge states Delta's fee schedule as the risk API sends it, in
 * percent, and its net P&L is the Positions page's Net P&L total.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RiskOverview } from '@/api/risk'
import { DEFAULT_FEE_PROFILE, positionFees } from '@/lib/cryptoFees'
import { act, fireEvent, render, screen, waitFor } from '@/test/test-utils'
import type { Position } from '@/types/trading'

const mocks = vi.hoisted(() => ({
  getPositions: vi.fn(),
  getOverview: vi.fn(),
  getQuotes: vi.fn(),
}))

vi.mock('@/api/trading', () => ({
  tradingApi: { getPositions: mocks.getPositions, getQuotes: mocks.getQuotes },
}))
vi.mock('@/api/risk', () => ({ riskApi: { getOverview: mocks.getOverview } }))
vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ apiKey: 'test-api-key', user: { broker: 'deltaexchange' } }),
}))
vi.mock('@/hooks/useLivePrice', () => ({
  useLivePrice: (positions: Position[]) => ({ data: positions, isLive: false, isPaused: false }),
}))
vi.mock('@/hooks/usePageVisibility', () => ({
  usePageVisibility: () => ({ isVisible: true, wasHidden: false, timeSinceHidden: 0 }),
}))

import DeltaFeeBadge, { deltaFeeText } from './DeltaFeeBadge'

const FEES: RiskOverview['fees'] = {
  maker_pct: 0.02,
  taker_pct: 0.05,
  gst_pct: 18,
  round_trip_taker_pct: 0.118,
}

const BTC_LONG = {
  symbol: 'BTCUSDFUT',
  exchange: 'CRYPTO',
  product: 'NRML',
  quantity: 59,
  average_price: 84646.5,
  ltp: 84657.5,
  mark_price: 84657.5,
  pnl: 0.649,
  pnlpercent: 0.013,
  lot_size: 0.001,
  fees_paid: 2.95,
} as Position

describe('deltaFeeText', () => {
  it('shows the risk API percentages as they are sent', () => {
    expect(deltaFeeText(FEES)).toBe('Maker 0.02% · Taker 0.05% plus 18% GST')
  })

  it('says nothing when the server sent no schedule', () => {
    expect(deltaFeeText(undefined)).toBeNull()
    expect(deltaFeeText({})).toBeNull()
  })
})

describe('DeltaFeeBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mocks.getPositions.mockResolvedValue({ status: 'success', data: [BTC_LONG] })
    mocks.getOverview.mockResolvedValue({
      leverage: 10,
      liquidation_move_pct: 9.75,
      maintenance_margin_pct: 0.25,
      fees: FEES,
      strategies: [],
    } satisfies RiskOverview)
    mocks.getQuotes.mockResolvedValue({ status: 'error' })
  })

  it('reads 0.02% maker and 0.05% taker, not 2.00% and 5.00%', async () => {
    render(<DeltaFeeBadge />)
    await screen.findByTestId('delta-net-pnl')
    // The schedule sits in the popover, so the navbar itself stays one line.
    expect(screen.queryByTestId('delta-fee-rates')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Net P&L after fees/ }))
    const rates = await screen.findByTestId('delta-fee-rates')
    expect(rates.textContent).toContain('Maker 0.02%')
    expect(rates.textContent).toContain('Taker 0.05%')
    expect(rates.textContent).not.toContain('2.00%')
    expect(rates.textContent).not.toContain('5.00%')
  })

  it('shows the Positions page net total', async () => {
    const net = positionFees(BTC_LONG, DEFAULT_FEE_PROFILE).net
    render(<DeltaFeeBadge />)
    await waitFor(() =>
      expect(screen.getByTestId('delta-net-pnl').textContent).toBe(deltaMoney(net, 'INR'))
    )
  })
})

it('updates the top-bar amount immediately when the shared currency changes, without requesting spot FX', async () => {
  localStorage.clear()
  mocks.getPositions.mockResolvedValue({ status: 'success', data: [BTC_LONG] })
  mocks.getOverview.mockResolvedValue(null)
  render(<DeltaFeeBadge />)
  const net = positionFees(BTC_LONG, DEFAULT_FEE_PROFILE).net
  await waitFor(() =>
    expect(screen.getByTestId('delta-net-pnl')).toHaveTextContent(deltaMoney(net, 'INR'))
  )
  act(() => setDeltaDisplayCurrency(undefined, 'USD'))
  expect(screen.getByTestId('delta-net-pnl')).toHaveTextContent(deltaMoney(net, 'USD'))
  act(() => setDeltaDisplayCurrency(undefined, 'INR'))
  expect(screen.getByTestId('delta-net-pnl')).toHaveTextContent(deltaMoney(net, 'INR'))
  expect(mocks.getQuotes).not.toHaveBeenCalled()
})
