/**
 * Crypto positions show the leverage, stop loss, take profit and fees of the
 * trade, not just its price and P&L.
 *
 * The stop and target are the running strategy's, published through
 * /leverage/api/risk. A position no strategy reports on says so instead of
 * showing a blank, because an unmanaged perpetual with leverage is exactly
 * the row a trader needs to notice.
 */

import { act, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RiskOverview } from '@/api/risk'
import { render, screen, within } from '@/test/test-utils'
import type { Position } from '@/types/trading'

const mocks = vi.hoisted(() => ({
  getPositions: vi.fn(),
  getOverview: vi.fn(),
}))

vi.mock('@/api/trading', () => ({
  tradingApi: {
    getPositions: mocks.getPositions,
    closePosition: vi.fn(),
    closeAllPositions: vi.fn(),
  },
}))

vi.mock('@/api/deltaProfitProtection', () => ({
  deltaProfitApi: { status: async () => ({ plans: [], heartbeat: Date.now() / 1000 }) },
}))

vi.mock('@/api/risk', () => ({ riskApi: { getOverview: mocks.getOverview } }))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ apiKey: 'test-api-key', user: { broker: 'deltaexchange' } }),
}))
vi.mock('@/stores/themeStore', () => ({ onModeChange: () => () => {} }))
vi.mock('@/hooks/useLivePrice', () => ({
  useLivePrice: (positions: Position[]) => ({ data: positions, isLive: false, isPaused: false }),
}))
vi.mock('@/hooks/useOrderEventRefresh', () => ({ useOrderEventRefresh: () => {} }))
vi.mock('@/hooks/usePageVisibility', () => ({
  usePageVisibility: () => ({ isVisible: true, wasHidden: false, timeSinceHidden: 0 }),
}))
vi.mock('@/hooks/useSupportedExchanges', () => ({
  useSupportedExchanges: () => ({ isCrypto: true }),
}))

import Positions from './Positions'

const BTC_SHORT = {
  symbol: 'BTCUSDFUT',
  exchange: 'CRYPTO',
  product: 'NRML',
  quantity: -1,
  average_price: 85000,
  ltp: 84575,
  pnl: 0.425,
  lot_size: 0.001,
} as Position

const ETH_LONG = {
  symbol: 'ETHUSDFUT',
  exchange: 'CRYPTO',
  product: 'NRML',
  quantity: 2,
  average_price: 3000,
  ltp: 3000,
  pnl: 0,
  lot_size: 0.01,
} as Position

const OVERVIEW: RiskOverview = {
  leverage: 10,
  liquidation_move_pct: 9.75,
  maintenance_margin_pct: 0.25,
  fees: { taker_pct: 0.05, maker_pct: 0.02, gst_pct: 18, round_trip_taker_pct: 0.118 },
  strategies: [
    {
      strategy: 'Delta BTC RSI Fade 1h',
      strategy_id: 'delta_btc_rsi_fade_1h_1',
      symbol: 'BTCUSDFUT',
      exchange: 'CRYPTO',
      product: 'NRML',
      mode: 'analyze',
      updated_at: '2026-10-02T10:05:00+05:30',
      age_seconds: 4,
      running: true,
      leverage: 10,
      liquidation_move_pct: 9.75,
      contract_btc: 0.001,
      quantity: 1,
      fees: { taker_pct_per_side: 0.05, gst_pct: 18, round_trip_pct: 0.118, funding: '8h' },
      rules: {
        entry: 'RSI(7) on closed 1h bar: < 20 long, > 80 short',
        stop: '3 x ATR(14), 0.25-1.0% of price',
        take_profit: 'trailing from +1x stop, 0.5x stop behind best price',
        max_hold_hours: 8,
        daily_loss_cap_pct: 1,
      },
      day: { trades: 0, wins: 0, net_pct: 0, fees_usd: 0, halted: false },
      next_stop_pct: null,
      rsi: null,
      position: {
        side: 'SHORT',
        entry: 85000,
        opened_at: '2026-10-02T10:05:00+05:30',
        notional_usd: 85,
        margin_usd: 8.5,
        stop_pct: 0.9,
        stop_price: 85765,
        initial_stop_price: 85765,
        trailing: false,
        trail_arm_price: 84235,
        trail_gap_pct: 0.45,
        best_move_pct: 0.5,
        risk_usd: 0.765,
        fees_usd_round_trip: 0.1003,
        time_exit_at: '2026-10-02T18:05:00+05:30',
        live: 84575,
      },
    },
  ],
}

