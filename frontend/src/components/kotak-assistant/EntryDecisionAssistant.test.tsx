import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { EntryDecisionAssistant } from './EntryDecisionAssistant'
const query = vi.hoisted(() => vi.fn())
vi.mock('@tanstack/react-query', () => ({ useQuery: query }))
vi.mock('@/api/kotakAssistant', () => ({ kotakAssistantApi: { entryDecisions: vi.fn() } }))
afterEach(() => vi.clearAllMocks())
const plan = {
  entry: 100.05,
  sl: 97.05,
  target: 108,
  quantity: 65,
  risk: 220,
  reward: 440,
  costs: 42,
  net_rr: 2,
  fits: true,
  reason: '',
  source: 'Fresh ask',
  fee_breakdown: { brokerage: 20 },
}
const signal = {
  strategy: 'breakout_retest',
  direction: 'CE',
  stage: 'ready',
  eligible: true,
  reason: 'Retest confirmed',
  expires: 1060,
  reference: { price: 22500 },
  trigger: 22520,
}
const data = {
  generated_at: 1000,
  symbol: 'NIFTY27OCT2622700CE',
  side: 'CE',
  plan_fresh: true,
  plan,
  candidates: {
    breakout_retest: signal,
    daily_sweep: { ...signal, strategy: 'daily_sweep', stage: 'waiting_trigger', eligible: false },
  },
  plan_reason: '',
}
const props = {
  symbol: data.symbol,
  side: 'CE' as const,
  underlying: 'NIFTY',
  lots: '1',
  onLotsChange: vi.fn(),
  onUse: vi.fn(),
  now: 1000,
  scope: 'neo:live',
  replay: false,
}
it('shows the exact selected premium plan and only loads levels on an explicit click', () => {
  query.mockReturnValue({ data, isError: false })
  render(<EntryDecisionAssistant {...props} />)
  expect(screen.getByText('Breakout + Retest')).toBeVisible()
  expect(screen.getByText('Daily Liquidity Sweep')).toBeVisible()
  expect(
    within(screen.getByRole('region', { name: 'Breakout + Retest setup' })).getByText('₹100.05')
  ).toBeVisible()
  expect(
    within(screen.getByRole('region', { name: 'Breakout + Retest setup' })).getByText('₹97.05')
  ).toBeVisible()
  expect(
    within(screen.getByRole('region', { name: 'Breakout + Retest setup' })).getByText('₹108.00')
  ).toBeVisible()
  expect(props.onUse).not.toHaveBeenCalled()
  fireEvent.click(
    within(screen.getByRole('region', { name: 'Breakout + Retest setup' })).getByRole('button', {
      name: 'Use setup · load ticket',
    })
  )
  expect(props.onUse).toHaveBeenCalledWith(plan)
})
it('watching a trigger is not entry permission', () => {
  query.mockReturnValue({ data, isError: false })
  render(<EntryDecisionAssistant {...props} />)
  const sweep = within(screen.getByRole('region', { name: 'Daily Liquidity Sweep setup' }))
  expect(sweep.getByRole('button', { name: 'Use setup · load ticket' })).toBeDisabled()
  expect(
    within(screen.getByRole('region', { name: 'Breakout + Retest setup' })).getByRole('button', {
      name: 'Use setup · load ticket',
    })
  ).toBeEnabled()
  expect(sweep.getByText(/WAIT/)).toBeVisible()
})
it('hides stale cached premiums and never loads during errors or replay', () => {
  query.mockReturnValue({ data, isError: true })
  const view = render(<EntryDecisionAssistant {...props} />)
  expect(screen.queryByText('₹100.05')).not.toBeInTheDocument()
  expect(
    screen
      .getAllByRole('button', { name: 'Use setup · load ticket' })
      .every((b) => b.hasAttribute('disabled'))
  ).toBe(true)
  view.rerender(<EntryDecisionAssistant {...props} replay />)
  expect(screen.getAllByText(/Read-only replay/)).toHaveLength(3)
  expect(
    screen
      .getAllByRole('button', { name: 'Use setup · load ticket' })
      .every((b) => b.hasAttribute('disabled'))
  ).toBe(true)
})
it('cannot load levels for an opposite-side signal or another selected contract', () => {
  query.mockReturnValue({
    data: {
      ...data,
      candidates: { ...data.candidates, breakout_retest: { ...signal, direction: 'PE' } },
    },
    isError: false,
  })
  render(<EntryDecisionAssistant {...props} />)
  expect(
    screen
      .getAllByRole('button', { name: 'Use setup · load ticket' })
      .every((b) => b.hasAttribute('disabled'))
  ).toBe(true)
  expect(props.onUse).not.toHaveBeenCalled()
})
it('shows daily pivot context separately from the selected premium plan and requires confirmation', () => {
  const now = Date.parse('2026-10-23T04:00:00Z') / 1000
  const levels = { P: 100, R1: 110, R2: 120, R3: 130, S1: 90, S2: 80, S3: 70 }
  const pivotSignal = {
    ...signal,
    strategy: 'pivot_rejection',
    pattern: 'Rejection + confirmation',
    reference: { price: 90, name: 'S1' },
    invalidation: 89.7,
    index_target: 100,
  }
  query.mockReturnValue({
    data: {
      ...data,
      generated_at: now,
      pivots: {
        underlying: 'NIFTY',
        session_date: '2026-10-23',
        reference_date: '2026-10-22',
        previous: { high: 110, low: 90, close: 100 },
        levels,
      },
      candidates: {
        ...data.candidates,
        pivot_rejection: {
          ...pivotSignal,
          directions: { CE: { ...pivotSignal, stage: 'waiting_trigger', eligible: false } },
        },
        pivot_retest: pivotSignal,
      },
    },
    isError: false,
  })
  render(<EntryDecisionAssistant {...props} now={now} />)
  fireEvent.change(screen.getByLabelText('Pivot entry pattern'), {
    target: { value: 'pivot_rejection' },
  })
  expect(
    screen.getByRole('table', { name: 'Previous-session Traditional daily pivots' })
  ).toBeVisible()
  expect(screen.getByText(/2026-10-22/)).toBeVisible()
  expect(screen.getByText(/Next index pivot/)).toBeVisible()
  expect(
    within(screen.getByRole('region', { name: 'Daily Pivots setup' })).getByText('₹97.05')
  ).toBeVisible()
  expect(
    within(screen.getByRole('region', { name: 'Daily Pivots setup' })).getByRole('button', {
      name: 'Use setup · load ticket',
    })
  ).toBeDisabled()
})

