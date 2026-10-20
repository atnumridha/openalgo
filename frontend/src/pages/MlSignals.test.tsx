/* @vitest-environment happy-dom */

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MlSignals from './MlSignals'

const apiMocks = vi.hoisted(() => ({
  coverage: vi.fn(),
  sentiment: vi.fn(),
  live: vi.fn(),
  models: vi.fn(),
  status: vi.fn(),
  refresh: vi.fn(),
  labels: vi.fn(),
  search: vi.fn(),
  train: vi.fn(),
  activate: vi.fn(),
  suggestions: vi.fn(),
  trades: vi.fn(),
  trade: vi.fn(),
  closeTrade: vi.fn(),
  settings: vi.fn(),
  saveSettings: vi.fn(),
  retrain: vi.fn(),
}))

vi.mock('@/api/mlSignals', () => ({
  mlSignalsApi: apiMocks,
}))

vi.mock('@/utils/toast', () => ({
  showToast: { success: vi.fn(), error: vi.fn() },
}))

function liveSnapshot(action: 'LONG' | 'SHORT' | 'WAIT', pLong = 0.2, pShort = 0.3) {
  const now = Date.now() / 1000
  return {
    state: 'live',
    interval: '5m',
    feed: 'Live.',
    server_time: now,
    computed_at: now,
    price: 84540.5,
    price_time: now - 10,
    model_version: 'unit',
    model_promoted: false,
    promotion_reason: 'Lost 1.20% of notional after fees over 40 trades on the unseen period.',
    forming: {
      time: Math.floor(now / 300) * 300,
      p_long: pLong,
      p_short: pShort,
      p_wait: 1 - pLong - pShort,
      action,
      ev_long_pct: 0.01,
      ev_short_pct: -0.02,
      min_edge_pct: 0.05,
      closes_at: Math.floor(now / 300) * 300 + 300,
    },
    closed: { time: Math.floor(now / 300) * 300 - 300, action: 'WAIT', p_long: 0.2, p_short: 0.2 },
    sentiment: { interval: '5m', score: 0.12, sources_used: 8, drivers: { fear_greed: 67 } },
    sources: {
      delta_btcusd: {
        label: 'Delta traded price',
        status: 'ok',
        age_seconds: 0.4,
        newest_time: now - 10,
        message: null,
      },
    },
    message: null,
  }
}

function suggestion(overrides: Record<string, unknown> = {}) {
  const now = Date.now() / 1000
  return {
    symbol: 'BTCUSD',
    openalgo_symbol: 'BTCUSDFUT',
    interval: '5m',
    mode: 'sandbox',
    action: 'LONG',
    price: 60000,
    snapshot_age_seconds: 0.5,
    model_version: 'unit',
    model_promoted: false,
    promotion_reason: 'Lost 1.20% of notional after fees over 40 trades on the unseen period.',
    p_long: 0.6,
    p_short: 0.1,
    p_wait: 0.3,
    ev_pct: 0.2,
    min_edge_pct: 0.05,
    stop_pct: 0.15,
    target_pct: 0.4,
    hold_minutes: 28,
    signal_time: now - 300,
    expires_at: now + 300,
    message: null,
    entry_price: 60000,
    stop_price: 59910,
    target_price: 60240,
    balance: 1000,
    balance_source: 'sandbox setting',
    contract_value: 0.001,
    sizing: {
      ok: true,
      contracts: 64,
      notional: 3840,
      margin: 384,
      leverage: 10,
      risk_amount: 9.9,
      risk_budget: 10,
      entry_fee: 2.27,
      exit_fee_in_window: 0,
      exit_fee_after_window: 2.26,
      voucher_if_in_window: 1.92,
      loss_at_stop: 9.9,
      profit_at_target: 13.09,
      reward_risk_after_fees: 1.32,
      capped_by_leverage: false,
      reason: null,
    },
    tradable: true,
    ...overrides,
  }
}

