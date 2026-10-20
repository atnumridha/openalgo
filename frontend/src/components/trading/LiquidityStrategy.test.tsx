import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TradingTerminal } from '@/lib/trading/terminal'
import { LiquidityStrategy } from './LiquidityStrategy'
const shared = vi.hoisted(() => ({ data: {} as Record<string, unknown>, post: vi.fn() }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: shared.data, isError: false }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))
vi.mock('@/api/client', () => ({ webClient: { get: vi.fn(), post: shared.post } }))
vi.mock('@/hooks/useBrokerCurrencyFormatter', () => ({
  useBrokerCurrencyFormatter: () => (x: number) => `INR ${x}`,
  useBrokerPriceFormatter: () => (x: number) => `USD ${x}`,
}))
afterEach(() => vi.clearAllMocks())
function setup(replay = false, stale = false) {
  shared.data = {
    running: true,
    config: { mode: 'paper', entry_mode: 'review', leverage: 5 },
    paper: {
      view: {
        plan_revision: 'revision-1',
        asof: Date.now() / 1000 - (stale ? 20 : 0),
        execution_enabled: true,
        candidate: { stage: 'TRIGGERED', direction: 'LONG', trigger: 100 },
        plan: {
          setup_id: 'x',
          entry: 101,
          stop: 99,
          target: 110,
          quantity: 1,
          net_risk: 1,
          net_target: 3,
        },
      },
    },
    live: {},
  }
  const overlay = vi.fn()
  const target = () =>
    ({
      cryptoResearchSnapshot: () => ({ replay }),
      showLiquidityExecutionPlan: overlay,
    }) as unknown as TradingTerminal
  return { target, overlay }
}
describe('Liquidity execution panel', () => {
  it('shows native prices, configured cash currency, and does not submit on render', () => {
    const { target } = setup()
    render(<LiquidityStrategy target={target} />)
    expect(screen.getByText('USD 101')).toBeInTheDocument()
    expect(screen.getByText('INR 1')).toBeInTheDocument()
    expect(shared.post).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /Enter PAPER/ })).toBeEnabled()
  })
  it('disables entries and live chart overlays during replay', () => {
    const { target, overlay } = setup(true)
    render(<LiquidityStrategy target={target} />)
    expect(screen.getByRole('button', { name: /Enter PAPER/ })).toBeDisabled()
    expect(overlay).toHaveBeenLastCalledWith(null)
  })
  it('does not allow a stale preview to enter', () => {
    const { target } = setup(false, true)
    render(<LiquidityStrategy target={target} />)
    expect(screen.getByRole('button', { name: /Enter PAPER/ })).toBeDisabled()
  })
  it('submits only the selected setup approval when clicked', () => {
    shared.post.mockResolvedValue({ data: { message: 'Queued' } })
    const { target } = setup()
    render(<LiquidityStrategy target={target} />)
    fireEvent.click(screen.getByRole('button', { name: /Enter PAPER/ }))
    expect(shared.post).toHaveBeenCalledWith('/liquidity-strategy/api/control', {
      mode: 'paper',
      action: 'approve',
      setup_id: 'x',
      revision: 'revision-1',
    })
  })
})
