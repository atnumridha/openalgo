import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { Trade } from '@/api/kotakAssistant'
import { ManagedTrades } from './ManagedTrades'
vi.mock('./TradeIndicators', () => ({ TradeIndicators: () => null }))

it('shows gross, estimated charges and net P&L without treating stale prices as current', () => {
  const trade = {
    id: 'trade',
    mode: 'live',
    symbol: 'NIFTY19OCT2622600CE',
    exchange: 'NFO',
    product: 'MIS',
    remaining: 65,
    entry_quantity: 65,
    lot: 65,
    tick: 0.05,
    average_entry: 100,
    sl: 90,
    current_sl: 90,
    target: 120,
    status: 'protected',
    ops: [],
  } as unknown as Trade
  const props = { trades: [trade], refresh: vi.fn(), brokerage: 0 }
  const quote = { bid: 110, ask: 110.05, time: Date.now() / 1000 }
  const view = render(<ManagedTrades {...props} quote={() => quote} />)
  expect(screen.getByLabelText('Gross open P&L')).toHaveTextContent('₹650')
  expect(screen.getByLabelText('Estimated open charges')).toHaveTextContent('₹16.66')
  expect(screen.getByLabelText('Net open P&L after charges')).toHaveTextContent('₹633.34')
  view.rerender(<ManagedTrades {...props} quote={() => ({ ...quote, time: quote.time - 10 })} />)
  expect(screen.getByLabelText('Net open P&L after charges')).toHaveTextContent('Unavailable')
})

const openTrade = {
  id: 'monitor',
  mode: 'live',
  symbol: 'NIFTY19OCT2623100CE',
  exchange: 'NFO',
  product: 'MIS',
  remaining: 65,
  entry_quantity: 65,
  lot: 65,
  tick: 0.05,
  average_entry: 70,
  sl: 64,
  current_sl: 64,
  target: 82,
  status: 'protected',
  ops: [],
} as unknown as Trade

it('shows live LTP separately from the filled entry and exit bid, and updates with each quote', () => {
  const quote = { ltp: 72.25, bid: 72.1, ask: 72.3, time: Date.now() / 1000, source: 'Live feed' }
  const props = { trades: [openTrade], refresh: vi.fn() }
  const view = render(<ManagedTrades {...props} quote={() => quote} />)
  expect(screen.getByText('Current price (LTP)')).toBeInTheDocument()
  expect(screen.getByLabelText('Current market price')).toHaveTextContent('₹72.25')
  expect(screen.getByText('Live', { exact: true })).toBeInTheDocument()
  expect(screen.getByText(/Updated .* IST|Waiting for a fresh market price/)).toHaveTextContent(
    /Updated .* IST · 0s ago · Live feed/
  )
  expect(screen.getByText(/Current exit bid:/)).toHaveTextContent('₹72.10')
  view.rerender(<ManagedTrades {...props} quote={() => ({ ...quote, ltp: 73.5 })} />)
  expect(screen.getByLabelText('Current market price')).toHaveTextContent('₹73.50')
})

it('marks an aging quote stale without another market tick', () => {
  const clock = vi.spyOn(Date, 'now')
  const now = Date.now()
  clock.mockReturnValue(now)
  try {
    const quote = { ltp: 72, bid: 71.9, ask: 72.1, time: now / 1000, source: 'Live feed' }
    const props = { trades: [openTrade], refresh: vi.fn(), quote: () => quote }
    const view = render(<ManagedTrades {...props} />)
    clock.mockReturnValue(now + 6000)
    view.rerender(<ManagedTrades {...props} />)
    expect(screen.getByText('Last price (LTP)')).toBeInTheDocument()
    expect(screen.getByText('Stale', { exact: true })).toBeInTheDocument()
    expect(screen.getByText(/Updated .* IST|Waiting for a fresh market price/)).toHaveTextContent(
      '6s ago'
    )
    expect(screen.getByLabelText('Net open P&L after charges')).toHaveTextContent('Unavailable')
    expect(screen.getByText(/Last exit bid:/)).toBeInTheDocument()
    expect(screen.queryByText('Live', { exact: true })).not.toBeInTheDocument()
  } finally {
    clock.mockRestore()
  }
})

it('can display fresh LTP without suggesting that a missing exit quote is executable', () => {
  const timestamp = Date.now() / 1000
  render(
    <ManagedTrades
      trades={[openTrade]}
      refresh={vi.fn()}
      quote={() => ({ ltp: 72.25, time: timestamp, source: 'Broker snapshot' })}
    />
  )
  expect(screen.getByLabelText('Current market price')).toHaveTextContent('₹72.25')
  expect(screen.getByText('Fresh', { exact: true })).toBeInTheDocument()
  expect(screen.getByLabelText('Net open P&L after charges')).toHaveTextContent('Unavailable')
})

it.each([undefined, 0, -1, NaN, Infinity])('does not invent an LTP when the value is %s', (ltp) => {
  render(
    <ManagedTrades
      trades={[openTrade]}
      refresh={vi.fn()}
      quote={() => ({ ltp, bid: 72, ask: 72.1, time: Date.now() / 1000 })}
    />
  )
  expect(screen.getByLabelText('Current market price')).toHaveTextContent('Unavailable')
  expect(screen.getByText(/Updated .* IST|Waiting for a fresh market price/)).toHaveTextContent(
    'Waiting for a fresh market price'
  )
})
