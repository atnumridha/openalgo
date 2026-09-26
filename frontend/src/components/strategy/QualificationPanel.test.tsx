import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const rest = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/client', () => ({ webClient: rest }))

import type { ResearchRun } from '@/types/trading-research'
import QualificationPanel from './QualificationPanel'

const policy = {
  version: 'forward-v1',
  min_final_trades: 20,
  min_sessions: 30,
  min_closed_trades: 100,
  min_profit_factor: 1.2,
  max_drawdown_pct: 15,
  approval_days: 7,
  max_quote_age_seconds: 5,
  max_fill_delay_seconds: 30,
}
const costs = {
  schedule_id: 'Reviewed fees',
  source: 'Dated broker schedule',
  effective_from: '2026-01-01',
  effective_to: '2026-12-31',
  brokerage_per_order: 20,
  exchange_rate: 0.0001,
  sebi_rate: 0.000001,
  gst_rate: 0.18,
  stamp_buy_rate: 0.00003,
  stt_sell_rate: 0.001,
  slippage_bps: 10,
}
const finalRun = {
  id: 12,
  kind: 'final',
  status: 'completed',
  candidate: 'trend_breakout',
  configuration_hash: 'historical-config',
} as ResearchRun
const campaign = () => ({
  id: 4,
  strategy_id: 7,
  final_run_id: 12,
  created_at: '2026-09-26T10:00:00Z',
  binding_hash: 'bound-strategy-flow',
  revision: 2,
  evidence_digest: 'evidence-one',
  status: 'collecting',
  binding: {
    broker: 'testbroker',
    broker_connection_id: 'account-1',
    costs,
    strategy_hash: 'strategy-fingerprint',
    workflow_hash: 'flow-fingerprint',
    source_hash: 'source-fingerprint',
    risk_policy_version: 'two-bucket-v1',
  },
  qualification: {
    eligible: false,
    checks: [
      {
        code: 'sessions',
        passed: false,
        message: 'At least 30 forward sessions required.',
        actual: 2,
        required: 30,
      },
      {
        code: 'closed_trades',
        passed: false,
        message: 'At least 100 closed trades required.',
        actual: 5,
        required: 100,
      },
      {
        code: 'execution_evidence',
        passed: false,
        message: 'Missing executable quote for trade 8.',
        actual: 1,
        required: 0,
      },
    ],
    metrics: {
      session_count: 2,
      closed_trade_count: 5,
      net_pnl: 0,
      expectancy: null,
      profit_factor: null,
      profit_factor_unbounded: false,
      stressed_net_pnl: null,
      max_drawdown_pct: 1,
      unresolved_count: 1,
      invalid_count: 1,
      risk_breach: false,
    },
  },
  reconciliation: null,
  approval: null,
  trades: [
    {
      trade_ref: 'trade-8',
      registered_at: '2026-09-26T10:00:00Z',
      session_day: '2026-09-26',
      status: 'partial',
      net_pnl: null,
      stressed_net_pnl: null,
      valid: false,
      issues: ['Missing executable quote'],
      orders_count: 2,
    },
  ],
})
const qualified = () => ({
  ...campaign(),
  status: 'eligible',
  qualification: {
    eligible: true,
    checks: [
      {
        code: 'sessions',
        passed: true,
        message: 'Forward session requirement met.',
        actual: 30,
        required: 30,
      },
    ],
    metrics: {
      ...campaign().qualification.metrics,
      session_count: 30,
      closed_trade_count: 100,
      net_pnl: 1200,
      expectancy: 12,
      profit_factor: 1.3,
      stressed_net_pnl: 700,
      unresolved_count: 0,
      invalid_count: 0,
    },
  },
})
const reconciled = () => ({
  ...qualified(),
  reconciliation: {
    status: 'current',
    at: '2026-09-26T12:00:00Z',
    reason: 'All fills reviewed',
    costs_confirmed: true,
    revision: 2,
    evidence_digest: 'evidence-one',
  },
})
const approved = () => ({
  ...reconciled(),
  approval: {
    status: 'approved',
    at: '2026-09-26T12:00:00Z',
    expires_at: '2099-09-30T12:00:00Z',
    reason: 'Ready for a reviewed release',
  },
})
let current:
  | ReturnType<typeof campaign>
  | ReturnType<typeof reconciled>
  | ReturnType<typeof approved>
let campaigns: unknown[]

