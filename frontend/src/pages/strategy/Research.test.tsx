import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const rest = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('@/api/client', () => ({ webClient: rest }))

import Research from './Research'

const costs = {
  schedule_id: 'test-only',
  source: 'Test fixture',
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
const dataset = {
  id: 7,
  name: 'Imported provider data',
  provider: 'fixture',
  content_hash: 'abc123',
  row_count: 10000,
  session_count: 90,
  start: '2026-01-01',
  end: '2026-05-15',
  quality: 'candle_screening',
  created_at: '2026-09-25',
}
const run = {
  id: 9,
  dataset_id: 7,
  candidate: 'trend_breakout',
  status: 'completed',
  kind: 'development',
  configuration_hash: 'config123',
  frozen_at: null,
  parent_run_id: null,
  created_at: '2026-09-25',
  started_at: null,
  finished_at: null,
  error: null,
  report: {
    metrics: {
      trade_count: 0,
      net_pnl: 0,
      expectancy: null,
      profit_factor: null,
      max_drawdown_pct: 0,
      max_losing_streak: 0,
      win_rate: null,
      ending_equity: 10000,
    },
    trades: [],
    rejections: { missing_next_option_bar: 2 },
    qualification: { eligible_for_live: false, reasons: ['Candle data lacks execution evidence'] },
  },
}
const overview = () => ({
  datasets: [dataset],
  runs: [run],
  candidates: [
    {
      id: 'trend_breakout',
      name: 'Trend breakout',
      description: 'Closed-bar breakout with trend filter.',
      defaults: {
        lookback: 20,
        stop_pct: 0.1,
        target_pct: 0.2,
        volume_ratio: 1.2,
        pullback_tolerance: 0.002,
      },
    },
  ],
  worker: { online: true, last_seen: '2026-09-26' },
  limits: {},
})
const risk = () => ({
  enabled: true,
  policy: {
    capital: 10000,
    first_trade_limit: 1000,
    later_trades_limit: 1000,
    daily_limit: 2000,
    drawdown_pct: 0.2,
    cash_buffer_pct: 0.2,
    version: 'two-bucket-v1',
  },
  costs,
  accounts: {
    sandbox: {
      equity: 9500,
      peak_equity: 10000,
      drawdown: 500,
      drawdown_headroom: 1500,
      first_remaining: 600,
      later_remaining: 900,
      daily_remaining: 1500,
      paused: false,
      pause_reason: null,
      session_day: '2026-09-26',
      reserved_risk: 0,
    },
    live: null,
  },
})

function renderResearch() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Research />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

async function enterCosts() {
  for (const [label, value] of [
    ['Schedule name', 'test-only'],
    ['Fee source or reference', 'Test fixture'],
    ['Effective from', '2026-01-01'],
    ['Effective until', '2026-12-31'],
    ['Brokerage per order (INR)', '20'],
    ['Exchange fee rate', '0.0001'],
    ['SEBI fee rate', '0.000001'],
    ['GST rate', '0.18'],
    ['Stamp duty buy rate', '0.00003'],
    ['STT sell rate', '0.001'],
    ['Slippage (basis points)', '10'],
  ])
    await userEvent.type(screen.getByLabelText(label), value)
}

beforeEach(() => {
  rest.get.mockReset()
  rest.post.mockReset()
  rest.put.mockReset()
  rest.get.mockImplementation((url: string) =>
    Promise.resolve({
      data: {
        status: 'success',
        data:
          url === '/strategy/api/risk'
            ? risk()
            : url === '/strategy/api/research/runs/9'
              ? run
              : overview(),
      },
    })
  )
})

describe('Research workspace', () => {
  it('separates first and later loss budgets and marks missing account evidence unavailable', async () => {
    renderResearch()
    const sandbox = await screen.findByRole('region', { name: 'Sandbox risk budget' })
    expect(sandbox).toHaveTextContent('First filled trade remaining')
    expect(sandbox).toHaveTextContent('₹600.00')
    expect(sandbox).toHaveTextContent('All later trades remaining')
    expect(sandbox).toHaveTextContent('₹900.00')
    expect(screen.getByRole('region', { name: 'Live risk budget' })).toHaveTextContent(
      'Unavailable'
    )
    expect(screen.getByRole('heading', { name: 'Forward Sandbox qualification and live release' })).toBeVisible()
  })

  it('imports a JSON file with provenance and selects its immutable dataset', async () => {
    const bundle = {
      name: 'My imported dataset',
      provider: 'Licensed provider',
      metadata: { source_reference: 'export reference' },
      rows: [],
    }
    rest.post.mockResolvedValue({
      data: { status: 'success', data: { ...dataset, name: bundle.name } },
    })
    renderResearch()
    await userEvent.upload(
      await screen.findByLabelText('Dataset file'),
      new File([JSON.stringify(bundle)], 'dataset.json', { type: 'application/json' })
    )
    await userEvent.click(screen.getByRole('button', { name: 'Import dataset' }))
    await waitFor(() =>
      expect(rest.post).toHaveBeenCalledWith('/strategy/api/research/datasets', bundle)
    )
    expect(await screen.findByRole('status', { name: 'Import result' })).toHaveTextContent(
      'My imported dataset'
    )
  })

  it('requires metadata for a CSV and keeps malformed files out of the API', async () => {
    renderResearch()
    await userEvent.upload(
      await screen.findByLabelText('Dataset file'),
      new File(['symbol,timestamp,open,high,low,close\n'], 'bars.csv', { type: 'text/csv' })
    )
    await userEvent.click(screen.getByRole('button', { name: 'Import dataset' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('CSV metadata')
    expect(rest.post).not.toHaveBeenCalled()
  })

  it.each([
    true,
    false,
  ])('submits a reproducible development run without activating the profile (enabled=%s)', async (enabled) => {
    rest.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: {
          status: 'success',
          data:
            url === '/strategy/api/risk'
              ? { ...risk(), enabled, costs: enabled ? costs : null }
              : url.endsWith('/runs/9')
                ? run
                : overview(),
        },
      })
    )
    rest.post.mockResolvedValue({
      data: { status: 'success', data: { ...run, status: 'queued', report: null } },
    })
    renderResearch()
    await screen.findByRole('option', { name: 'Imported provider data (90 sessions)' })
    if (!enabled) await enterCosts()
    await userEvent.selectOptions(screen.getByLabelText('Research dataset'), '7')
    await userEvent.click(screen.getByRole('button', { name: 'Run development test' }))
    await waitFor(() =>
      expect(rest.post).toHaveBeenCalledWith('/strategy/api/research/runs', {
        dataset_id: 7,
        candidate: 'trend_breakout',
        parameters: {
          lookback: 20,
          stop_pct: 0.1,
          target_pct: 0.2,
          volume_ratio: 1.2,
          pullback_tolerance: 0.002,
        },
        costs,
        seed: 42,
      })
    )
    expect(rest.put).not.toHaveBeenCalled()
  })

  it('blocks run submission while the worker is offline', async () => {
    rest.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: {
          status: 'success',
          data:
            url === '/strategy/api/risk'
              ? risk()
              : { ...overview(), worker: { online: false, last_seen: null } },
        },
      })
    )
    renderResearch()
    expect(await screen.findByText('Worker offline')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Run development test' })).toBeDisabled()
  })

  it('keeps an undefined profit factor distinct from a zero net result', async () => {
    renderResearch()
    await userEvent.click(await screen.findByRole('button', { name: 'View run 9' }))
    const report = await screen.findByRole('region', { name: 'Run report' })
    expect(within(report).getByText('Net P&L', { selector: 'dt' }).parentElement).toHaveTextContent(
      '₹0.00'
    )
    expect(within(report).getByText('Profit factor').parentElement).toHaveTextContent('Unavailable')
    expect(report).toHaveTextContent('Candle data lacks execution evidence')
    expect(screen.queryByRole('button', { name: /approve live/i })).not.toBeInTheDocument()
  })

  it('does not turn an empty fee into a free trade', async () => {
    renderResearch()
    await screen.findByRole('option', { name: 'Imported provider data (90 sessions)' })
    await userEvent.selectOptions(screen.getByLabelText('Research dataset'), '7')
    await userEvent.clear(screen.getByLabelText('STT sell rate'))
    await userEvent.click(screen.getByRole('button', { name: 'Run development test' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Missing costs cannot be treated as zero'
    )
    expect(rest.post).not.toHaveBeenCalled()
  })

  it('saves the edited fee schedule for entry risk without launching a run', async () => {
    rest.put.mockResolvedValue({ data: { status: 'success', data: costs } })
    renderResearch()
    await screen.findByRole('region', { name: 'Sandbox risk budget' })
    await userEvent.clear(screen.getByLabelText('Brokerage per order (INR)'))
    await userEvent.type(screen.getByLabelText('Brokerage per order (INR)'), '15')
    await userEvent.click(screen.getByRole('button', { name: 'Update enabled profile costs' }))
    await waitFor(() =>
      expect(rest.put).toHaveBeenCalledWith('/strategy/api/risk/costs', {
        ...costs,
        brokerage_per_order: 15,
      })
    )
    expect(await screen.findByRole('status')).toHaveTextContent('cost schedule was saved')
    expect(rest.post).not.toHaveBeenCalled()
  })

  it('keeps the final holdout sealed until an explicit one-time evaluation is confirmed', async () => {
    const frozen = { ...run, frozen_at: '2026-09-26T12:00:00Z' }
    rest.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: {
          status: 'success',
          data:
            url === '/strategy/api/risk' ? risk() : url.endsWith('/runs/9') ? frozen : overview(),
        },
      })
    )
    rest.post.mockResolvedValue({ data: { status: 'success', data: frozen } })
    renderResearch()
    await userEvent.click(await screen.findByRole('button', { name: 'View run 9' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Run final holdout once' }))
    const dialog = screen.getByRole('dialog')
    const consume = within(dialog).getByRole('button', { name: 'Consume holdout and run' })
    expect(consume).toBeDisabled()
    expect(rest.post).not.toHaveBeenCalled()
    await userEvent.click(within(dialog).getByRole('checkbox'))
    await userEvent.click(consume)
    await waitFor(() =>
      expect(rest.post).toHaveBeenCalledWith('/strategy/api/research/runs/9/final-test', {})
    )
  })

  it('preserves a server holdout refusal and leaves the frozen report available', async () => {
    const frozen = { ...run, frozen_at: '2026-09-26T12:00:00Z' }
    rest.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: {
          status: 'success',
          data:
            url === '/strategy/api/risk' ? risk() : url.endsWith('/runs/9') ? frozen : overview(),
        },
      })
    )
    rest.post.mockRejectedValue(new Error('These holdout contents have already been consumed'))
    renderResearch()
    await userEvent.click(await screen.findByRole('button', { name: 'View run 9' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Run final holdout once' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.click(within(dialog).getByRole('checkbox'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Consume holdout and run' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('already been consumed')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Keep sealed' }))
    expect(screen.getByRole('region', { name: 'Run report' })).toHaveTextContent('config123')
  })

  it('cancels only the selected active research run', async () => {
    const pending = { ...run, status: 'running', report: null }
    rest.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: {
          status: 'success',
          data:
            url === '/strategy/api/risk' ? risk() : url.endsWith('/runs/9') ? pending : overview(),
        },
      })
    )
    rest.post.mockResolvedValue({
      data: { status: 'success', data: { ...pending, status: 'cancelled' } },
    })
    renderResearch()
    await userEvent.click(await screen.findByRole('button', { name: 'View run 9' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel run' }))
    await waitFor(() =>
      expect(rest.post).toHaveBeenCalledWith('/strategy/api/research/runs/9/cancel', {})
    )
    expect(screen.queryByRole('button', { name: 'Freeze this version' })).not.toBeInTheDocument()
  })

  it('requires reconciliation and a reason to resume a specific paused account', async () => {
    const pausedRisk = risk()
    pausedRisk.accounts.sandbox.paused = true
    rest.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: { status: 'success', data: url === '/strategy/api/risk' ? pausedRisk : overview() },
      })
    )
    rest.post.mockResolvedValue({ data: { status: 'success', data: pausedRisk.accounts.sandbox } })
    renderResearch()
    const budget = await screen.findByRole('region', { name: 'Sandbox risk budget' })
    const resume = within(budget).getByRole('button', { name: 'Resume after reconciliation' })
    expect(resume).toBeDisabled()
    expect(budget).toHaveTextContent('Daily loss allowances will not reset')
    await userEvent.type(
      within(budget).getByLabelText('Review reason'),
      'Broker positions and ledger reconciled'
    )
    expect(resume).toBeDisabled()
    await userEvent.click(within(budget).getByRole('checkbox'))
    await userEvent.click(resume)
    await waitFor(() =>
      expect(rest.post).toHaveBeenCalledWith('/strategy/api/risk/resume', {
        mode: 'sandbox',
        reason: 'Broker positions and ledger reconciled',
        reconciled: true,
      })
    )
    expect(
      within(screen.getByRole('region', { name: 'Live risk budget' })).queryByRole('button', {
        name: 'Resume after reconciliation',
      })
    ).not.toBeInTheDocument()
  })

  it('shows an inactive profile without implying its budgets protect existing entries', async () => {
    rest.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: {
          status: 'success',
          data:
            url === '/strategy/api/risk' ? { ...risk(), enabled: false, costs: null } : overview(),
        },
      })
    )
    renderResearch()
    expect(await screen.findByText('Capital profile inactive')).toBeVisible()
    expect(screen.getByText(/Existing flows retain their current risk rules/)).toBeVisible()
    expect(screen.queryByText('Budget monitored')).not.toBeInTheDocument()
    expect(screen.queryByText(/Entry risk is blocked until/)).not.toBeInTheDocument()
    expect(screen.getByLabelText('STT sell rate')).toHaveValue(null)
  })

  it('explicitly enables the capital profile when saving verified costs and refreshes its state', async () => {
    let enabled = false
    rest.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: {
          status: 'success',
          data:
            url === '/strategy/api/risk'
              ? { ...risk(), enabled, costs: enabled ? costs : null }
              : overview(),
        },
      })
    )
    rest.put.mockImplementation(() => {
      enabled = true
      return Promise.resolve({ data: { status: 'success', data: costs } })
    })
    renderResearch()
    await screen.findByText('Capital profile inactive')
    await enterCosts()
    const activate = screen.getByRole('button', { name: 'Save costs and enable capital profile' })
    expect(activate).toHaveAccessibleDescription(/managed Strategy Module entries/)
    expect(activate).toHaveAccessibleDescription(/managed live entries/)
    expect(rest.put).not.toHaveBeenCalled()
    await userEvent.click(activate)
    await waitFor(() => expect(rest.put).toHaveBeenCalledWith('/strategy/api/risk/costs', costs))
    expect(await screen.findByText('Capital profile enabled')).toBeVisible()
    expect(rest.post).not.toHaveBeenCalled()
  })

  it('rejects files exceeding the server import size before reading them', async () => {
    renderResearch()
    const large = new File(['{}'], 'large.json', { type: 'application/json' })
    Object.defineProperty(large, 'size', { value: 21 * 1024 * 1024 })
    await userEvent.upload(screen.getByLabelText('Dataset file'), large)
    await userEvent.click(screen.getByRole('button', { name: 'Import dataset' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('20 MB')
    expect(rest.post).not.toHaveBeenCalled()
  })

  it('labels training separately and exposes out-of-sample outcome gaps', async () => {
    const reported = {
      ...run,
      report: {
        ...run.report,
        oos: {
          ...run.report,
          qualification: {
            eligible_for_live: false,
            reasons: ['Incomplete position outcomes make this replay unqualified.'],
          },
        },
        metrics: { ...run.report.metrics, exposure_bars: 32, max_observed_open_drawdown_pct: 5.1 },
      },
    }
    rest.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: {
          status: 'success',
          data:
            url === '/strategy/api/risk' ? risk() : url.endsWith('/runs/9') ? reported : overview(),
        },
      })
    )
    renderResearch()
    await userEvent.click(await screen.findByRole('button', { name: 'View run 9' }))
    expect(
      await screen.findByRole('heading', { name: 'Development training evidence' })
    ).toBeVisible()
    expect(
      screen.getByText('Incomplete position outcomes make this replay unqualified.')
    ).toBeVisible()
    expect(screen.getAllByText('Bars with exposure')[0].parentElement).toHaveTextContent('32')
  })

  it('shows the recorded cost schedule rather than the current editable assumptions in run evidence', async () => {
    const recorded = {
      ...run,
      configuration: {
        candidate: 'trend_breakout',
        parameters: { lookback: 10 },
        seed: 42,
        costs: { ...costs, schedule_id: 'Historical fee version', stt_sell_rate: 0.002 },
        engine_version: 'v1',
        dataset_hash: 'dataset123',
        risk_policy_version: 'two-bucket-v1',
      },
    }
    rest.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: {
          status: 'success',
          data:
            url === '/strategy/api/risk' ? risk() : url.endsWith('/runs/9') ? recorded : overview(),
        },
      })
    )
    renderResearch()
    await userEvent.click(await screen.findByRole('button', { name: 'View run 9' }))
    await userEvent.click(await screen.findByText('Recorded experiment inputs'))
    const inputs = screen.getByRole('region', { name: 'Recorded experiment inputs' })
    expect(inputs).toHaveTextContent('Historical fee version')
    expect(inputs).toHaveTextContent('0.002')
    expect(screen.getByLabelText('STT sell rate')).toHaveValue(0.001)
  })
})