async function renderCrypto(positions: Position[], overview: RiskOverview | null = OVERVIEW) {
  mocks.getPositions.mockResolvedValue({ status: 'success', data: positions })
  mocks.getOverview.mockResolvedValue(overview)
  render(<Positions />)
  await screen.findAllByText(positions[0].symbol)
}

function rowFor(symbol: string) {
  const cell = screen.getAllByText(symbol).find((el) => el.closest('tbody'))
  return cell?.closest('tr') as HTMLElement
}

describe('Positions on a crypto broker', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    localStorage.setItem('openalgo_delta_position_currency_session', 'USD')
  })

  it('counts down every second without quote changes and recalculates net fees at expiry', async () => {
    vi.useFakeTimers()
    const now = Date.parse('2026-10-16T12:00:00Z')
    vi.setSystemTime(now)
    mocks.getPositions.mockResolvedValue({
      status: 'success',
      data: [
        {
          ...BTC_SHORT,
          opened_at: new Date(now - 30 * 60_000 + 2000).toISOString(),
        },
      ],
    })
    mocks.getOverview.mockResolvedValue(OVERVIEW)
    const view = render(<Positions />)
    try {
      await act(async () => {
        await Promise.resolve()
      })
      expect(within(rowFor('BTCUSDFUT')).getByText(/close free for 00:02/)).toBeInTheDocument()
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000)
      })
      expect(within(rowFor('BTCUSDFUT')).getByText(/close free for 00:01/)).toBeInTheDocument()
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000)
      })
      expect(within(rowFor('BTCUSDFUT')).queryByText(/close free for/)).not.toBeInTheDocument()
      expect(within(rowFor('BTCUSDFUT')).getByText('$0.32')).toBeInTheDocument()
      expect(screen.getByText('before fees $0.43').parentElement).toHaveTextContent('$0.32')
      expect(mocks.getPositions).toHaveBeenCalledTimes(1)
    } finally {
      view.unmount()
      vi.clearAllTimers()
      vi.useRealTimers()
    }
  })

  it('labels the risk columns', async () => {
    await renderCrypto([BTC_SHORT])
    for (const name of [
      'Leverage',
      'Stop Loss · USD',
      'Take Profit · USD',
      'Fees',
      'Net after fees',
    ]) {
      expect(screen.getByRole('columnheader', { name })).toBeInTheDocument()
    }
  })

  it("shows the strategy's stop, target, leverage and margin on its row", async () => {
    await renderCrypto([BTC_SHORT])
    await screen.findAllByText('$85,765.00')

    const row = within(rowFor('BTCUSDFUT'))
    expect(row.getByText('10x')).toBeInTheDocument()
    expect(row.getByText('margin $8.50')).toBeInTheDocument()
    expect(row.getByText('$85,765.00')).toBeInTheDocument()
    // Above entry on a short: the stop is a loss.
    expect(row.getByText('-0.90%')).toBeInTheDocument()
    expect(row.getByText('$84,235.00')).toBeInTheDocument()
  })

  it('charges the opening fee and a free close inside the Scalper Offer window', async () => {
    await renderCrypto([
      { ...BTC_SHORT, opened_at: new Date(Date.now() - 5 * 60_000).toISOString() },
    ])
    await screen.findAllByText('$85,765.00')

    // 1 contract x 0.001 BTC x 85,000 = $85 notional; 0.05% taker + 18% GST
    // = $0.05 to open, nothing to close within 30 minutes on BTCUSD.
    const row = within(rowFor('BTCUSDFUT'))
    expect(row.getByText(/close free for 2\d:[0-5]\d/)).toBeInTheDocument()
    expect(row.getByText(/est\. \$0\.05/)).toBeInTheDocument()
    // 0.425 P&L - 0.05015 opening fee.
    expect(row.getByText('$0.37')).toBeInTheDocument()
  })

  it('owes the closing fee once the Scalper Offer window has passed', async () => {
    await renderCrypto([
      { ...BTC_SHORT, opened_at: new Date(Date.now() - 45 * 60_000).toISOString() },
    ])
    await screen.findAllByText('$85,765.00')

    // Opening $0.05015 + closing at 84,575 ($0.0499) = $0.10.
    const row = within(rowFor('BTCUSDFUT'))
    expect(row.getByText('$0.10')).toBeInTheDocument()
    // 0.425 - 0.05015 - 0.04990 = 0.32495.
    expect(row.getByText('$0.32')).toBeInTheDocument()
  })

  it("uses the exchange's own fee and funding figures when it reports them", async () => {
    await renderCrypto([
      {
        ...BTC_SHORT,
        fees_paid: 0.06,
        funding: -0.02,
        opened_at: new Date(Date.now() - 5 * 60_000).toISOString(),
      },
    ])
    await screen.findAllByText('$85,765.00')

    const row = within(rowFor('BTCUSDFUT'))
    expect(row.getByText(/paid \$0\.06/)).toBeInTheDocument()
    expect(row.getByText('funding -$0.02')).toBeInTheDocument()
    // 0.425 - 0.06 paid - 0.02 funding = 0.345.
    expect(row.getByText('$0.35')).toBeInTheDocument()
  })

  it('headlines net P&L after fees for a crypto account', async () => {
    await renderCrypto([{ ...BTC_SHORT, fees_paid: 0.06 }])
    expect(await screen.findByText('before fees $0.43')).toBeInTheDocument()
    expect(screen.getByText('Net P&L')).toBeInTheDocument()
  })

  it('flags an open position no strategy is protecting', async () => {
    await renderCrypto([ETH_LONG])
    await screen.findByText('Fees per round trip')

    const row = within(rowFor('ETHUSDFUT'))
    expect(row.getAllByText('Not verified')).toHaveLength(2)
    expect(row.getByText('10x')).toBeInTheDocument()
  })

  it('shows the account leverage, liquidation distance and fee schedule', async () => {
    await renderCrypto([BTC_SHORT])
    await screen.findByText('Estimated liquidation distance')

    expect(screen.getByText('9.75%')).toBeInTheDocument()
    expect(screen.getAllByText('0.118%').length).toBeGreaterThan(0)
    expect(screen.getByText('Take profit (trailing)')).toBeInTheDocument()
    expect(screen.getByText('Break-even exit')).toBeInTheDocument()
  })

  it('still renders the table when the risk endpoint is unavailable', async () => {
    await renderCrypto([BTC_SHORT], null)

    const row = within(rowFor('BTCUSDFUT'))
    expect(row.getByText('Default')).toBeInTheDocument()
    expect(row.getAllByText('Not verified')).toHaveLength(2)
  })

  it('lists each strategy stop and target when two share the contract', async () => {
    const rsi = OVERVIEW.strategies[0]
    const emaTrade = {
      ...rsi,
      strategy: 'Delta BTC EMA 20/50 1h',
      strategy_id: 'delta_btc_ema_cross_1h_1',
      position: {
        ...(rsi.position as NonNullable<typeof rsi.position>),
        stop_price: 85510,
        trail_arm_price: 84490,
        trail_gap_pct: 0.3,
      },
    }
    await renderCrypto([{ ...BTC_SHORT, quantity: -2 } as Position], {
      ...OVERVIEW,
      strategies: [rsi, emaTrade],
    })
    await screen.findAllByText('$85,510.00')

    const row = within(rowFor('BTCUSDFUT'))
    expect(row.getByText('$85,765.00')).toBeInTheDocument()
    expect(row.getByText('$85,510.00')).toBeInTheDocument()
    expect(row.getByText(/RSI Fade 1h · -0.90%/)).toBeInTheDocument()
    expect(row.getByText(/EMA 20\/50 1h · -0.60%/)).toBeInTheDocument()
    expect(row.getByText('$84,490.00')).toBeInTheDocument()
  })

  it('does not attach a strategy trading another product to this row', async () => {
    await renderCrypto([{ ...BTC_SHORT, product: 'MIS' } as Position])
    await screen.findByText('Fees per round trip')

    const row = within(rowFor('BTCUSDFUT'))
    expect(row.getAllByText('Not verified')).toHaveLength(2)
  })

  it("shows what a flat strategy's entry rule is watching", async () => {
    const flatEma = {
      ...OVERVIEW.strategies[0],
      strategy: 'Delta BTC EMA 20/50 1h',
      position: null,
      rsi: null,
      indicator: 'EMA20 84,700 above EMA50 84,500',
    }
    await renderCrypto([BTC_SHORT], { ...OVERVIEW, strategies: [flatEma] })

    expect(await screen.findByText('Now: EMA20 84,700 above EMA50 84,500')).toBeInTheDocument()
  })

  it('shows a fixed target and a minute time limit for a 30-minute scalp', async () => {
    const rsi = OVERVIEW.strategies[0]
    const scalp = {
      ...rsi,
      strategy: 'Delta BTC 30m Scalp',
      strategy_id: 'delta_btc_30m_scalp_1',
      rules: { ...rsi.rules, max_hold_hours: 28 / 60 },
      position: {
        ...(rsi.position as NonNullable<typeof rsi.position>),
        stop_price: 85425,
        target_type: 'fixed' as const,
        target_price: 82450,
        trail_arm_price: 82450,
        trail_gap_pct: 0,
      },
    }
    await renderCrypto([BTC_SHORT], { ...OVERVIEW, strategies: [scalp] })
    await screen.findByText('Take profit (fixed)')

    expect(screen.getByText('28 min max')).toBeInTheDocument()
    expect(screen.queryByText('Trails behind best by')).not.toBeInTheDocument()
    const row = within(rowFor('BTCUSDFUT'))
    expect(row.getByText('$82,450.00')).toBeInTheDocument()
    expect(row.getByText('fixed target')).toBeInTheDocument()
  })
})