describe('MlSignals', () => {
  beforeEach(() => {
    localStorage.setItem('openalgo_delta_position_currency_session', 'USD')
    vi.clearAllMocks()
    apiMocks.coverage.mockResolvedValue({ sources: {} })
    apiMocks.models.mockResolvedValue({ models: [] })
    apiMocks.status.mockResolvedValue({ busy: false, job: null, progress: 0, message: 'idle' })
    apiMocks.live.mockResolvedValue(liveSnapshot('WAIT'))
    apiMocks.suggestions.mockResolvedValue([suggestion()])
    apiMocks.trades.mockResolvedValue({ open: [], closed: [] })
    apiMocks.settings.mockResolvedValue(null)
    apiMocks.trade.mockResolvedValue({
      status: 'success',
      message: 'LONG 64 BTCUSD contracts sent',
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads the live signal, suggestions and open trades', async () => {
    render(<MlSignals />)

    expect(screen.getByRole('heading', { name: 'ML Signals' })).toBeInTheDocument()
    expect(screen.getByText('Not trained')).toBeInTheDocument()
    await waitFor(() => {
      expect(apiMocks.live).toHaveBeenCalledWith('5m', 'BTCUSD')
      expect(apiMocks.suggestions).toHaveBeenCalledWith('5m', 'sandbox')
      expect(apiMocks.trades).toHaveBeenCalled()
    })
    const card = await screen.findByTestId('suggestion-BTCUSD')
    expect(within(card).getByText('$59,910.00')).toBeInTheDocument()
    expect(within(card).getByText('64')).toBeInTheDocument()
    expect(within(card).getByText('$1.92')).toBeInTheDocument()
    expect(apiMocks.sentiment).not.toHaveBeenCalled()
  })

  it('polls the live signal every second and shows the new action', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<MlSignals />)
    await waitFor(() => expect(screen.getByTestId('live-action')).toHaveTextContent('WAIT'))

    apiMocks.live.mockResolvedValue(liveSnapshot('LONG', 0.71, 0.1))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100)
    })
    await waitFor(() => expect(screen.getByTestId('live-action')).toHaveTextContent('LONG'))
    expect(apiMocks.live.mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(apiMocks.coverage).toHaveBeenCalledTimes(1)
    expect(apiMocks.models).toHaveBeenCalledTimes(1)
  })

  it('opens a Sandbox trade only after the confirmation', async () => {
    render(<MlSignals />)
    const button = await screen.findByTestId('trade-BTCUSD')
    expect(button).toHaveTextContent('Buy 64 in Sandbox')
    fireEvent.click(button)
    expect(apiMocks.trade).not.toHaveBeenCalled()
    fireEvent.click(await screen.findByRole('button', { name: /Start trade/ }))
    await waitFor(() =>
      expect(apiMocks.trade).toHaveBeenCalledWith({
        symbol: 'BTCUSD',
        interval: '5m',
        mode: 'sandbox',
        action: 'LONG',
        contracts: 64,
      })
    )
  })

  it('locks Live with the reason until the model is promoted', async () => {
    apiMocks.suggestions.mockResolvedValue([suggestion({ mode: 'live' })])
    render(<MlSignals />)
    fireEvent.click(await screen.findByRole('combobox', { name: 'Trading mode' }))
    fireEvent.click(await screen.findByRole('option', { name: 'Live' }))
    await waitFor(() => expect(apiMocks.suggestions).toHaveBeenCalledWith('5m', 'live'))
    const button = await screen.findByTestId('trade-BTCUSD')
    await waitFor(() => expect(button).toHaveTextContent('Live locked'))
    expect(button).toBeDisabled()
    const card = screen.getByTestId('suggestion-BTCUSD')
    expect(within(card).getAllByText(/Lost 1.20% of notional/).length).toBeGreaterThan(0)
  })

  it('shows open trades with net P&L after fees and the voucher beside it', async () => {
    apiMocks.trades.mockResolvedValue({
      open: [
        {
          key: '7:1',
          strategy_id: 1,
          run_id: 7,
          leg_id: 1,
          mode: 'sandbox',
          symbol: 'BTCUSD',
          side: 'LONG',
          entry_status: 'complete',
          contracts: 64,
          entry_price: 60000,
          last_price: 60060,
          stop_price: 59910,
          target_price: 60240,
          trail_active: false,
          gross_pnl: 3.84,
          fees_paid: 2.27,
          exit_fee_now: 0,
          exit_fee_after_window: 2.27,
          window_remaining_minutes: 22,
          voucher_now: 1.92,
          net_pnl: 1.57,
          pnl_pct: 0.1,
          held_minutes: 8,
          interval: '5m',
          exit_kind: null,
        },
      ],
      closed: [],
    })
    render(<MlSignals />)
    await waitFor(() => expect(screen.getByTestId('ml-open-net')).toHaveTextContent('$1.57 net'))
    const row = screen.getByTestId('ml-trade-7:1')
    expect(within(row).getByText('close free for 22m')).toBeInTheDocument()
    expect(within(row).getByText('voucher $1.92')).toBeInTheDocument()
  })
})
