import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
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
vi.mock('@/components/strategy/StrategyLiveChart', () => ({
  StrategyLiveChart: ({ underlying }: { underlying?: string | null }) =>
    underlying ? <div data-testid="strategy-live-chart">{underlying}</div> : null,
}))

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
  configuration: { profile: 'ema915', underlying: 'NIFTY', exchange: 'NSE_INDEX' },
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
function setup(data: typeof strategy | (typeof strategy)[] = strategy) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  api.overview.mockResolvedValue({
    server_time: new Date().toISOString(),
    scheduler: { status: 'running' },
    live_authorization: { active: false },
    strategies: Array.isArray(data) ? data : [data],
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
  it('renders the live chart for a selected strategy with an underlying', async () => {
    setup()
    expect(await screen.findByTestId('strategy-live-chart')).toHaveTextContent('NIFTY')
  })
  it('labels retained entry rejection as historical without claiming it is resolved', async () => {
    setup({ ...strategy, last_risk_rejection: {
      at: '2026-09-28T06:23:52Z', message: 'Capital policy refused entry: contract metadata required',
      details: { code: 'contract_metadata_required' },
    } } as typeof strategy)
    await screen.findByText('Capital policy refused entry: contract metadata required')
    expect(screen.getByText(/Past attempt.*current readiness check/)).toBeInTheDocument()
  })
  it('explains ordinary receiver polls without hiding genuine expired-signal failures', async () => {
    const reason = 'Signal expired; waiting for the next receiver candle'
    const row = {
      ...strategy,
      reason,
      configuration: { profile: 'receiver_momentum', exchange: 'MCX' },
      evaluation: { ...strategy.evaluation, reason, evaluated_at: '2026-09-28T18:12:06+05:30' },
    }
    const view = setup(row as typeof strategy)
    await screen.findAllByText(/Waiting for the next 5-minute candle close/)
    expect(screen.queryByText(reason)).not.toBeInTheDocument()
    expect(screen.getAllByText(/18:15:00 IST/).length).toBeGreaterThan(0)
    view.unmount()
    const expired = 'Signal expired while fetching receiver history'
    setup({ ...row, reason: expired, evaluation: { ...row.evaluation, reason: expired } } as typeof strategy)
    await screen.findAllByText(expired)
    expect(screen.queryByText(/Waiting for the next 5-minute candle close/)).not.toBeInTheDocument()
  })

  it('shows retained MCX candle progress while the latest poll waits for the next close', async () => {
    api.logs.mockResolvedValue({ items: [{
      id: 20, kind: 'signal_evaluation', at: new Date().toISOString(),
      details: { mode: 'sandbox', profile: 'receiver_momentum', reason: 'Collecting ten contiguous completed five-minute candles',
        history: [{ symbol: 'CRUDEOILM19OCT26FUT', interval: '5m', candles: 8, last_bar_at: new Date().toISOString() }],
      },
    }], next_cursor: null })
    setup({ ...strategy, configuration: { profile: 'receiver_momentum', exchange: 'MCX' } } as typeof strategy)
    await screen.findByText(/8 \/ 10 completed candles/)
    expect(api.logs).toHaveBeenCalledWith(13, 'events')
    expect(api.one).not.toHaveBeenCalled()
    expect(api.stop).not.toHaveBeenCalled()
  })
  it('explains candle warm-up without claiming an observed candle is missing', async () => {
    const warming = {
      ...strategy,
      monitor_status: 'data_unavailable',
      reason: 'The expected completed candle is missing. Inspect history timestamps below.',
      evaluation: {
        ...strategy.evaluation,
        reason: 'Collecting ten contiguous completed five-minute candles',
        technical: { ...strategy.evaluation.technical, data_ready: false },
      },
    }
    setup(warming)
    await screen.findByRole('heading', { level: 2, name: strategy.name })
    expect(screen.getAllByText(warming.evaluation.reason)).toHaveLength(2)
    expect(screen.queryByText(/expected completed candle is missing/i)).not.toBeInTheDocument()
    expect(screen.getByText(/Signal data is not ready/)).toBeInTheDocument()
    expect(api.one).not.toHaveBeenCalled()
  })
  it('keeps the inspected live strategy stable when a refresh changes priority', async () => {
    const first = { ...strategy, id: 19, name: 'Live Bollinger', mode: 'live', live_enabled: true }
    const second = { ...first, id: 20, name: 'Live Trend' }
    const { client } = setup([first, second])
    await screen.findByRole('heading', { level: 2, name: first.name })
    api.overview.mockResolvedValue({
      ...client.getQueryData(['automation-monitor']),
      strategies: [first, { ...second, open_run_count: 1 }],
    })
    await client.invalidateQueries({ queryKey: ['automation-monitor'] })
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: /^Inspect / })[0]).toHaveAccessibleName(
        `Inspect ${second.name}`
      )
    )
    expect(screen.getByRole('heading', { level: 2, name: first.name })).toBeInTheDocument()
  })
  it('opens on the live strategy without mutating or activating the saved list', async () => {
    const live = { ...strategy, id: 19, name: 'Live Bollinger', mode: 'live', live_enabled: true }
    const saved = [strategy, live]
    setup(saved)
    await screen.findByRole('heading', { level: 2, name: live.name })
    expect(screen.getAllByRole('button', { name: /^Inspect / })[0]).toHaveAccessibleName(
      `Inspect ${live.name}`
    )
    expect(saved[0].id).toBe(13)
    expect(api.one).not.toHaveBeenCalled()
    expect(api.stop).not.toHaveBeenCalled()
  })
  it('keeps the inspected strategy inside the active filter and hides stale details on no match', async () => {
    const live = { ...strategy, id: 19, name: 'Live Bollinger', mode: 'live', live_enabled: true }
    setup([strategy, live])
    const user = userEvent.setup()
    await screen.findByRole('button', { name: `Inspect ${live.name}` })
    await user.selectOptions(screen.getByLabelText('Execution mode'), 'live')
    await screen.findByRole('heading', { level: 2, name: live.name })
    await user.selectOptions(screen.getByLabelText('Execution mode'), 'sandbox')
    await screen.findByRole('heading', { level: 2, name: strategy.name })
    await user.type(screen.getByLabelText('Find a strategy'), 'does not exist')
    expect(screen.getByText('No strategies match these filters.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Stop automation & close' })
    ).not.toBeInTheDocument()
  })
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
