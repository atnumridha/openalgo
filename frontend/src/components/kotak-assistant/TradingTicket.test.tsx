import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TradingTicket, TradingTicketView, useTradingTicket } from './TradingTicket'
import { kotakAssistantApi, type SetupResult, type Snapshot, type Plan } from '@/api/kotakAssistant'

vi.mock('@/api/kotakAssistant', () => ({
  kotakAssistantApi: {
    enter: vi.fn(),
    preview: vi.fn(() => new Promise(() => {})),
    cashPlan: vi.fn(),
  },
}))

describe('Ticket level clarity', () => {
  it('enables automatic target exits on new tickets without placing an order', () => {
    render(
      <TradingTicket
        mode="live"
        leg={{ symbol: 'NIFTY19OCT2622600CE', lotsize: 65, tick_size: 0.05, ask: 100 }}
        refresh={vi.fn()}
      />
    )
    expect(screen.getByLabelText('Automatic target exit')).toBeChecked()
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })

  it('publishes edited draft prices for the same contract without placing an order', () => {
    const changed = vi.fn()
    render(
      <TradingTicket
        mode="analyze"
        leg={{ symbol: 'NIFTY19OCT2622600CE', lotsize: 65, tick_size: 0.05, ask: 100 }}
        refresh={vi.fn()}
        onDraftChange={changed}
      />
    )
    fireEvent.change(screen.getByLabelText('Entry limit ₹'), { target: { value: '105' } })
    fireEvent.change(screen.getByLabelText('Stop loss trigger ₹'), { target: { value: '90' } })
    fireEvent.change(screen.getByLabelText('Profit target ₹'), { target: { value: '130' } })
    expect(changed).toHaveBeenLastCalledWith({
      symbol: 'NIFTY19OCT2622600CE',
      mode: 'analyze',
      entry: 105,
      sl: 90,
      target: 130,
    })
    expect(screen.getByLabelText('Entry limit ₹')).toHaveValue(105)
    expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(90)
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(130)
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })
  it('updates target and chart draft for each reward ratio and changed stop', () => {
    const changed = vi.fn()
    render(
      <TradingTicket
        mode="analyze"
        leg={{ symbol: 'NIFTY19OCT2622600CE', lotsize: 65, tick_size: 0.05, ask: 100 }}
        refresh={vi.fn()}
        onDraftChange={changed}
      />
    )
    fireEvent.change(screen.getByLabelText('Stop loss trigger ₹'), { target: { value: '90' } })
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(120)
    fireEvent.click(screen.getByRole('button', { name: 'Risk reward 1:1.5' }))
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(115)
    fireEvent.click(screen.getByRole('button', { name: 'Risk reward 1:5' }))
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(150)
    expect(changed).toHaveBeenLastCalledWith(
      expect.objectContaining({ entry: 100, sl: 90, target: 150 })
    )
    expect(screen.getByText('₹650.00')).toBeInTheDocument()
    expect(screen.getByText('₹3,250.00')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Stop loss trigger ₹'), { target: { value: '95' } })
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(125)
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })
  it('automatically fills a labelled draft SL and 1:2 target when only the ask is available', () => {
    render(
      <TradingTicket
        mode="analyze"
        leg={{ symbol: 'NIFTY19OCT2622600CE', lotsize: 65, tick_size: 0.05, ask: 100 }}
        refresh={vi.fn()}
      />
    )
    expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(90)
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(120)
    expect(screen.getByText(/10% premium buffer/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Entry limit ₹'), { target: { value: '110' } })
    expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(99)
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(132)
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })
  it('preserves manual SL and target edits when the suggested plan arrives later', () => {
    const leg = { symbol: 'NIFTY19OCT2622600CE', lotsize: 65, tick_size: 0.05, ask: 100 }
    const props = { mode: 'analyze' as const, leg, refresh: vi.fn() }
    const view = render(<TradingTicket {...props} />)
    fireEvent.change(screen.getByLabelText('Stop loss trigger ₹'), { target: { value: '92' } })
    fireEvent.change(screen.getByLabelText('Profit target ₹'), { target: { value: '125' } })
    view.rerender(
      <TradingTicket
        {...props}
        desk={
          {
            selected_plan: { entry: 100, sl: 85, target: 130 },
            analysis: {},
            settings: { cutoff: '15:15' },
          } as never
        }
      />
    )
    expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(92)
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(125)
  })
  it('uses the volatility plan rather than the percentage fallback when available', () => {
    render(
      <TradingTicket
        mode="analyze"
        leg={{ symbol: 'NIFTY19OCT2622600CE', lotsize: 65, tick_size: 0.05, ask: 100 }}
        refresh={vi.fn()}
        desk={
          {
            selected_plan: { entry: 100, sl: 85, target: 130 },
            analysis: {},
            settings: { cutoff: '15:15' },
          } as never
        }
      />
    )
    expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(85)
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(130)
    expect(screen.getByText('Automatic SL · option volatility')).toBeInTheDocument()
  })
})

describe('Daily entry block', () => {
  it('still disables a new buy when a configured daily money limit is reached', () => {
    render(
      <TradingTicket
        mode="live"
        leg={{ symbol: 'NIFTY19OCT2622600CE', lotsize: 65, tick_size: 0.05, ask: 100 }}
        refresh={vi.fn()}
        desk={
          {
            exchange: 'NFO',
            day: { halt: 'Daily loss limit reached' },
            analysis: {},
            settings: {},
          } as never
        }
      />
    )
    expect(screen.getByRole('button', { name: /Buy 1 lot/ })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('Daily loss limit reached')
  })
})

const setupLeg = { symbol: 'NIFTY19OCT2622600CE', lotsize: 65, tick_size: 0.05, ask: 100 }
const setupDesk = {
  scope: 'account:analyze',
  exchange: 'NFO',
  underlying: 'NIFTY',
  analysis: { action: 'WAIT', zones: [] },
  settings: { cutoff: '15:15', brokerage: 0, slippage: 0 },
  selected_plan: { entry: 100, sl: 85, target: 130 },
} as unknown as Snapshot
const openingSetup: SetupResult = {
  strategy: 'opening_reversal',
  version: '1.0',
  mode: 'literal',
  stage: 'triggered',
  direction: 'CE',
  reason: 'Crossed trigger',
  evidence: [],
  setup_id: 'setup-1',
  index_entry: 22520,
  invalidation: 22480,
  index_target: 22600,
  eligible: true,
}
function AdoptionHarness({
  data = setupDesk,
  setup = openingSetup,
  selectedPlan,
}: {
  data?: Snapshot
  setup?: SetupResult
  selectedPlan?: Plan | null
}) {
  const controller = useTradingTicket({
    leg: setupLeg,
    desk: data,
    mode: 'analyze',
    refresh: vi.fn(),
    selectedPlan,
  })
  return (
    <>
      <button onClick={() => controller.adoptSetup(setup)}>Adopt chart setup</button>
      <TradingTicketView controller={controller} />
    </>
  )
}
const cashPlan = {
  entry: 100,
  sl: 92.55,
  target: 123.4,
  quantity: 65,
  risk: 499.14,
  reward: 1501.47,
  loss_budget: 500,
  target_multiple: 3,
  net_target: 1500,
  costs: 16.2,
  net_rr: 3,
  fits: true,
  reason: '',
  max_lots: null,
  fee_verified: '2026-10-14',
  fee_source: 'exchange schedule',
  fee_breakdown: {},
  risk_policy: { kind: 'cash_budget', loss_budget: 500, target_multiple: 3, net_target: 1500 },
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(kotakAssistantApi.cashPlan).mockResolvedValue(cashPlan as never)
})
describe('Setup adoption and cash risk', () => {
  it('does not inherit a trend index stop when adopting an opening cash setup', async () => {
    render(
      <AdoptionHarness
        data={{ ...setupDesk, analysis: { ...setupDesk.analysis, invalidation: 22480 } }}
        setup={{ ...openingSetup, invalidation: null, index_target: null }}
      />
    )
    fireEvent.click(screen.getByLabelText('Exit on index invalidation'))
    expect(screen.getByLabelText('Exit on index invalidation')).toBeChecked()
    fireEvent.click(screen.getByRole('button', { name: 'Adopt chart setup' }))
    await waitFor(() =>
      expect(screen.getByLabelText('Exit on index invalidation')).not.toBeChecked()
    )
    expect(screen.getByLabelText('Exit on index invalidation')).toBeDisabled()
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })
  it('adopts index context without putting an index price in the premium ticket, and preserves edits on polling', async () => {
    const trend = {
      ...openingSetup,
      strategy: 'trend' as const,
      mode: 'confirmed' as const,
      stage: 'ready',
    }
    const view = render(<AdoptionHarness setup={trend} />)
    fireEvent.click(screen.getByRole('button', { name: 'Adopt chart setup' }))
    expect(screen.getByLabelText('Entry limit ₹')).toHaveValue(100)
    expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(85)
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(130)
    fireEvent.change(screen.getByLabelText('Entry limit ₹'), { target: { value: '105' } })
    fireEvent.change(screen.getByLabelText('Stop loss trigger ₹'), { target: { value: '93' } })
    fireEvent.change(screen.getByLabelText('Profit target ₹'), { target: { value: '144' } })
    view.rerender(
      <AdoptionHarness
        setup={trend}
        data={{ ...setupDesk, selected_plan: { entry: 101, sl: 80, target: 143 } } as Snapshot}
      />
    )
    expect(screen.getByLabelText('Entry limit ₹')).toHaveValue(105)
    expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(93)
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(144)
    await waitFor(() =>
      expect(kotakAssistantApi.preview).toHaveBeenLastCalledWith(
        'analyze',
        expect.objectContaining({
          strategy: 'trend',
          strategy_version: '1.0',
          risk_policy: { kind: 'structural_premium', planned_sl: 93, planned_target: 144 },
        })
      )
    )
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })
  it('uses the server cash plan for the total quantity and recalculates after lots or budget change', async () => {
    render(<AdoptionHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'Adopt chart setup' }))
    await waitFor(() => expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(92.55))
    await waitFor(() =>
      expect(kotakAssistantApi.preview).toHaveBeenLastCalledWith(
        'analyze',
        expect.objectContaining({
          strategy: 'opening_reversal',
          strategy_version: '1.0',
          setup_id: 'setup-1',
          index_invalidation: undefined,
          auto_invalidation: false,
          risk_policy: {
            kind: 'cash_budget',
            loss_budget: 500,
            target_multiple: 3,
            net_target: 1500,
          },
        })
      )
    )
    expect(screen.getByLabelText('Net loss budget ₹')).toHaveValue(500)
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(123.4)
    expect(screen.getByText(/Net target.*1,500/)).toBeInTheDocument()
    expect(kotakAssistantApi.cashPlan).toHaveBeenLastCalledWith({
      entry: 100,
      quantity: 65,
      tick: 0.05,
      exchange: 'NFO',
      loss_budget: 500,
      target_multiple: 3,
      lot: 65,
    })
    vi.mocked(kotakAssistantApi.cashPlan).mockResolvedValue({
      ...cashPlan,
      quantity: 130,
      sl: 96.4,
      target: 111.8,
    } as never)
    fireEvent.change(screen.getByLabelText('Lots'), { target: { value: '2' } })
    await waitFor(() => expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(96.4))
    expect(kotakAssistantApi.cashPlan).toHaveBeenLastCalledWith(
      expect.objectContaining({ quantity: 130, loss_budget: 500 })
    )
    fireEvent.change(screen.getByLabelText('Net loss budget ₹'), { target: { value: '700' } })
    await waitFor(() =>
      expect(kotakAssistantApi.cashPlan).toHaveBeenLastCalledWith(
        expect.objectContaining({ quantity: 130, loss_budget: 700 })
      )
    )
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })
  it('explains an unsuitable budget and allows an explicit return to manual premium risk', async () => {
    vi.mocked(kotakAssistantApi.cashPlan).mockResolvedValue({
      ...cashPlan,
      fits: false,
      reason: 'Budget is smaller than estimated charges',
    } as never)
    render(<AdoptionHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'Adopt chart setup' }))
    await screen.findByText('Budget is smaller than estimated charges')
    expect(screen.getByRole('button', { name: /Buy 1 lot/ })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Use manual premium risk' }))
    expect(screen.getByRole('button', { name: /Buy 1 lot/ })).toBeEnabled()
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })

  it('does not adopt another pane premium plan when the selected plan is explicitly unavailable', () => {
    render(
      <AdoptionHarness
        selectedPlan={null}
        data={{ ...setupDesk, selected_plan: { entry: 700, sl: 600, target: 900 } } as Snapshot}
        setup={{ ...openingSetup, strategy: 'trend', mode: 'confirmed', stage: 'ready' }}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Adopt chart setup' }))
    expect(screen.getByLabelText('Entry limit ₹')).toHaveValue(100)
    expect(screen.getByLabelText('Stop loss trigger ₹')).toHaveValue(90)
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })
  it('clears adopted policy when the broker scope changes', async () => {
    const view = render(<AdoptionHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'Adopt chart setup' }))
    await waitFor(() => expect(screen.getByLabelText('Net loss budget ₹')).toHaveValue(500))
    view.rerender(<AdoptionHarness data={{ ...setupDesk, scope: 'different-broker:analyze' }} />)
    expect(screen.queryByLabelText('Net loss budget ₹')).not.toBeInTheDocument()
    expect(screen.queryByText(/Adopted opening reversal/)).not.toBeInTheDocument()
  })
  it('supports every approved trend reward ratio against the edited premium stop', () => {
    render(<TradingTicket mode="analyze" leg={setupLeg} refresh={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Stop loss trigger ₹'), { target: { value: '90' } })
    for (const [ratio, target] of [
      [1.5, 115],
      [2, 120],
      [3, 130],
      [4, 140],
      [5, 150],
      [6, 160],
    ]) {
      fireEvent.click(screen.getByRole('button', { name: `Risk reward 1:${ratio}` }))
      expect(screen.getByLabelText('Profit target ₹')).toHaveValue(target)
    }
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })
})
