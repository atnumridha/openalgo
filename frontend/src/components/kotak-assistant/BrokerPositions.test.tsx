import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { BrokerMonitorSnapshot, Trade } from '@/api/kotakAssistant'
import { BrokerPositions, unownedBrokerPositions } from './BrokerPositions'

vi.mock('./TradeIndicators', () => ({ TradeIndicators: () => null }))
const now = Date.now() / 1000
const today = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Kolkata',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
}).format(new Date(now * 1000))
const data = {
  scope: 'u:account:live:observer',
  mode: 'live',
  book_time: now,
  error: null,
  positions: [
    {
      symbol: 'NIFTY19OCT2623100CE',
      exchange: 'NFO',
      product: 'MIS',
      quantity: 65,
      average_entry: 100,
      average_entry_verified: true,
      entry_basis: 'Today’s broker fills',
      average_price: 100,
      ltp: 110,
      pnl: 650,
      lot: 65,
      tick: 0.05,
    },
  ],
  orders: [],
  fills: [],
  days: {},
} as BrokerMonitorSnapshot
const props = {
  data,
  trades: [] as Trade[],
  interval: '5m',
  now,
  brokerage: 0,
  quote: () => ({ ltp: 110, bid: 109.95, ask: 110.05, time: now, source: 'Live feed' }),
}

it('automatically displays a broker position with live price and net P&L without an add/adopt action', () => {
  render(<BrokerPositions {...props} />)
  const card = screen.getByRole('region', { name: 'Broker position NIFTY19OCT2623100CE MIS' })
  expect(within(card).getByLabelText('Broker filled entry')).toHaveTextContent('₹100.00')
  expect(within(card).getByLabelText('Broker current price')).toHaveTextContent('₹110.00')
  expect(within(card).getByLabelText('Broker gross open P&L')).toHaveTextContent('₹650.00')
  expect(within(card).getByLabelText('Broker estimated net open P&L')).toHaveTextContent('₹633.34')
  expect(within(card).getByLabelText('Broker SL')).toHaveTextContent('Not set at broker')
  expect(within(card).getByLabelText('Broker target')).toHaveTextContent('Not set at broker')
  expect(within(card).queryByRole('button')).not.toBeInTheDocument()
})

it('updates partial exits and removes positions once a fresh broker book confirms flat', () => {
  const view = render(<BrokerPositions {...props} />)
  view.rerender(
    <BrokerPositions
      {...props}
      data={{ ...data, positions: [{ ...data.positions[0], quantity: 130 }] }}
    />
  )
  expect(screen.getByLabelText('Broker gross open P&L')).toHaveTextContent('₹1,300.00')
  view.rerender(
    <BrokerPositions
      {...props}
      data={{ ...data, positions: [{ ...data.positions[0], quantity: 0 }] }}
    />
  )
  expect(screen.queryByRole('region', { name: /Broker position/ })).not.toBeInTheDocument()
})

it('shows stale account state without treating the last known position as confirmed live exposure', () => {
  render(
    <BrokerPositions
      {...props}
      data={{ ...data, error: 'Broker session unavailable', book_time: now - 30 }}
    />
  )
  expect(screen.getByText('Broker session unavailable')).toBeInTheDocument()
  expect(screen.getByLabelText('Broker current price')).toHaveTextContent('₹110.00')
  expect(screen.getByLabelText('Broker gross open P&L')).toHaveTextContent('Unavailable')
  expect(screen.getByText(/Last known position/)).toBeInTheDocument()
  expect(screen.getByLabelText('Broker SL')).toHaveTextContent('Not present in last saved orders')
})

it('reads actual counter-side stops and targets including their remaining quantities and status', () => {
  const order = {
    symbol: data.positions[0].symbol,
    exchange: 'NFO',
    product: 'MIS',
    action: 'SELL',
    quantity: 65,
    filled_quantity: 0,
    order_status: 'trigger pending',
  }
  render(
    <BrokerPositions
      {...props}
      data={{
        ...data,
        orders: [
          { ...order, orderid: 'stop-1', pricetype: 'SL', trigger_price: 90, price: 88 },
          {
            ...order,
            orderid: 'target-1',
            pricetype: 'LIMIT',
            trigger_price: 0,
            price: 120,
            order_status: 'open',
          },
        ],
      }}
    />
  )
  expect(screen.getByLabelText('Broker SL')).toHaveTextContent('₹90.00')
  expect(screen.getByLabelText('Broker target')).toHaveTextContent('₹120.00')
  expect(screen.getByText(/stop-1.*65.*trigger pending/)).toBeInTheDocument()
})

