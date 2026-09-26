import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const rest = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  webClient: rest,
  apiClient: { get: vi.fn(), post: vi.fn() },
  authClient: { post: vi.fn() },
  fetchCSRFToken: vi.fn(),
  default: { get: vi.fn(), post: vi.fn() },
}))

vi.mock('@/utils/toast', () => ({
  showToast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

import {
  disableStrategyAutomation,
  enableStrategyAutomation,
  startAllSandboxStrategies,
  strategyQueryKeys,
} from '@/api/strategy_module'
import StrategyList from './List'

function client() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

function renderList() {
  const queryClient = client()
  return {
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <StrategyList />
        </MemoryRouter>
      </QueryClientProvider>
    ),
    queryClient,
  }
}

const stoppedStrategy = {
  id: 3,
  name: 'test stat',
  strategy_kind: 'batch',
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
  created_at: '2026-08-31T05:53:09+00:00',
  updated_at: '2026-08-31T07:03:57+00:00',
  last_finalized_run: {
    id: 6,
    pnl_realized: -52,
    stopped_at: '2026-08-31T07:03:57+00:00',
  },
}

const staleCheckpoint = {
  id: 1148,
  run_id: 6,
  ts: '2026-08-31T07:03:55+00:00',
  pnl_realized: 0,
  pnl_unrealized: -19.5,
  pnl_total: -19.5,
  pnl_peak: 0,
  pnl_trough: -19.5,
  lock_floor: null,
  trail_to_entry_active: false,
  leg_state: {},
}

beforeEach(() => {
  rest.get.mockReset()
  rest.post.mockReset()
  rest.patch.mockReset()
  rest.delete.mockReset()
})

describe('strategy list P&L', () => {
  it('places automation safety controls above saved strategies', async () => {
    rest.get.mockImplementation((url: string) => {
      if (url === '/strategy/api/automation/critical-alerts') {
        return Promise.resolve({ data: { data: [] } })
      }
      if (url === '/strategy/api/strategies') {
        return Promise.resolve({ data: { data: [] } })
      }
      if (url === '/strategy/api/automation/live-authorization') {
        return Promise.resolve({
          data: {
            live_authorization: {
              active: false,
              session_day: '2026-09-23',
              expires_at: '2026-09-23T15:30:00+05:30',
            },
          },
        })
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })

    renderList()

    const safetyHeading = await screen.findByRole('heading', {
      name: 'Automation safety controls',
    })
    const savedStrategies = screen.getByText('Saved strategies')
    expect(
      safetyHeading.compareDocumentPosition(savedStrategies) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy()
  })

  it('uses a stopped run’s finalized P&L instead of its stale live checkpoint', async () => {
    rest.get.mockImplementation((url: string) => {
      if (url === '/strategy/api/automation/critical-alerts') {
        return Promise.resolve({ data: { data: [] } })
      }
      if (url === '/strategy/api/strategies') {
        return Promise.resolve({ data: { data: [stoppedStrategy] } })
      }
      if (url === '/strategy/api/strategies/3/checkpoints') {
        return Promise.resolve({ data: { data: [staleCheckpoint], run_id: 6 } })
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })

    renderList()

    const name = await screen.findByRole('link', { name: 'test stat' })
    const row = name.closest('tr')
    expect(row).not.toBeNull()
    expect(within(row as HTMLTableRowElement).getAllByText('-52.00')).toHaveLength(2)
    expect(within(row as HTMLTableRowElement).getByText('0.00')).toBeInTheDocument()
    expect(row).not.toHaveTextContent('-19.50')
  })

  it('keeps long names inside a fixed first column while the table scrolls', async () => {
    mockStrategyList([
      { ...stoppedStrategy, name: 'NATGASMINI Momentum and Breakout Signal Receiver' },
    ])
    renderList()

    const name = await screen.findByRole('link', {
      name: 'NATGASMINI Momentum and Breakout Signal Receiver',
    })
    const table = name.closest('table') as HTMLTableElement
    const nameCell = name.closest('td') as HTMLTableCellElement
    expect(table).toHaveClass('w-max', 'min-w-full')
    expect(nameCell).toHaveClass('whitespace-normal', 'break-words')
    expect(nameCell).toHaveClass('sticky', 'left-0')
  })

  it('keeps all three P&L columns at the front of the scrolling table', async () => {
    mockStrategyList([stoppedStrategy])
    renderList()
    await screen.findByRole('link', { name: 'test stat' })

    const headers = screen.getAllByRole('columnheader')
    expect(headers.slice(0, 4).map((header) => header.textContent)).toEqual([
      'Name',
      'Realized',
      'Unrealized',
      'Total P&L',
    ])
    expect(headers[1]).toHaveClass('lg:sticky', 'lg:left-64')
    expect(headers[2]).toHaveClass('lg:sticky', 'lg:left-[24rem]')
    expect(headers[3]).toHaveClass('lg:sticky', 'lg:left-[32rem]')
  })
})

describe('current-session sandbox reset', () => {
  it('submits only a verified preview token and closes after a successful reset', async () => {
    rest.get.mockImplementation((url: string) => {
      if (url === '/strategy/api/automation/critical-alerts')
        return Promise.resolve({ data: { data: [] } })
      if (url === '/strategy/api/strategies')
        return Promise.resolve({ data: { data: [stoppedStrategy] } })
      if (url === '/strategy/api/sandbox-reset/preview')
        return Promise.resolve({
          data: {
            data: {
              session_start_utc: '2026-09-24T21:30:00Z',
              session_end_utc: '2026-09-25T21:30:00Z',
              run_count: 1,
              order_count: 2,
              trade_count: 2,
              realised_pnl: -100,
              funds_before: 99900,
              funds_after: 100000,
              blockers: [],
              version: 'a'.repeat(64),
            },
          },
        })
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })
    rest.post.mockResolvedValue({
      data: {
        data: {
          audit_id: 1,
          run_count: 1,
          order_count: 2,
          trade_count: 2,
          realised_pnl: -100,
          funds_after: 100000,
          already_done: false,
          version: 'a'.repeat(64),
        },
      },
    })

    renderList()
    await userEvent.click(await screen.findByRole('button', { name: /reset today.*sandbox/i }))
    await userEvent.click(await screen.findByRole('button', { name: /confirm reset/i }))

    expect(rest.post).toHaveBeenCalledWith('/strategy/api/sandbox-reset', {
      version: 'a'.repeat(64),
    })
    expect(await screen.findByRole('button', { name: /reset today.*sandbox/i })).toBeInTheDocument()
  })

  it('shows a blocked preview without enabling destructive confirmation', async () => {
    rest.get.mockImplementation((url: string) => {
      if (url === '/strategy/api/automation/critical-alerts') {
        return Promise.resolve({ data: { data: [] } })
      }
      if (url === '/strategy/api/strategies') {
        return Promise.resolve({ data: { data: [stoppedStrategy] } })
      }
      if (url === '/strategy/api/sandbox-reset/preview') {
        return Promise.resolve({
          data: {
            data: {
              session_start_utc: '2026-09-24T21:30:00Z',
              session_end_utc: '2026-09-25T21:30:00Z',
              run_count: 16,
              order_count: 28,
              trade_count: 28,
              realised_pnl: -1454,
              funds_before: 9998546.85,
              funds_after: 10000000.85,
              blockers: ['Sandbox funds P&L does not reconcile with strategy runs'],
              version: 'a'.repeat(64),
            },
          },
        })
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })

    renderList()
    await userEvent.click(await screen.findByRole('button', { name: /reset today.*sandbox/i }))

    expect(await screen.findByText(/funds P&L does not reconcile/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /confirm reset/i })).toBeDisabled()
    expect(rest.post).not.toHaveBeenCalled()
  })
})

function mockStrategyList(rows: object[]) {
  rest.get.mockImplementation((url: string) => {
    if (url === '/strategy/api/automation/critical-alerts')
      return Promise.resolve({ data: { data: [] } })
    if (url === '/strategy/api/strategies')
      return Promise.resolve({ data: { data: rows.map((row) => ({ ...row })) } })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
}

describe('sandbox automation controls', () => {
  it('uses the control routes and unwraps their result items', async () => {
    const item = {
      strategy_id: 3,
      name: 'Signal',
      state: 'armed',
      outcome: 'armed',
      workflow_id: 9,
      run_id: null,
      close_pending: false,
      reason: null,
    }
    rest.post
      .mockResolvedValueOnce({ data: { data: item } })
      .mockResolvedValueOnce({
        data: {
          data: { ...item, state: 'closing', outcome: 'close_pending', close_pending: true },
        },
      })
      .mockResolvedValueOnce({ data: { data: { items: [item] } } })

    expect(await enableStrategyAutomation(3)).toEqual(item)
    expect(await disableStrategyAutomation(3)).toMatchObject({
      state: 'closing',
      close_pending: true,
    })
    expect(await startAllSandboxStrategies()).toEqual({ items: [item] })
    expect(rest.post.mock.calls.map(([url]) => url)).toEqual([
      '/strategy/api/strategies/3/automation/enable',
      '/strategy/api/strategies/3/automation/disable',
      '/strategy/api/strategies/start-all-sandbox',
    ])
  })

  it('separates armed automation from a stopped run and allows batch controls', async () => {
    mockStrategyList([
      {
        ...stoppedStrategy,
        id: 3,
        name: 'Armed signal',
        strategy_kind: 'signal',
        automation_state: 'armed',
      },
      {
        ...stoppedStrategy,
        id: 4,
        name: 'Disabled signal',
        strategy_kind: 'signal',
        automation_state: 'disabled',
      },
      { ...stoppedStrategy, id: 5, name: 'Batch strategy', automation_state: 'disabled' },
      {
        ...stoppedStrategy,
        id: 6,
        name: 'Live signal',
        strategy_kind: 'signal',
        live_enabled: true,
        automation_state: 'disabled',
      },
    ])
    renderList()

    const armed = (await screen.findByRole('link', { name: 'Armed signal' })).closest(
      'tr'
    ) as HTMLElement
    expect(
      screen.getByText(/Start all starts every eligible batch strategy in sandbox/i)
    ).toBeVisible()
    expect(screen.getByRole('columnheader', { name: 'Automation' })).toBeInTheDocument()
    expect(within(armed).getByText('Armed')).toBeInTheDocument()
    expect(within(armed).getByText('stopped')).toBeInTheDocument()
    expect(within(armed).getByRole('button', { name: /disable automation/i })).toBeEnabled()
    expect(
      within(
        screen.getByRole('link', { name: 'Disabled signal' }).closest('tr') as HTMLElement
      ).getByRole('button', { name: 'Arm signals for Disabled signal' })
    ).toBeEnabled()
    const batch = screen.getByRole('link', { name: 'Batch strategy' }).closest('tr') as HTMLElement
    expect(within(batch).getByRole('button', { name: /enable automation/i })).toBeEnabled()
    expect(within(batch).queryByText(/only signal strategies/i)).not.toBeInTheDocument()
    const live = screen.getByRole('link', { name: 'Live signal' }).closest('tr') as HTMLElement
    expect(within(live).getByRole('button', { name: /enable automation/i })).toBeDisabled()
    const liveReason = within(live).getByText(/LIVE mode: sandbox automation unavailable/i)
    expect(liveReason).toBeVisible()
    expect(liveReason).not.toHaveClass('sr-only')
  })

  it('confirms disable and displays close pending without claiming completion', async () => {
    const serverRows = [
      { ...stoppedStrategy, strategy_kind: 'signal', automation_state: 'armed', status: 'running' },
    ]
    mockStrategyList(serverRows)
    let finish!: (value: object) => void
    rest.post.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
    renderList()
    await userEvent.click(await screen.findByRole('button', { name: /disable automation/i }))
    expect(screen.getByRole('dialog')).toHaveTextContent(
      'New entries stop immediately. Any open position will be sent through the existing close process and remains Closing until confirmed flat.'
    )
    expect(rest.post).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /confirm disable/i }))
    expect(rest.post).toHaveBeenCalledWith('/strategy/api/strategies/3/automation/disable')
    expect(screen.getByRole('button', { name: /disabling/i })).toBeDisabled()
    serverRows[0] = { ...serverRows[0], automation_state: 'closing' }
    finish({
      data: {
        data: {
          strategy_id: 3,
          name: 'test stat',
          state: 'closing',
          outcome: 'close_pending',
          workflow_id: 9,
          run_id: 6,
          close_pending: true,
          reason: null,
        },
      },
    })
    await waitFor(() =>
      expect(screen.getByRole('status', { name: 'Strategy start results' })).toHaveTextContent(
        'Closing…'
      )
    )
    expect(screen.queryByText(/closed/i)).not.toBeInTheDocument()
  })

  it('shows a close failure reason and retains pending exposure', async () => {
    const serverRows = [
      {
        ...stoppedStrategy,
        strategy_kind: 'signal',
        automation_state: 'armed',
        automation_state_reason: null as string | null,
      },
    ]
    mockStrategyList(serverRows)
    rest.post.mockImplementation(() => {
      serverRows[0] = {
        ...serverRows[0],
        automation_state: 'close_failed',
        automation_state_reason: 'Exit broker rejected',
      }
      return Promise.reject(
        Object.assign(new Error('Exit broker rejected'), {
          response: {
            data: {
              data: {
                strategy_id: 3,
                name: 'test stat',
                state: 'close_failed',
                outcome: 'failed',
                workflow_id: 9,
                run_id: 6,
                close_pending: true,
                reason: 'Exit broker rejected',
              },
            },
          },
        })
      )
    })
    const { queryClient } = renderList()
    await userEvent.click(await screen.findByRole('button', { name: /disable automation/i }))
    await userEvent.click(screen.getByRole('button', { name: /confirm disable/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Exit broker rejected')
    const controlStatus = screen.getByRole('status', { name: 'Strategy start results' })
    await waitFor(() => expect(controlStatus).toHaveTextContent('Close failed'))
    expect(controlStatus).toHaveTextContent('Closing until confirmed flat')
    expect(screen.queryByText(/closed/i)).not.toBeInTheDocument()

    serverRows[0] = { ...serverRows[0], automation_state: 'closing', automation_state_reason: null }
    await queryClient.invalidateQueries({ queryKey: strategyQueryKeys.list({}) })
    await waitFor(() =>
      expect(screen.getByRole('status', { name: 'Strategy start results' })).toHaveTextContent(
        'Closing…'
      )
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('replaces a pending announcement with the latest confirmed-flat list state', async () => {
    const serverRows = [{ ...stoppedStrategy, strategy_kind: 'signal', automation_state: 'armed' }]
    mockStrategyList(serverRows)
    rest.post.mockImplementation(() => {
      serverRows[0] = { ...serverRows[0], automation_state: 'closing' }
      return Promise.resolve({
        data: {
          data: {
            strategy_id: 3,
            name: 'test stat',
            state: 'closing',
            outcome: 'close_pending',
            workflow_id: 9,
            run_id: 6,
            close_pending: true,
            reason: null,
          },
        },
      })
    })
    const { queryClient } = renderList()
    await userEvent.click(await screen.findByRole('button', { name: /disable automation/i }))
    await userEvent.click(screen.getByRole('button', { name: /confirm disable/i }))
    const status = await screen.findByRole('status', { name: 'Strategy start results' })
    await waitFor(() => expect(status).toHaveTextContent('Closing'))

    serverRows[0] = { ...serverRows[0], automation_state: 'disabled' }
    await queryClient.invalidateQueries({ queryKey: strategyQueryKeys.list({}) })
    await waitFor(() =>
      expect(screen.getByRole('status', { name: 'Strategy start results' })).toHaveTextContent(
        /Disabled.*confirmed flat/i
      )
    )
    expect(screen.getByRole('status', { name: 'Strategy start results' })).not.toHaveTextContent(
      'Closing'
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('announces a later close failure from the latest list reason', async () => {
    const serverRows = [
      {
        ...stoppedStrategy,
        strategy_kind: 'signal',
        automation_state: 'armed',
        automation_state_reason: null as string | null,
      },
    ]
    mockStrategyList(serverRows)
    rest.post.mockImplementation(() => {
      serverRows[0] = { ...serverRows[0], automation_state: 'closing' }
      return Promise.resolve({
        data: {
          data: {
            strategy_id: 3,
            name: 'test stat',
            state: 'closing',
            outcome: 'close_pending',
            workflow_id: 9,
            run_id: 6,
            close_pending: true,
            reason: null,
          },
        },
      })
    })
    const { queryClient } = renderList()
    await userEvent.click(await screen.findByRole('button', { name: /disable automation/i }))
    await userEvent.click(screen.getByRole('button', { name: /confirm disable/i }))
    const status = await screen.findByRole('status', { name: 'Strategy start results' })
    await waitFor(() => expect(status).toHaveTextContent('Closing'))

    serverRows[0] = {
      ...serverRows[0],
      automation_state: 'close_failed',
      automation_state_reason: 'Broker still holds exposure',
    }
    await queryClient.invalidateQueries({ queryKey: strategyQueryKeys.list({}) })
    await waitFor(() =>
      expect(screen.getByRole('status', { name: 'Strategy start results' })).toHaveTextContent(
        'Close failed'
      )
    )
    expect(screen.getByRole('status', { name: 'Strategy start results' })).not.toHaveTextContent(
      'test stat: Closing…'
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Broker still holds exposure')
  })

  it('does not announce disable success before the refreshed list confirms it', async () => {
    const serverRows = [{ ...stoppedStrategy, strategy_kind: 'signal', automation_state: 'armed' }]
    mockStrategyList(serverRows)
    rest.post.mockResolvedValue({
      data: {
        data: {
          strategy_id: 3,
          name: 'test stat',
          state: 'disabled',
          outcome: 'disabled',
          workflow_id: 9,
          run_id: null,
          close_pending: false,
          reason: null,
        },
      },
    })
    renderList()
    await userEvent.click(await screen.findByRole('button', { name: /disable automation/i }))
    await userEvent.click(screen.getByRole('button', { name: /confirm disable/i }))
    const status = await screen.findByRole('status', { name: 'Strategy start results' })
    await waitFor(() => expect(status).toHaveTextContent('Checking latest strategy state'))
    expect(status).not.toHaveTextContent('Disabled')
  })

  it('shows a pending close immediately when the disable response is ahead of the list', async () => {
    mockStrategyList([{ ...stoppedStrategy, strategy_kind: 'signal', automation_state: 'armed' }])
    rest.post.mockResolvedValue({
      data: {
        data: {
          strategy_id: 3,
          name: 'test stat',
          state: 'closing',
          outcome: 'close_pending',
          workflow_id: 9,
          run_id: 6,
          close_pending: true,
          reason: null,
        },
      },
    })
    renderList()
    await userEvent.click(await screen.findByRole('button', { name: /disable automation/i }))
    await userEvent.click(screen.getByRole('button', { name: /confirm disable/i }))

    await waitFor(() =>
      expect(screen.getByRole('status', { name: 'Strategy start results' })).toHaveTextContent(
        'Closing…'
      )
    )
    const status = screen.getByRole('status', { name: 'Strategy start results' })
    expect(status).toHaveTextContent('Closing until confirmed flat')
    expect(status).not.toHaveTextContent('Disabled')
    const row = screen.getByRole('link', { name: 'test stat' }).closest('tr') as HTMLElement
    expect(within(row).getByText('Closing…')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: /disable automation/i })).toBeDisabled()
  })

  it('starts all sandbox strategies and reports every bulk outcome and its reason', async () => {
    mockStrategyList([
      { ...stoppedStrategy, strategy_kind: 'signal', automation_state: 'disabled' },
    ])
    rest.post.mockResolvedValue({
      data: {
        data: {
          items: [
            {
              strategy_id: 3,
              name: 'First',
              state: 'armed',
              outcome: 'armed',
              workflow_id: 9,
              run_id: null,
              close_pending: false,
              reason: 'Waiting for a valid signal',
            },
            {
              strategy_id: 4,
              name: 'Batch',
              state: 'armed',
              outcome: 'started',
              workflow_id: null,
              run_id: 22,
              close_pending: false,
              reason: null,
            },
            {
              strategy_id: 5,
              name: 'Broken',
              state: 'disabled',
              outcome: 'failed',
              workflow_id: null,
              run_id: null,
              close_pending: false,
              reason: 'Flow activation failed',
            },
          ],
        },
      },
    })
    renderList()
    await userEvent.click(await screen.findByRole('button', { name: 'Start all (sandbox)' }))
    const result = await screen.findByRole('status', { name: 'Strategy start results' })
    expect(result).toHaveTextContent('First')
    expect(result).toHaveTextContent('Armed')
    expect(result).toHaveTextContent('Batch')
    expect(result).toHaveTextContent('Started')
    expect(result).not.toHaveTextContent('Only signal strategies')
    expect(screen.getByRole('alert')).toHaveTextContent('Flow activation failed')
  })

  it('requires typed confirmation before starting all live strategies', async () => {
    mockStrategyList([{ ...stoppedStrategy, id: 3, name: 'Live batch', live_enabled: true }])
    rest.post.mockResolvedValue({
      data: {
        data: {
          items: [
            {
              strategy_id: 3,
              name: 'Live batch',
              state: 'disabled',
              outcome: 'started',
              workflow_id: null,
              run_id: 81,
              close_pending: false,
              reason: null,
            },
          ],
        },
      },
    })
    renderList()

    await userEvent.click(await screen.findByRole('button', { name: 'Start all (live)' }))
    const confirm = screen.getByRole('button', { name: 'Confirm live start' })
    expect(confirm).toBeDisabled()
    expect(screen.getByRole('dialog')).toHaveTextContent(/real broker orders/i)
    await userEvent.type(screen.getByLabelText(/type START LIVE/i), 'START LIVE')
    expect(confirm).toBeEnabled()
    await userEvent.click(confirm)

    expect(rest.post).toHaveBeenCalledWith('/strategy/api/strategies/start-all-live', {
      confirmation: 'START LIVE',
    })
    expect(await screen.findByRole('status', { name: 'Strategy start results' })).toHaveTextContent(
      'Started'
    )
  })

  it('shows a rejected live start inside the open confirmation dialog', async () => {
    mockStrategyList([{ ...stoppedStrategy, id: 3, name: 'Live batch', live_enabled: true }])
    rest.post.mockRejectedValue(
      Object.assign(new Error('You do not have permission to access this resource'), {
        response: { status: 403 },
      })
    )
    renderList()

    await userEvent.click(await screen.findByRole('button', { name: 'Start all (live)' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/type START LIVE/i), 'START LIVE')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm live start' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'Live automation authorization is inactive. Authorize live automation above, then try again.'
    )
    expect(dialog).toBeVisible()
  })
})

describe('direct live mode controls', () => {
  it('requires confirmation before enabling LIVE from a stopped strategy row', async () => {
    const rows = [{ ...stoppedStrategy, id: 3, name: 'NIFTY signal', live_enabled: false }]
    mockStrategyList(rows)
    rest.post.mockImplementation((url: string, body: { enabled: boolean }) => {
      if (url !== '/strategy/api/strategies/3/live')
        return Promise.reject(new Error(`Unexpected POST ${url}`))
      rows[0] = { ...rows[0], live_enabled: body.enabled }
      return Promise.resolve({ data: { data: { live_enabled: body.enabled } } })
    })
    renderList()

    await userEvent.click(
      await screen.findByRole('button', { name: 'Enable LIVE for NIFTY signal' })
    )
    expect(rest.post).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent(/real broker orders/i)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Enable LIVE' }))

    expect(rest.post).toHaveBeenCalledWith('/strategy/api/strategies/3/live', { enabled: true })
    const row = (await screen.findByRole('link', { name: 'NIFTY signal' })).closest(
      'tr'
    ) as HTMLElement
    await waitFor(() => expect(within(row).getByText('LIVE-enabled')).toBeInTheDocument())
  })

  it('disables LIVE directly and prevents mode changes while a run is active', async () => {
    const rows = [
      { ...stoppedStrategy, id: 3, name: 'Stopped live', live_enabled: true },
      { ...stoppedStrategy, id: 4, name: 'Running live', status: 'running', live_enabled: true },
    ]
    mockStrategyList(rows)
    rest.post.mockImplementation((url: string, body: { enabled: boolean }) => {
      if (url !== '/strategy/api/strategies/3/live')
        return Promise.reject(new Error(`Unexpected POST ${url}`))
      rows[0] = { ...rows[0], live_enabled: body.enabled }
      return Promise.resolve({ data: { data: { live_enabled: body.enabled } } })
    })
    renderList()

    const runningRow = (await screen.findByRole('link', { name: 'Running live' })).closest(
      'tr'
    ) as HTMLElement
    expect(
      within(runningRow).getByRole('button', { name: 'Disable LIVE for Running live' })
    ).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Disable LIVE for Stopped live' }))

    expect(rest.post).toHaveBeenCalledWith('/strategy/api/strategies/3/live', { enabled: false })
    const stoppedRow = (await screen.findByRole('link', { name: 'Stopped live' })).closest(
      'tr'
    ) as HTMLElement
    await waitFor(() => expect(within(stoppedRow).getByText('SANDBOX-only')).toBeInTheDocument())
  })
})

describe('individual strategy start controls', () => {
  it('starts a batch strategy in sandbox only after choosing in its row dialog', async () => {
    mockStrategyList([{ ...stoppedStrategy, id: 3, name: 'Batch strategy' }])
    rest.post.mockResolvedValue({ data: { run_id: 25, mode: 'sandbox', legs: [] } })
    renderList()

    await userEvent.click(
      await screen.findByRole('button', { name: 'Start run for Batch strategy' })
    )
    expect(rest.post).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent(/sandbox mode is paper-only/i)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Start sandbox' }))
    expect(rest.post).toHaveBeenCalledWith('/strategy/api/strategies/3/start', { mode: 'sandbox' })
  })

  it('arms a signal receiver instead of attempting a direct run', async () => {
    const rows = [
      {
        ...stoppedStrategy,
        id: 3,
        name: 'Signal receiver',
        strategy_kind: 'signal',
        automation_state: 'disabled',
      },
    ]
    mockStrategyList(rows)
    rest.post.mockImplementation((url: string) => {
      if (url !== '/strategy/api/strategies/3/automation/enable') {
        return Promise.reject(new Error(`Unexpected POST ${url}`))
      }
      rows[0] = { ...rows[0], automation_state: 'armed' }
      return Promise.resolve({
        data: {
          data: {
            strategy_id: 3,
            name: 'Signal receiver',
            state: 'armed',
            outcome: 'armed',
            workflow_id: 9,
            run_id: null,
            close_pending: false,
            reason: null,
          },
        },
      })
    })
    renderList()

    await userEvent.click(
      await screen.findByRole('button', { name: 'Arm signals for Signal receiver' })
    )
    expect(rest.post).toHaveBeenCalledWith('/strategy/api/strategies/3/automation/enable')
    expect(rest.post).not.toHaveBeenCalledWith(
      '/strategy/api/strategies/3/start',
      expect.anything()
    )
  })

  it('refuses a live start without current session authorization', async () => {
    rest.get.mockImplementation((url: string) => {
      if (url === '/strategy/api/strategies')
        return Promise.resolve({
          data: { data: [{ ...stoppedStrategy, name: 'Live batch', live_enabled: true }] },
        })
      if (url === '/strategy/api/automation/critical-alerts')
        return Promise.resolve({ data: { data: [] } })
      if (url === '/strategy/api/automation/live-authorization')
        return Promise.resolve({
          data: { live_authorization: { active: false, expires_at: '2026-09-26T03:00:00+05:30' } },
        })
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })
    renderList()

    await userEvent.click(await screen.findByRole('button', { name: 'Start run for Live batch' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'LIVE' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(/not authorized/i)
    await userEvent.type(within(dialog).getByLabelText(/START LIVE/), 'START LIVE')
    expect(within(dialog).getByRole('button', { name: 'Start live' })).toBeDisabled()
    expect(rest.post).not.toHaveBeenCalled()
  })
})
