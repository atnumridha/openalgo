import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ overview: vi.fn(), logs: vi.fn(), stop: vi.fn(), one: vi.fn() }))
vi.mock('@/api/automation_monitor', () => ({
  getAutomationMonitor: api.overview,
  getAutomationLogs: api.logs,
  emergencyStopAutomation: api.stop,
}))
vi.mock('@/api/strategy_module', () => ({ disableStrategyAutomation: api.one }))

import Monitor from './Monitor'

const strategy = {
  id: 13,
  name: 'NIFTY EMA 9/15',
  mode: 'sandbox',
  automation_state: 'armed',
  run_status: 'stopped',
  monitor_status: 'watching',
  reason: 'Waiting for a fresh qualifying signal',
  last_check_at: new Date().toISOString(),
  next_check_at: new Date(Date.now() + 60000).toISOString(),
  check_age_seconds: 10,
  interval_seconds: 60,
  workflow_id: 13,
  workflow_active: true,
  open_run_count: 0,
  open_runs: [],
  live_enabled: false,
  entry_time: '09:35',
  exit_time: '15:20',
  configuration: { profile: 'ema915' },
  rules: ['Both EMA slopes must meet 0.10 ATR'],
  evaluation: {
    recorded_at: new Date().toISOString(),
    stage: 'waiting',
    reason: 'No setup',
    technical: {
      metrics: { ema9: 25001 },
      checks: [{ side: 'CE', label: 'Trend slope', passed: false }],
      data_ready: true,
      direction: '',
      bar_at: new Date().toISOString(),
    },
    history: [],
  },
}
function setup(data = strategy) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  api.overview.mockResolvedValue({
    server_time: new Date().toISOString(),
    scheduler: { status: 'running' },
    live_authorization: { active: false },
    strategies: [data],
    risk: { sandbox: { available: false } },
  })
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Monitor />
        </MemoryRouter>
      </QueryClientProvider>
    ),
  }
}
beforeEach(() => {
  vi.clearAllMocks()
  api.logs.mockResolvedValue({ items: [], next_cursor: null })
  api.stop.mockResolvedValue({
    all_stopped: false,
    items: [
      {
        strategy_id: 13,
        name: strategy.name,
        state: 'closing',
        close_pending: true,
        ok: true,
        reason: null,
      },
    ],
  })
})
describe('Automation review', () => {
  it('shows all live blockers together even outside entry hours', async () => {
    setup({
      ...strategy,
      mode: 'live',
      live_enabled: true,
      monitor_status: 'live_blocked',
      reason: 'Live entry has 2 setup blockers.',
      activity_reason: 'Entry window ended at 15:20 IST.',
      live_readiness: {
        blocked: true,
        blocker_count: 2,
        checks: [
          {
            code: 'session_approval',
            label: 'Trading-session approval',
            status: 'blocked',
            message: 'Approve the current session.',
          },
          {
            code: 'research_release',
            label: 'Research requirement',
            status: 'blocked',
            message: 'No approved forward release.',
            action_url: '/strategy/research',
          },
        ],
      },
    } as typeof strategy)
    await screen.findByText('Approve the current session.')
    expect(screen.getByText('No approved forward release.')).toBeInTheDocument()
    expect(screen.getByText('Entry window ended at 15:20 IST.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Review Research requirement' })).toHaveAttribute(
      'href',
      '/strategy/research'
    )
    expect(screen.getByText('2 setup blockers')).toBeInTheDocument()
    expect(api.one).not.toHaveBeenCalled()
  })
  it('separates enabled automation, no trade and real-money eligibility', async () => {
    setup()
    await screen.findByText('Automation review')
    await screen.findByText('Waiting for a fresh qualifying signal')
    expect(screen.getByText(/Real-money orders will not trigger/)).toBeInTheDocument()
    expect(screen.getByText('Trend slope')).toBeInTheDocument()
    expect(screen.getByText('25001')).toBeInTheDocument()
    expect(api.stop).not.toHaveBeenCalled()
  })
  it('requires explicit STOP ALL, allows cancellation and reports pending closures truthfully', async () => {
    setup()
    const user = userEvent.setup()
    await screen.findByRole('button', { name: /Inspect NIFTY/ })
    await user.click(screen.getByRole('button', { name: 'Emergency stop' }))
    expect(screen.getByRole('button', { name: 'Block entries & request closure' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(api.stop).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Emergency stop' }))
    await user.type(screen.getByLabelText('Type STOP ALL'), 'STOP ALL')
    await user.click(screen.getByRole('button', { name: 'Block entries & request closure' }))
    await screen.findByText('Closure needs attention')
    expect(screen.queryByText('All targeted automation stopped')).not.toBeInTheDocument()
    expect(api.stop).toHaveBeenCalledTimes(1)
  })
  it('surfaces lost monitoring instead of treating old values as healthy', async () => {
    const { client } = setup()
    await screen.findByRole('button', { name: /Inspect NIFTY/ })
    api.overview.mockRejectedValue(new Error('unreachable'))
    await client.invalidateQueries({ queryKey: ['automation-monitor'] })
    await screen.findByText(/Monitoring unavailable/)
    expect(screen.getByRole('button', { name: 'Emergency stop' })).toBeEnabled()
  })
  it('loads older retained logs', async () => {
    api.logs
      .mockResolvedValueOnce({
        items: [{ id: 2, at: null, status: 'completed', message: 'Recent check', details: [] }],
        next_cursor: 2,
      })
      .mockResolvedValue({
        items: [
          { id: 1, at: null, status: 'failed', message: 'Old error', details: { why: 'timeout' } },
        ],
        next_cursor: null,
      })
    setup()
    const user = userEvent.setup()
    await screen.findByRole('button', { name: /Inspect NIFTY/ })
    await user.click(screen.getByRole('button', { name: 'Activity & logs' }))
    await screen.findByText('Recent check')
    await user.click(screen.getByRole('button', { name: 'Load older records' }))
    await screen.findByText('Old error')
    expect(api.logs).toHaveBeenLastCalledWith(13, 'executions', 2)
  })
})

it('keeps risk rejection metrics visible after later successful signal checks', async () => {
  const row = {
    ...strategy,
    last_risk_rejection: {
      at: new Date().toISOString(),
      message: 'Minimum reward-to-risk refused',
      details: { metrics: { minimum_reward_risk: '1.126' } },
    },
  }
  setup(row)
  const user = userEvent.setup()
  await user.click(await screen.findByText(/Latest entry rejection/))
  expect(screen.getByText('Minimum reward-to-risk refused')).toBeInTheDocument()
  expect(screen.getByText(/1.126/)).toBeInTheDocument()
})
it('shows the recorded option stop without presenting a plan as an approved trade', async () => {
  setup({
    ...strategy,
    entry_plan: {
      at: new Date().toISOString(),
      details: {
        context: {
          structure: {
            symbol: 'NIFTY29SEP2625000CE',
            entry_price: '40',
            stop_price: '39.45',
            planned_gross_loss: '35.75',
            objective_r: 3,
            hard_target: false,
          },
        },
      },
    },
  } as typeof strategy)
  await screen.findByText('Recorded option entry plan')
  expect(screen.getByText('NIFTY29SEP2625000CE')).toBeInTheDocument()
  expect(screen.getByText('₹39.45')).toBeInTheDocument()
  expect(screen.getByText(/3R planning objective/)).toBeInTheDocument()
  expect(screen.getByText(/Not an admission or a fill/)).toBeInTheDocument()
})
it('does not offer the monitor stop control for unsupported drafts', async () => {
  setup({ ...strategy, automation_state: 'disabled', configuration: { profile: '' } })
  await screen.findByRole('button', { name: /Inspect NIFTY/ })
  expect(screen.getByRole('button', { name: 'Stop automation & close' })).toBeDisabled()
})