it('keeps fixed same-day pivots visible through quote delays without preserving trade readiness', () => {
  const now = Date.parse('2026-10-23T04:00:00Z') / 1000
  const pivots = {
    underlying: 'NIFTY',
    session_date: '2026-10-23',
    reference_date: '2026-10-22',
    previous: { high: 110, low: 90, close: 100 },
    levels: { P: 100, R1: 110, R2: 120, R3: 130, S1: 90, S2: 80, S3: 70 },
  }
  query.mockReturnValue({ data: { ...data, generated_at: now, pivots }, isError: false })
  const view = render(<EntryDecisionAssistant {...props} now={now} />)
  view.rerender(<EntryDecisionAssistant {...props} now={now + 6} />)
  expect(
    screen.getByRole('table', { name: 'Previous-session Traditional daily pivots' })
  ).toBeVisible()
  expect(
    within(screen.getByRole('region', { name: 'Daily Pivots setup' })).getByRole('button', {
      name: 'Use setup · load ticket',
    })
  ).toBeDisabled()
  expect(screen.queryByText('₹100.05')).not.toBeInTheDocument()
  view.rerender(<EntryDecisionAssistant {...props} now={now + 86400} />)
  expect(
    screen.queryByRole('table', { name: 'Previous-session Traditional daily pivots' })
  ).not.toBeInTheDocument()
})

it('always displays three strategy columns using one shared market snapshot', () => {
  query.mockReturnValue({ data, isError: false })
  render(<EntryDecisionAssistant {...props} />)
  for (const name of ['Breakout + Retest', 'Daily Pivots', 'Daily Liquidity Sweep']) {
    expect(screen.getByRole('region', { name: `${name} setup` })).toBeVisible()
  }
  expect(screen.getByRole('group', { name: 'Entry strategy comparison' })).toHaveClass(
    'grid-cols-3'
  )
  expect(screen.getAllByLabelText('Decision plan lots')).toHaveLength(1)
  expect(query).toHaveBeenCalledTimes(1)
  expect(screen.queryByRole('button', { name: 'Daily Pivots' })).not.toBeInTheDocument()
})

it('shows computed premiums and the risk rejection instead of hiding the entire plan', () => {
  const reason = 'Planned total-position loss exceeds ₹1,000 after charges; reduce lots'
  query.mockReturnValue({
    data: { ...data, plan: { ...plan, fits: false, risk: 1532.5, reason }, plan_reason: reason },
    isError: false,
  })
  render(<EntryDecisionAssistant {...props} />)
  const column = within(screen.getByRole('region', { name: 'Breakout + Retest setup' }))
  expect(column.getByText('₹100.05')).toBeVisible()
  expect(column.getByText('₹97.05')).toBeVisible()
  expect(column.getByText('₹108.00')).toBeVisible()
  expect(column.getByText(reason)).toBeVisible()
  expect(column.getByRole('button', { name: 'Use setup · load ticket' })).toBeDisabled()
  expect(screen.queryByText(/CE SETUP READY/)).not.toBeInTheDocument()
})

it('keeps the shared decision observation polling active while the tab is in the background', () => {
  query.mockReturnValue({ data, isError: false })
  render(<EntryDecisionAssistant {...props} />)
  const options = query.mock.calls[0][0]
  expect(options.refetchInterval).toBe(1000)
  expect(options.refetchIntervalInBackground).toBe(true)
})