it('shows fresh broker leverage and native SL/TP instead of the app default', async () => {
  mocks.getOverview.mockResolvedValue({
    ...OVERVIEW,
    strategies: [],
    broker_positions: [
      {
        symbol: 'BTCUSDFUT',
        quantity: -1,
        entry: 85000,
        leverage: 5,
        stops: [85100],
        targets: [84700],
        checked_at: Date.now() / 1000,
      },
    ],
  })
  mocks.getPositions.mockResolvedValue({ status: 'success', data: [BTC_SHORT] })
  render(<Positions />)
  await screen.findByText('$85,100.00')
  const row = within(rowFor('BTCUSDFUT'))
  expect(row.getByText('5x')).toBeInTheDocument()
  expect(row.getByText('Broker SL')).toBeInTheDocument()
  expect(row.getByText('$84,700.00')).toBeInTheDocument()
  expect(row.getByText('Broker TP')).toBeInTheDocument()
})

it('keeps entry, LTP and break-even in USD while P&L follows INR/USD preference', async () => {
  localStorage.clear()
  mocks.getOverview.mockResolvedValue(OVERVIEW)
  mocks.getPositions.mockResolvedValue({ status: 'success', data: [BTC_SHORT] })
  const mounted = render(<Positions />)
  await screen.findByText('before fees ₹36.13')
  const select = screen.getByRole('combobox', { name: 'Position display currency' })
  expect(select).toHaveValue('INR')
  expect(within(rowFor('BTCUSDFUT')).getByText(/^b\/e \$/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Delta India: US$1 = ₹85 (fixed)' })).toBeInTheDocument()
  expect(within(rowFor('BTCUSDFUT')).getByText('$85,000.00')).toBeInTheDocument()
  expect(within(rowFor('BTCUSDFUT')).getByText('$85,765.00')).toBeInTheDocument()
  fireEvent.change(select, { target: { value: 'USD' } })
  expect(screen.getByText('before fees $0.43')).toBeInTheDocument()
  expect(localStorage.getItem('openalgo_delta_position_currency_session')).toBe('USD')
  mounted.unmount()
  render(<Positions />)
  expect(screen.getByRole('combobox', { name: 'Position display currency' })).toHaveValue('USD')
})
