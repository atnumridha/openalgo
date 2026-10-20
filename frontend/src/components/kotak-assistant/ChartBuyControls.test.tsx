import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ChartBuyControls, TradingTicketView, useTradingTicket } from './TradingTicket'
import type { Snapshot } from '@/api/kotakAssistant'
import { kotakAssistantApi } from '@/api/kotakAssistant'

vi.mock('@/api/kotakAssistant', () => ({ kotakAssistantApi: { preview: vi.fn(), enter: vi.fn() } }))
const leg = { symbol: 'NIFTY19OCT2622600CE', lotsize: 65, tick_size: 0.05, ask: 100 }
const plan = {
  entry: 100,
  sl: 90,
  target: 120,
  quantity: 130,
  risk: 1350,
  reward: 2500,
  costs: 30,
  net_rr: 1.85,
  fits: true,
  fee_breakdown: {},
  fee_source: '',
  fee_verified: '2026-10-14',
}
const desk = {
  scope: 'u:account:analyze',
  exchange: 'NFO',
  underlying: 'NIFTY',
  analysis: { action: 'WAIT', zones: [] },
  settings: { cutoff: '15:15' },
  day: {},
} as unknown as Snapshot
function Harness({
  mode = 'analyze',
  data = desk,
  option = leg,
}: {
  mode?: 'analyze' | 'live'
  data?: Snapshot
  option?: typeof leg
}) {
  const controller = useTradingTicket({ leg: option, desk: data, mode, refresh: vi.fn() })
  return (
    <>
      <ChartBuyControls controller={controller} />
      <TradingTicketView controller={controller} />
    </>
  )
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(kotakAssistantApi.preview).mockResolvedValue({
    ticket: 'preview-id',
    expires: Date.now() / 1000 + 60,
    mode: 'analyze',
    plan,
  } as never)
  vi.mocked(kotakAssistantApi.enter).mockResolvedValue({
    status: 'entry_pending',
    reason: 'Awaiting fills',
  } as never)
})
describe('Buy directly on chart', () => {
  it('lets a valid manual Live ticket be clicked before a background preview is ready', async () => {
    vi.mocked(kotakAssistantApi.preview).mockResolvedValue({
      ticket: 'manual-live',
      expires: Date.now() / 1000 + 5,
      mode: 'live',
      plan,
    } as never)
    render(<Harness mode="live" />)
    const buy = screen.getByRole('button', { name: 'Buy CE · 1 lot · LIVE' })
    expect(buy).toBeEnabled()
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
    fireEvent.click(buy)
    fireEvent.click(buy)
    await waitFor(() =>
      expect(kotakAssistantApi.enter).toHaveBeenCalledExactlyOnceWith('live', 'manual-live')
    )
    expect(kotakAssistantApi.preview).toHaveBeenCalledWith(
      'live',
      expect.objectContaining({ quantity: 65, sl: 90, target: 120 })
    )
  })
  it('shows a click-time broker rejection without submitting an entry', async () => {
    vi.mocked(kotakAssistantApi.preview).mockRejectedValue(
      new Error('Fresh account books unavailable')
    )
    render(<Harness />)
    const buy = screen.getByRole('button', { name: 'Buy CE · 1 lot · PAPER' })
    expect(buy).toBeEnabled()
    fireEvent.click(buy)
    await waitFor(() =>
      expect(
        within(screen.getByLabelText('CE chart order controls')).getByRole('status')
      ).toHaveTextContent('Fresh account books unavailable')
    )
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })
  it('does not submit a different contract when selection changes during click-time validation', async () => {
    let resolve!: (value: unknown) => void
    vi.mocked(kotakAssistantApi.preview).mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done as (value: unknown) => void
        })
    )
    const view = render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: 'Buy CE · 1 lot · PAPER' }))
    expect(screen.getByRole('button', { name: 'Submitting…' })).toBeDisabled()
    view.rerender(<Harness option={{ ...leg, symbol: 'NIFTY19OCT2622600PE' }} />)
    await act(async () =>
      resolve({ ticket: 'old-ce', expires: Date.now() / 1000 + 5, mode: 'analyze', plan })
    )
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
    expect(
      within(screen.getByLabelText('PE chart order controls')).getByRole('status')
    ).toHaveTextContent('Order changed while checking')
  })
  it('retries an unknown submission using the same broker intent without making a new ticket', async () => {
    vi.mocked(kotakAssistantApi.enter).mockRejectedValueOnce(new Error('Network outcome unknown'))
    render(<Harness />)
    const buy = screen.getByRole('button', { name: 'Buy CE · 1 lot · PAPER' })
    fireEvent.click(buy)
    await waitFor(() =>
      expect(
        within(screen.getByLabelText('CE chart order controls')).getByRole('status')
      ).toHaveTextContent('Network outcome unknown')
    )
    vi.mocked(kotakAssistantApi.preview).mockResolvedValue({
      ticket: 'must-not-replace',
      expires: Date.now() / 1000 + 5,
      mode: 'analyze',
      plan,
    } as never)
    fireEvent.click(buy)
    await waitFor(() => expect(kotakAssistantApi.enter).toHaveBeenCalledTimes(2))
    expect(vi.mocked(kotakAssistantApi.enter).mock.calls).toEqual([
      ['analyze', 'preview-id'],
      ['analyze', 'preview-id'],
    ])
  })
  it('keeps invalid lots, off-tick prices and invalid long-option stop levels disabled', () => {
    render(<Harness />)
    const buy = screen.getByRole('button', { name: 'Buy CE · 1 lot · PAPER' })
    fireEvent.change(screen.getByLabelText('Lots'), { target: { value: '0' } })
    expect(buy).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Lots'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Entry limit ₹'), { target: { value: '100.01' } })
    expect(buy).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Entry limit ₹'), { target: { value: '100' } })
    fireEvent.change(screen.getByLabelText('Stop loss trigger ₹'), { target: { value: '101' } })
    expect(buy).toBeDisabled()
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })
  it('changes the chart ratio and invalidates the previous target approval', async () => {
    render(<Harness />)
    const buy = screen.getByRole('button', { name: 'Buy CE · 1 lot · PAPER' })
    await waitFor(() => expect(buy).toBeEnabled())
    vi.mocked(kotakAssistantApi.preview).mockImplementation(() => new Promise(() => {}))
    const chart = within(screen.getByLabelText('CE chart order controls'))
    fireEvent.click(chart.getByRole('button', { name: '1:5', exact: true }))
    expect(screen.getByLabelText('Profit target ₹')).toHaveValue(150)
    expect(chart.getByRole('button', { name: '1:5', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    expect(buy).toBeEnabled()
    fireEvent.click(buy)
    await waitFor(() =>
      expect(kotakAssistantApi.preview).toHaveBeenLastCalledWith(
        'analyze',
        expect.objectContaining({ target: 150 })
      )
    )
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
    expect(chart.getByLabelText('Gross P&L at Target')).toHaveTextContent('₹3,250')
    expect(chart.getByLabelText('Net P&L at Target')).toHaveTextContent('₹3,228.35')
  })
  it('scales premium and gross outcomes with lots while broker checks are unavailable', async () => {
    vi.mocked(kotakAssistantApi.preview).mockImplementation(() => new Promise(() => {}))
    render(<Harness />)
    fireEvent.change(screen.getByLabelText('CE lots'), { target: { value: '2' } })
    const chart = within(screen.getByLabelText('CE chart order controls'))
    expect(chart.getByText('Premium ₹13,000.00')).toBeInTheDocument()
    expect(chart.getByLabelText('Gross P&L at SL')).toHaveTextContent('-₹1,300')
    expect(chart.getByLabelText('Gross P&L at Target')).toHaveTextContent('₹2,600')
    expect(chart.getByLabelText('Estimated charges at Target')).toHaveTextContent('₹35.81')
    expect(chart.getByLabelText('Net P&L at Target')).toHaveTextContent('₹2,564.19')
    fireEvent.change(screen.getByLabelText('CE lots'), { target: { value: '0' } })
    expect(chart.getByLabelText('Net P&L at SL')).toHaveTextContent('—')
    expect(chart.getByLabelText('Net P&L at Target')).toHaveTextContent('—')
  })
  it('shows fee-aware estimates even when the broker rejects entry outside market hours', async () => {
    vi.mocked(kotakAssistantApi.preview).mockRejectedValue(new Error('Market closed'))
    render(<Harness />)
    const chart = within(screen.getByLabelText('CE chart order controls'))
    await waitFor(() => expect(chart.getByRole('status')).toHaveTextContent('Market closed'))
    expect(chart.getByLabelText('Net P&L at SL')).toHaveTextContent('-₹664.16')
    expect(chart.getByLabelText('Estimated charges at Target')).toHaveTextContent('₹17.91')
    expect(chart.getByLabelText('Net P&L at Target')).toHaveTextContent('₹1,282.09')
    const buy = screen.getByRole('button', { name: 'Buy CE · 1 lot · PAPER' })
    expect(buy).toBeEnabled()
    fireEvent.click(buy)
    await waitFor(() => expect(kotakAssistantApi.preview).toHaveBeenCalledTimes(2))
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })
  it('keeps cost estimates available without treating an expired preview as entry approval', async () => {
    vi.mocked(kotakAssistantApi.preview).mockResolvedValue({
      ticket: 'expired',
      expires: Date.now() / 1000 - 1,
      mode: 'analyze',
      plan,
    } as never)
    render(<Harness />)
    const chart = within(screen.getByLabelText('CE chart order controls'))
    await waitFor(() =>
      expect(chart.getByRole('status')).toHaveTextContent('refresh broker checks on Buy')
    )
    expect(chart.getByLabelText('Net P&L at SL')).toHaveTextContent('-₹664.16')
    vi.mocked(kotakAssistantApi.preview).mockResolvedValue({
      ticket: 'refreshed',
      expires: Date.now() / 1000 + 5,
      mode: 'analyze',
      plan,
    } as never)
    fireEvent.click(screen.getByRole('button', { name: 'Buy CE · 1 lot · PAPER' }))
    await waitFor(() =>
      expect(kotakAssistantApi.enter).toHaveBeenCalledExactlyOnceWith('analyze', 'refreshed')
    )
  })
  it('shares lot and manually edited levels with the detailed ticket and submits once', async () => {
    render(<Harness />)
    fireEvent.change(screen.getByLabelText('CE lots'), { target: { value: '2' } })
    expect(screen.getByLabelText('Lots')).toHaveValue(2)
    fireEvent.change(screen.getByLabelText('Stop loss trigger ₹'), { target: { value: '92' } })
    await waitFor(() =>
      expect(kotakAssistantApi.preview).toHaveBeenLastCalledWith(
        'analyze',
        expect.objectContaining({
          symbol: leg.symbol,
          quantity: 130,
          sl: 92,
          target: 116,
          auto_target: true,
        })
      )
    )
    const buy = screen.getByRole('button', { name: 'Buy CE · 2 lots · PAPER' })
    await waitFor(() => expect(buy).toBeEnabled())
    fireEvent.click(buy)
    fireEvent.click(buy)
    await waitFor(() =>
      expect(kotakAssistantApi.enter).toHaveBeenCalledExactlyOnceWith('analyze', 'preview-id')
    )
  })
  it('invalidates the old preview immediately when lots change', async () => {
    render(<Harness />)
    const buy = screen.getByRole('button', { name: 'Buy CE · 1 lot · PAPER' })
    await waitFor(() => expect(buy).toBeEnabled())
    await waitFor(() => expect(kotakAssistantApi.preview).toHaveBeenCalled())
    vi.mocked(kotakAssistantApi.preview).mockImplementation(() => new Promise(() => {}))
    fireEvent.change(screen.getByLabelText('CE lots'), { target: { value: '3' } })
    const changedBuy = screen.getByRole('button', { name: 'Buy CE · 3 lots · PAPER' })
    expect(changedBuy).toBeEnabled()
    fireEvent.click(changedBuy)
    await waitFor(() =>
      expect(kotakAssistantApi.preview).toHaveBeenLastCalledWith(
        'analyze',
        expect.objectContaining({ quantity: 195 })
      )
    )
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })
  it('keeps manual Live Buy available after trade-count guidance', async () => {
    render(
      <Harness
        mode="live"
        data={
          {
            ...desk,
            day: { entry_limits: { blocked_reason: 'Daily entry limit reached · 3 entries' } },
          } as never
        }
      />
    )
    expect(screen.getByRole('button', { name: 'Buy CE · 1 lot · LIVE' })).toBeEnabled()
    expect(kotakAssistantApi.enter).not.toHaveBeenCalled()
  })
  it('submits PE in the explicitly displayed Live mode', async () => {
    const pe = { ...leg, symbol: 'NIFTY19OCT2622600PE' }
    vi.mocked(kotakAssistantApi.preview).mockResolvedValue({
      ticket: 'live-pe',
      expires: Date.now() / 1000 + 60,
      mode: 'live',
      plan,
    } as never)
    render(<Harness mode="live" option={pe} />)
    const buy = screen.getByRole('button', { name: 'Buy PE · 1 lot · LIVE' })
    await waitFor(() => expect(buy).toBeEnabled())
    fireEvent.click(buy)
    await waitFor(() =>
      expect(kotakAssistantApi.enter).toHaveBeenCalledExactlyOnceWith('live', 'live-pe')
    )
    expect(kotakAssistantApi.preview).toHaveBeenLastCalledWith(
      'live',
      expect.objectContaining({ symbol: pe.symbol, quantity: 65 })
    )
  })
  it('clears a known rejected intent before submitting a changed order', async () => {
    vi.mocked(kotakAssistantApi.enter).mockRejectedValueOnce({
      response: { status: 409 },
      message: 'Preview expired',
    })
    render(<Harness />)
    let buy = screen.getByRole('button', { name: 'Buy CE · 1 lot · PAPER' })
    await waitFor(() => expect(buy).toBeEnabled())
    fireEvent.click(buy)
    await screen.findAllByText(/Preview expired/)
    vi.mocked(kotakAssistantApi.preview).mockResolvedValue({
      ticket: 'new-size',
      expires: Date.now() / 1000 + 60,
      mode: 'analyze',
      plan,
    } as never)
    fireEvent.change(screen.getByLabelText('CE lots'), { target: { value: '2' } })
    buy = screen.getByRole('button', { name: 'Buy CE · 2 lots · PAPER' })
    await waitFor(() => expect(buy).toBeEnabled())
    fireEvent.click(buy)
    await waitFor(() =>
      expect(kotakAssistantApi.enter).toHaveBeenLastCalledWith('analyze', 'new-size')
    )
  })
})