it('keeps shorts and other symbols, and hides only exact live terminal-managed matches', () => {
  const rows = {
    ...data,
    positions: [
      data.positions[0],
      { ...data.positions[0], exchange: 'BFO' },
      { ...data.positions[0], product: 'NRML' },
    ],
  }
  const terminal = {
    ...data.positions[0],
    mode: 'live',
    status: 'protected',
    remaining: 65,
  } as unknown as Trade
  expect(unownedBrokerPositions(rows, [terminal])).toHaveLength(2)
  expect(unownedBrokerPositions(rows, [{ ...terminal, mode: 'analyze' }])).toHaveLength(3)
  render(
    <BrokerPositions
      {...props}
      data={{ ...data, positions: [{ ...data.positions[0], quantity: -65 }] }}
      quote={() => ({ ltp: 90, time: now })}
    />
  )
  expect(screen.getByText(/SHORT.*65 units/)).toBeInTheDocument()
  expect(screen.getByLabelText('Broker gross open P&L')).toHaveTextContent('₹650.00')
})
it('shows the full broker quantity when an app trade adds to the same terminal-managed contract', () => {
  const terminal = {
    ...data.positions[0],
    mode: 'live',
    status: 'protected',
    remaining: 65,
  } as unknown as Trade
  const broker = { ...data, positions: [{ ...data.positions[0], quantity: 130 }] }
  expect(unownedBrokerPositions(broker, [terminal])).toHaveLength(1)
  render(<BrokerPositions {...props} data={broker} trades={[terminal]} />)
  expect(screen.getByText(/Broker total.*65 terminal-managed units/)).toBeInTheDocument()
})

it('does not invent an original entry or net P&L for unverified carried positions', () => {
  render(
    <BrokerPositions
      {...props}
      data={{ ...data, positions: [{ ...data.positions[0], average_entry_verified: false }] }}
    />
  )
  expect(screen.getByLabelText('Broker estimated net open P&L')).toHaveTextContent('Unavailable')
  expect(screen.getByText(/Broker average/)).toBeInTheDocument()
})
it('shows broker fills in time order even when the broker report arrives unordered', () => {
  const fill = {
    symbol: 'NIFTY19OCT2623100CE',
    exchange: 'NFO',
    product: 'MIS',
    action: 'BUY',
    quantity: 65,
    timestamp: '15-Oct-2026 10:00:00',
  }
  const fills = [
    { ...fill, tradeid: 'middle', orderid: 'middle', average_price: 110, epoch: now - 10 },
    { ...fill, tradeid: 'latest', orderid: 'latest', average_price: 120, epoch: now },
    { ...fill, tradeid: 'earliest', orderid: 'earliest', average_price: 100, epoch: now - 20 },
  ]
  render(
    <BrokerPositions
      {...props}
      data={{
        ...data,
        day: today,
        positions: [],
        fills,
        days: { [today]: { positions: [], orders: [], fills } },
      }}
    />
  )
  fireEvent.click(screen.getByText('Saved broker fills · 3 today', { exact: true }))
  const rows = within(screen.getByRole('table')).getAllByRole('row')
  expect(rows[1]).toHaveTextContent('₹120.00')
  expect(rows[3]).toHaveTextContent('₹100.00')
})
it('dates a saved prior-day report instead of labelling its fills as today after restart', () => {
  render(
    <BrokerPositions
      {...props}
      now={Date.parse('2026-10-16T10:00:00+05:30') / 1000}
      data={{
        ...data,
        day: '2026-10-15',
        fills: [],
        days: { '2026-10-15': { positions: [], orders: [], fills: [] } },
      }}
    />
  )
  expect(
    screen.getByText('Saved broker fills · 0 on 2026-10-15', { exact: true })
  ).toBeInTheDocument()
})