function renderPanel(runs: ResearchRun[] = [finalRun]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <QualificationPanel runs={runs} />
    </QueryClientProvider>
  )
}

beforeEach(() => {
  current = campaign()
  campaigns = [current]
  rest.get.mockReset()
  rest.post.mockReset()
  rest.get.mockImplementation((url: string) =>
    Promise.resolve({
      data: {
        status: 'success',
        data:
          url === '/strategy/api/qualification'
            ? { campaigns, strategies: [{ id: 7, name: 'Bound breakout flow' }], policy }
            : current,
      },
    })
  )
})

describe('Forward qualification', () => {
  it('shows prospective progress, missing evidence, and unavailable metrics without treating them as zero', async () => {
    renderPanel()
    const detail = await screen.findByRole('region', { name: 'Campaign evidence' })
    expect(detail).toHaveTextContent('2 / 30')
    expect(detail).toHaveTextContent('5 / 100')
    expect(detail).toHaveTextContent('Missing executable quote for trade 8.')
    expect(within(detail).getByText('Net P&L', { selector: 'dt' }).parentElement).toHaveTextContent(
      '₹0.00'
    )
    expect(
      within(detail).getByText('Profit factor', { selector: 'dt' }).parentElement
    ).toHaveTextContent('Unavailable')
    expect(detail).toHaveTextContent('Historical research reference: run #12')
    expect(detail).toHaveTextContent('Bound breakout flow')
    expect(screen.getByRole('button', { name: 'Approve live release' })).toBeDisabled()
    expect(rest.post).not.toHaveBeenCalled()
    await userEvent.click(screen.getByText('Forward trade evidence (1)'))
    expect(screen.getByRole('table', { name: 'Forward trade evidence' })).toHaveTextContent(
      'partial'
    )
    expect(screen.getByRole('table', { name: 'Forward trade evidence' })).toHaveTextContent(
      'Missing executable quote'
    )
    const scrollingEvidence = screen.getByRole('region', {
      name: 'Scrollable forward trade evidence',
    })
    scrollingEvidence.focus()
    expect(scrollingEvidence).toHaveFocus()
  })

  it('enrolls only the selected deployed strategy and completed final reference without starting trading', async () => {
    campaigns = []
    rest.post.mockImplementation(() => {
      campaigns = [current]
      return Promise.resolve({ data: { status: 'success', data: current } })
    })
    renderPanel([
      finalRun,
      { ...finalRun, id: 10, kind: 'development' },
      { ...finalRun, id: 11, status: 'running' },
    ])
    expect(await screen.findByText(/No forward campaigns yet/)).toBeVisible()
    expect(screen.queryByRole('option', { name: /Run #10/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Run #11/ })).not.toBeInTheDocument()
    const enroll = screen.getByRole('button', { name: 'Enroll Sandbox campaign' })
    expect(enroll).toBeDisabled()
    await userEvent.selectOptions(screen.getByLabelText('Deployed strategy'), '7')
    await userEvent.selectOptions(screen.getByLabelText('Final research reference'), '12')
    await userEvent.click(enroll)
    await waitFor(() =>
      expect(rest.post).toHaveBeenCalledWith('/strategy/api/qualification/campaigns', {
        strategy_id: 7,
        final_run_id: 12,
      })
    )
    expect(
      await screen.findByRole('status', { name: 'Qualification action result' })
    ).toHaveTextContent('does not start trading')
    expect(rest.post).toHaveBeenCalledTimes(1)
  })

  it('requires a fee review and explicit acknowledgment before approving the current evidence', async () => {
    current = qualified()
    rest.post.mockImplementation((url: string) => {
      current = url.endsWith('/reconcile') ? reconciled() : approved()
      return Promise.resolve({ data: { status: 'success', data: current } })
    })
    renderPanel()
    await screen.findByRole('region', { name: 'Campaign evidence' })
    const reconcile = screen.getByRole('button', { name: 'Record reconciliation' })
    const approve = screen.getByRole('button', { name: 'Approve live release' })
    expect(reconcile).toBeDisabled()
    expect(approve).toBeDisabled()
    await userEvent.click(screen.getByText('Bound configuration and cost assumptions'))
    expect(screen.getByRole('region', { name: 'Bound configuration' })).toHaveTextContent(
      'Reviewed fees'
    )
    expect(screen.getByRole('region', { name: 'Bound configuration' })).toHaveTextContent(
      '2026-12-31'
    )
    await userEvent.type(screen.getByLabelText('Reconciliation reason'), 'All fills reviewed')
    expect(reconcile).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: /reviewed the forward fills/ }))
    await userEvent.click(reconcile)
    await waitFor(() =>
      expect(rest.post).toHaveBeenCalledWith('/strategy/api/qualification/campaigns/4/reconcile', {
        reason: 'All fills reviewed',
        costs_confirmed: true,
        expected_revision: 2,
        evidence_digest: 'evidence-one',
      })
    )
    await waitFor(() => expect(screen.getByText('Reconciliation current')).toBeVisible())
    await userEvent.type(
      screen.getByLabelText('Release review reason'),
      'Ready for a reviewed release'
    )
    expect(screen.getByRole('button', { name: 'Approve live release' })).toBeDisabled()
    await userEvent.click(
      screen.getByRole('checkbox', { name: /Daily live-session authorization/ })
    )
    await userEvent.click(screen.getByRole('button', { name: 'Approve live release' }))
    await waitFor(() =>
      expect(rest.post).toHaveBeenCalledWith('/strategy/api/qualification/campaigns/4/approve', {
        reason: 'Ready for a reviewed release',
        acknowledged: true,
        expected_revision: 2,
        evidence_digest: 'evidence-one',
      })
    )
    expect(await screen.findByText('Release approved')).toBeVisible()
    expect(screen.getByText(/2099/)).toBeVisible()
    expect(rest.post).toHaveBeenCalledTimes(2)
  })

  it('revokes an approval with a recorded reason', async () => {
    current = approved()
    rest.post.mockImplementation(() => {
      current = {
        ...approved(),
        approval: { ...approved().approval, status: 'revoked', reason: 'Pause for review' },
      }
      return Promise.resolve({ data: { status: 'success', data: current } })
    })
    renderPanel()
    await screen.findByText('Release approved')
    const revoke = screen.getByRole('button', { name: 'Revoke live release' })
    expect(revoke).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Revocation reason'), 'Pause for review')
    await userEvent.click(revoke)
    await waitFor(() =>
      expect(rest.post).toHaveBeenCalledWith('/strategy/api/qualification/campaigns/4/revoke', {
        reason: 'Pause for review',
      })
    )
    expect(await screen.findByText('Release revoked')).toBeVisible()
  })

  it.each([
    'expired',
    'invalidated',
    'revoked',
  ])('does not present %s approval as permission to enter live', async (status) => {
    current = {
      ...approved(),
      qualification: campaign().qualification,
      reconciliation: { ...reconciled().reconciliation, status: 'stale' },
      approval: { ...approved().approval, status },
    }
    renderPanel()
    expect(await screen.findByText(`Release ${status}`)).toBeVisible()
    expect(screen.getByText('Reconciliation stale')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Approve live release' })).toBeDisabled()
    expect(screen.queryByText('Release approved')).not.toBeInTheDocument()
  })

  it('expires approval locally when the server response carries a past expiry', async () => {
    current = {
      ...approved(),
      approval: { ...approved().approval, expires_at: '2020-01-01T00:00:00Z' },
    }
    renderPanel()
    expect(await screen.findByText('Release expired')).toBeVisible()
    expect(screen.queryByText('Release approved')).not.toBeInTheDocument()
  })

  it('explains the actual binding and approval invalidation causes', async () => {
    current = {
      ...approved(),
      binding_problem: 'The linked Flow changed. Enroll a new campaign.',
      approval: {
        ...approved().approval,
        status: 'invalidated',
        invalidation_reason: 'The broker authorization changed.',
      },
    }
    renderPanel()
    await screen.findByText('Release invalidated')
    expect(screen.getByText('The linked Flow changed. Enroll a new campaign.')).toBeVisible()
    expect(screen.getByText('The broker authorization changed.')).toBeVisible()
  })

  it('surfaces a server refusal without claiming approval succeeded', async () => {
    current = reconciled()
    rest.post.mockResolvedValue({
      data: { status: 'error', message: 'Evidence changed; reconcile again.' },
    })
    renderPanel()
    await screen.findByText('Reconciliation current')
    await userEvent.type(screen.getByLabelText('Release review reason'), 'Reviewed for live')
    await userEvent.click(
      screen.getByRole('checkbox', { name: /Daily live-session authorization/ })
    )
    await userEvent.click(screen.getByRole('button', { name: 'Approve live release' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Evidence changed; reconcile again.')
    expect(screen.queryByText('Release approved')).not.toBeInTheDocument()
  })

  it('keeps unavailable service evidence distinct from an empty campaign history', async () => {
    rest.get.mockRejectedValue(new Error('Qualification storage unavailable'))
    renderPanel([])
    expect(await screen.findByRole('alert')).toHaveTextContent('Qualification storage unavailable')
    expect(screen.queryByText(/No forward campaigns yet/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Enroll Sandbox campaign' })).toBeDisabled()
  })

  it('clears the approval acknowledgment after a server rejection requires a fresh review', async () => {
    current = reconciled()
    rest.post.mockRejectedValue(new Error('Evidence changed; reconcile again.'))
    renderPanel()
    await screen.findByText('Reconciliation current')
    await userEvent.type(screen.getByLabelText('Release review reason'), 'Reviewed for live')
    await userEvent.click(
      screen.getByRole('checkbox', { name: /Daily live-session authorization/ })
    )
    await userEvent.click(screen.getByRole('button', { name: 'Approve live release' }))
    await screen.findByRole('alert')
    expect(
      screen.getByRole('checkbox', { name: /Daily live-session authorization/ })
    ).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Approve live release' })).toBeDisabled()
  })

  it.each([400, 409])('refreshes stale evidence after an approval refusal (%s)', async (status) => {
    current = reconciled()
    rest.post.mockImplementation(() => {
      current = {
        ...reconciled(),
        revision: 3,
        evidence_digest: 'evidence-two',
        reconciliation: { ...reconciled().reconciliation, status: 'stale' },
      }
      return Promise.reject(
        Object.assign(new Error('Displayed evidence changed.'), { response: { status } })
      )
    })
    renderPanel()
    await screen.findByText('Reconciliation current')
    await userEvent.type(
      screen.getByLabelText('Release review reason'),
      'Reviewed displayed evidence'
    )
    await userEvent.click(
      screen.getByRole('checkbox', { name: /Daily live-session authorization/ })
    )
    await userEvent.click(screen.getByRole('button', { name: 'Approve live release' }))
    expect(await screen.findByText('Reconciliation stale')).toBeVisible()
    expect(screen.getByLabelText('Release review reason')).toHaveValue('')
    expect(
      screen.getByRole('checkbox', { name: /Daily live-session authorization/ })
    ).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Approve live release' })).toBeDisabled()
    expect(rest.post).toHaveBeenCalledWith('/strategy/api/qualification/campaigns/4/approve', {
      reason: 'Reviewed displayed evidence',
      acknowledged: true,
      expected_revision: 2,
      evidence_digest: 'evidence-one',
    })
  })

  it('clears review inputs when refreshed evidence changes revision', async () => {
    current = reconciled()
    renderPanel()
    await screen.findByText('Reconciliation current')
    await userEvent.type(screen.getByLabelText('Release review reason'), 'Reviewed for live')
    await userEvent.click(
      screen.getByRole('checkbox', { name: /Daily live-session authorization/ })
    )
    current = {
      ...reconciled(),
      revision: 3,
      evidence_digest: 'new-fill',
      reconciliation: { ...reconciled().reconciliation, status: 'stale' },
    }
    await userEvent.click(screen.getByRole('button', { name: 'Refresh qualification' }))
    await screen.findByText('Reconciliation stale')
    expect(screen.getByLabelText('Release review reason')).toHaveValue('')
    expect(
      screen.getByRole('checkbox', { name: /Daily live-session authorization/ })
    ).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Approve live release' })).toBeDisabled()
  })

  it('fails closed if refreshing a previously approved campaign becomes unavailable', async () => {
    current = approved()
    renderPanel()
    await screen.findByText('Release approved')
    rest.get.mockImplementation((url: string) =>
      url.endsWith('/campaigns/4')
        ? Promise.reject(new Error('Evidence store unreachable'))
        : Promise.resolve({
            data: {
              status: 'success',
              data: {
                campaigns: [current],
                strategies: [{ id: 7, name: 'Bound breakout flow' }],
                policy,
              },
            },
          })
    )
    await userEvent.click(screen.getByRole('button', { name: 'Refresh qualification' }))
    await screen.findByRole('alert')
    expect(screen.getByText('Release status unavailable')).toBeVisible()
    expect(screen.queryByText('Release approved')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve live release' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Record reconciliation' })).toBeDisabled()
  })
})
