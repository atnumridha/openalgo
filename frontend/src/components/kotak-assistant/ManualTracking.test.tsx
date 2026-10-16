import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useManualTracking, ManualTrackedTrades, ManualTrackingTicket } from './ManualTracking'
import type { TrackingTrade } from './trackingStore'
import { loadTracking, saveTracking } from './trackingStore'
import { kotakAssistantApi } from '@/api/kotakAssistant'

const saved = vi.hoisted(() => new Map<string, TrackingTrade>())
vi.mock('./trackingStore', () => ({
  loadTracking: vi.fn(async (scope: string) =>
    [...saved.values()].filter((r) => r.scope === scope)
  ),
  saveTracking: vi.fn(async (row: TrackingTrade) => {
    saved.set(row.id, row)
  }),
}))
vi.mock('./TradeIndicators', () => ({
  TradeIndicators: ({ fetchHistory }: { fetchHistory: boolean }) => (
    <p>History fetch {String(fetchHistory)}</p>
  ),
}))
vi.mock('@/hooks/useMarketData', () => ({ useMarketData: () => ({ data: new Map() }) }))
vi.mock('@/api/kotakAssistant', () => ({
  kotakAssistantApi: { enter: vi.fn(), exit: vi.fn(), adopt: vi.fn(), stop: vi.fn() },
}))
const leg = { symbol: 'NIFTY19OCT2623100CE', lotsize: 65, tick_size: 0.05 }
function Desk({
  symbol = leg.symbol,
  scope = 'alice:kotak',
  price = undefined as number | undefined,
}) {
  const controller = useManualTracking(scope)
  return (
    <>
      <ManualTrackingTicket
        controller={controller}
        leg={{ ...leg, symbol, ask: price, ltp: price }}
        exchange="NFO"
      />
      <h3>Open trades & live monitoring</h3>
      <ManualTrackedTrades controller={controller} interval="5m" />
    </>
  )
}
beforeEach(() => {
  saved.clear()
  vi.clearAllMocks()
})
it('adds a selected-strike trade locally, survives remount, and records an entered close without broker orders', async () => {
  const view = render(<Desk />)
  fireEvent.change(screen.getByLabelText('Tracked entry price'), { target: { value: '70.95' } })
  fireEvent.change(screen.getByLabelText('Tracked lots'), { target: { value: '2' } })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Add to tracking' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Add to tracking' }))
  await screen.findByRole('region', { name: `Tracking only ${leg.symbol}` })
  const trade = screen.getByRole('region', { name: `Tracking only ${leg.symbol}` })
  expect(within(trade).getByText(/2 lots · 130 units/)).toBeInTheDocument()
  expect(within(trade).getByLabelText('Tracked filled entry')).toHaveTextContent('₹70.95')
  expect(within(trade).getByLabelText('Tracked SL level')).toHaveTextContent('₹63.85')
  expect(within(trade).getByLabelText('Tracked profit target')).toHaveTextContent('₹85.15')
  expect(within(trade).getByLabelText('Planned gross risk')).toHaveTextContent('₹923.00')
  expect(within(trade).getByLabelText('Planned gross profit')).toHaveTextContent('₹1,846.00')
  expect(within(trade).getByLabelText('Estimated net profit at target')).not.toHaveTextContent(
    'Unavailable'
  )
  expect(screen.getByText('History fetch false')).toBeInTheDocument()
  view.unmount()
  render(<Desk />)
  await screen.findByRole('region', { name: `Tracking only ${leg.symbol}` })
  fireEvent.change(screen.getByLabelText(`Closing price ${leg.symbol}`), {
    target: { value: '75' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Record close' }))
  await waitFor(() =>
    expect(
      screen.queryByRole('region', { name: `Tracking only ${leg.symbol}` })
    ).not.toBeInTheDocument()
  )
  const row = [...saved.values()][0]
  expect(row.entry).toBe(70.95)
  expect(row.exit).toBe(75)
  expect(row.closed).toBeGreaterThan(0)
  expect(screen.getByText(/Gross ₹526.50/)).toBeInTheDocument()
  for (const method of Object.values(kotakAssistantApi)) expect(method).not.toHaveBeenCalled()
})
it('restores older records with a visible automatic plan even before live quotes reconnect', async () => {
  saved.set('legacy', {
    id: 'legacy',
    scope: 'alice:kotak',
    symbol: leg.symbol,
    exchange: 'NFO',
    lot: 65,
    lots: 1,
    entry: 100,
    created: 1,
  })
  const view = render(<Desk />)
  const trade = await screen.findByRole('region', { name: `Tracking only ${leg.symbol}` })
  expect(within(trade).getByLabelText('Tracked filled entry')).toHaveTextContent('₹100.00')
  expect(within(trade).getByLabelText('Tracked SL level')).toHaveTextContent('₹90.00')
  expect(within(trade).getByLabelText('Tracked profit target')).toHaveTextContent('₹120.00')
  expect(within(trade).getByText(/Automatic plan.*10% SL.*1:2/)).toBeInTheDocument()
  expect(within(trade).getByLabelText('Tracked gross P&L')).toHaveTextContent('Unavailable')
  expect(within(trade).queryByText(/Broker-confirmed/)).not.toBeInTheDocument()
  view.unmount()
  render(<Desk />)
  const restored = await screen.findByRole('region', { name: `Tracking only ${leg.symbol}` })
  expect(within(restored).getByLabelText('Tracked profit target')).toHaveTextContent('₹120.00')
  for (const method of Object.values(kotakAssistantApi)) expect(method).not.toHaveBeenCalled()
})
it('retains saved custom levels after remount and when correcting the entry', async () => {
  saved.set('custom', {
    id: 'custom',
    scope: 'alice:kotak',
    symbol: leg.symbol,
    exchange: 'NFO',
    lot: 65,
    lots: 1,
    entry: 100,
    sl: 95,
    target: 115,
    tick: 0.05,
    automatic_sl: false,
    reward_ratio: 3,
    created: 1,
  })
  render(<Desk />)
  const trade = await screen.findByRole('region', { name: `Tracking only ${leg.symbol}` })
  expect(within(trade).getByLabelText('Tracked SL level')).toHaveTextContent('₹95.00')
  expect(within(trade).getByLabelText('Tracked profit target')).toHaveTextContent('₹115.00')
  fireEvent.change(screen.getByLabelText(`Correct entry ${leg.symbol}`), {
    target: { value: '110' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save entry' }))
  await waitFor(() =>
    expect(saved.get('custom')).toMatchObject({ entry: 110, sl: 95, target: 155 })
  )
  expect(within(trade).getByLabelText('Planned gross risk')).toHaveTextContent('₹975.00')
})
it('clears the entry when the contract changes and isolates saved records by user', async () => {
  saved.set('other', {
    id: 'other',
    scope: 'bob:kotak',
    symbol: leg.symbol,
    exchange: 'NFO',
    lot: 65,
    lots: 1,
    entry: 50,
    created: 1,
  })
  const view = render(<Desk />)
  await act(async () => {})
  expect(
    screen.queryByRole('region', { name: `Tracking only ${leg.symbol}` })
  ).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Tracked entry price'), { target: { value: '70.95' } })
  view.rerender(<Desk symbol="NIFTY19OCT2623100PE" />)
  expect(screen.getByLabelText('Tracked entry price')).toHaveValue(null)
  expect(screen.getByRole('button', { name: 'Add to tracking' })).toBeDisabled()
})
it('does not report success when local storage fails', async () => {
  vi.mocked(saveTracking).mockRejectedValueOnce(new Error('Storage full'))
  render(<Desk />)
  fireEvent.change(screen.getByLabelText('Tracked entry price'), { target: { value: '70' } })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Add to tracking' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Add to tracking' }))
  await screen.findByText('Storage full')
  expect(
    screen.queryByRole('region', { name: `Tracking only ${leg.symbol}` })
  ).not.toBeInTheDocument()
  expect(loadTracking).toHaveBeenCalledWith('alice:kotak')
})
it('reloads a committed close when a stale window attempts to save an entry correction', async () => {
  const row: TrackingTrade = {
    id: 'stale',
    scope: 'alice:kotak',
    symbol: leg.symbol,
    exchange: 'NFO',
    lot: 65,
    lots: 1,
    entry: 100,
    sl: 90,
    target: 120,
    created: 1,
  }
  saved.set(row.id, row)
  render(<Desk />)
  await screen.findByRole('region', { name: `Tracking only ${leg.symbol}` })
  saved.set(row.id, { ...row, closed: 1792044000, exit: 111 })
  vi.mocked(saveTracking).mockRejectedValueOnce(new Error('Trade already closed in another window'))
  fireEvent.change(screen.getByLabelText(`Correct entry ${leg.symbol}`), {
    target: { value: '102' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save entry' }))
  await screen.findByText('Trade already closed in another window')
  expect(
    screen.queryByRole('region', { name: `Tracking only ${leg.symbol}` })
  ).not.toBeInTheDocument()
  expect(saved.get(row.id)).toMatchObject({ entry: 100, exit: 111, closed: 1792044000 })
  for (const method of Object.values(kotakAssistantApi)) expect(method).not.toHaveBeenCalled()
})
it('auto-fills selected price, recalculates all ratios and preserves an edited fill during updates', async () => {
  const view = render(<Desk price={100} />)
  await act(async () => {})
  expect(screen.getByLabelText('Tracked entry price')).toHaveValue(100)
  expect(screen.getByLabelText('Tracked stop loss')).toHaveValue(90)
  for (const ratio of [1.5, 2, 3, 4, 5, 6]) {
    fireEvent.click(
      screen.getByRole('button', { name: `Tracking risk reward 1:${ratio}`, exact: true })
    )
    expect(screen.getByLabelText('Tracked target')).toHaveValue(100 + 10 * ratio)
  }
  fireEvent.click(screen.getByRole('button', { name: 'Tracking risk reward 1:2', exact: true }))
  fireEvent.change(screen.getByLabelText('Tracked entry price'), { target: { value: '200' } })
  expect(screen.getByLabelText('Tracked stop loss')).toHaveValue(180)
  expect(screen.getByLabelText('Tracked target')).toHaveValue(240)
  view.rerender(<Desk price={110} />)
  expect(screen.getByLabelText('Tracked entry price')).toHaveValue(200)
  fireEvent.change(screen.getByLabelText('Tracked stop loss'), { target: { value: '190' } })
  expect(screen.getByLabelText('Tracked target')).toHaveValue(220)
  fireEvent.click(screen.getByRole('button', { name: 'Auto fill', exact: true }))
  expect(screen.getByLabelText('Tracked entry price')).toHaveValue(110)
  expect(screen.getByLabelText('Tracked stop loss')).toHaveValue(99)
  expect(screen.getByLabelText('Tracked target')).toHaveValue(132)
  fireEvent.click(screen.getByRole('button', { name: 'Add to tracking' }))
  await waitFor(() => expect(saved.size).toBe(1))
  expect([...saved.values()][0]).toMatchObject({ entry: 110, sl: 99, target: 132, reward_ratio: 2 })
})
