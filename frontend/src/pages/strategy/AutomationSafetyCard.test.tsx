import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const strategyApi = vi.hoisted(() => ({
  getLiveAuthorization: vi.fn(),
  grantLiveAuthorization: vi.fn(),
  revokeLiveAuthorization: vi.fn(),
  installStarterPack: vi.fn(),
  strategyQueryKeys: {
    strategies: vi.fn(() => ['strategy-module', 'strategies']),
    liveAuthorization: vi.fn(() => ['strategy-module', 'automation', 'live-authorization']),
  },
}))

vi.mock('@/api/strategy_module', () => strategyApi)

import AutomationSafetyCard from './AutomationSafetyCard'

const inactiveAuthorization = {
  active: false,
  session_day: '2026-09-23',
  expires_at: '2026-09-23T15:30:00+05:30',
}

const activeAuthorization = {
  active: true,
  session_day: '2026-09-23',
  expires_at: '2026-09-23T15:30:00+05:30',
}

const createdStrategy = {
  id: 21,
  name: 'NIFTY 5/15-minute trend signal receiver',
  strategy_kind: 'signal',
  direction: 'both',
  universe_tab: 'weekly_monthly',
  underlying: 'NIFTY',
  underlying_exchange: 'NSE_INDEX',
  strategy_type: 'intraday',
  entry_time: null,
  exit_time: null,
  product: 'NRML',
  pricetype: 'MARKET',
  overall_sl_mtm: null,
  overall_target_mtm: null,
  lock_profit: null,
  trail_sl_to_entry: false,
  scheduler: null,
  live_enabled: false,
  webhook_locked: false,
  webhook_ip_allowlist: null,
  daily_loss_limit_inr: null,
  status: 'stopped',
  current_run_id: null,
  created_at: '2026-09-23T09:00:00+05:30',
  updated_at: '2026-09-23T09:00:00+05:30',
}

function renderCard(queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AutomationSafetyCard />
        </MemoryRouter>
      </QueryClientProvider>
    ),
  }
}

beforeEach(() => {
  strategyApi.getLiveAuthorization.mockReset()
  strategyApi.grantLiveAuthorization.mockReset()
  strategyApi.revokeLiveAuthorization.mockReset()
  strategyApi.installStarterPack.mockReset()
  strategyApi.getLiveAuthorization.mockResolvedValue(inactiveAuthorization)
})

describe('AutomationSafetyCard', () => {
  it('shows inactive authorization, independent live gates, policy limits, and safe next steps', async () => {
    renderCard()

    expect(await screen.findByText('Live automation authorization is inactive')).toBeInTheDocument()
    expect(screen.getByText('Expires: 23 Sep 2026, 15:30 IST')).toBeInTheDocument()
    expect(screen.getByText('Installing does not start trading.')).toBeInTheDocument()
    expect(screen.getByText('Each strategy must also be individually live-enabled.')).toBeInTheDocument()
    expect(screen.getByText('Maximum two simultaneous cash positions')).toBeInTheDocument()
    expect(
      screen.getByText('4% daily module loss or three stopped runs blocks new entries')
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open Agent' })).toHaveAttribute('href', '/agent')
    expect(screen.getByRole('link', { name: 'Review Flows' })).toHaveAttribute('href', '/flow')
  })

  it('renders active authorization and requires confirmation before granting a session', async () => {
    strategyApi.getLiveAuthorization.mockResolvedValue(activeAuthorization)
    const user = userEvent.setup()
    renderCard()

    expect(await screen.findByText('Live automation authorized for this session')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revoke authorization' })).toBeInTheDocument()

    // A future inactive refresh makes the grant path available; confirmation must still gate it.
    strategyApi.getLiveAuthorization.mockResolvedValue(inactiveAuthorization)
    await user.click(screen.getByRole('button', { name: 'Refresh status' }))
    expect(await screen.findByRole('button', { name: 'Authorize live automation' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Authorize live automation' }))

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Authorize live automation for this session?')).toBeInTheDocument()
    expect(strategyApi.grantLiveAuthorization).not.toHaveBeenCalled()

    strategyApi.grantLiveAuthorization.mockResolvedValue(activeAuthorization)
    await user.click(within(dialog).getByRole('button', { name: 'Authorize for this session' }))

    await waitFor(() => {
      expect(screen.getByText('Live automation authorized for this session')).toBeInTheDocument()
    })
    expect(strategyApi.grantLiveAuthorization).toHaveBeenCalledTimes(1)
  })

  it('requires confirmation before revoking and announces the inactive result', async () => {
    strategyApi.getLiveAuthorization.mockResolvedValue(activeAuthorization)
    strategyApi.revokeLiveAuthorization.mockResolvedValue(inactiveAuthorization)
    const user = userEvent.setup()
    renderCard()

    await screen.findByText('Live automation authorized for this session')
    await user.click(screen.getByRole('button', { name: 'Revoke authorization' }))

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Revoke live automation authorization?')).toBeInTheDocument()
    expect(within(dialog).getByText(/Existing exits, stops, and protective behavior remain allowed/)).toBeInTheDocument()
    expect(strategyApi.revokeLiveAuthorization).not.toHaveBeenCalled()

    await user.click(within(dialog).getByRole('button', { name: 'Revoke authorization' }))
    await waitFor(() => {
      expect(screen.getByText('Live automation authorization is inactive')).toBeInTheDocument()
    })
    expect(screen.getByRole('status')).toHaveTextContent('Live authorization revoked.')
  })

  it('reviews the starter pack before installation, shows created and existing strategies, and refreshes saved strategies', async () => {
    strategyApi.installStarterPack.mockResolvedValue({
      created: [createdStrategy],
      existing: [{ ...createdStrategy, id: 22, name: 'NIFTY breakout-and-retest signal receiver' }],
      webhook_tokens: { [createdStrategy.name]: 'copy-once-token' },
    })
    const user = userEvent.setup()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    renderCard(queryClient)

    await screen.findByText('Live automation authorization is inactive')
    await user.click(screen.getByRole('button', { name: 'Install recommended starter pack' }))

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Review recommended starter pack')).toBeInTheDocument()
    expect(within(dialog).getByText('Every installed strategy is stopped, sandbox-only, live-disabled, and unscheduled.')).toBeInTheDocument()
    expect(within(dialog).getByText('Installing does not start trading.')).toBeInTheDocument()
    expect(strategyApi.installStarterPack).not.toHaveBeenCalled()

    await user.click(within(dialog).getByRole('button', { name: 'Install sandbox starter pack' }))

    expect(await screen.findByRole('link', { name: createdStrategy.name })).toHaveAttribute(
      'href',
      '/strategy/21'
    )
    expect(screen.getByRole('link', { name: 'NIFTY breakout-and-retest signal receiver' })).toHaveAttribute(
      'href',
      '/strategy/22'
    )
    expect(screen.getByText('copy-once-token')).toBeInTheDocument()
    expect(strategyApi.installStarterPack).toHaveBeenCalledTimes(1)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['strategy-module', 'strategies'] })
  })

  it('announces API errors without masking the current authorization state', async () => {
    strategyApi.grantLiveAuthorization.mockRejectedValue(new Error('Broker session must be reconnected'))
    const user = userEvent.setup()
    renderCard()

    await screen.findByText('Live automation authorization is inactive')
    await user.click(screen.getByRole('button', { name: 'Authorize live automation' }))
    await user.click(screen.getByRole('button', { name: 'Authorize for this session' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Broker session must be reconnected'
    )
    expect(screen.getByText('Live automation authorization is inactive')).toBeInTheDocument()
  })
})
