import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import type { Trade } from '@/api/kotakAssistant'
import { TradeTracking } from './TradeTracking'

it('shows saved terminal lifecycle and broker IDs, including closed trades', () => {
  const trade = {
    id: 'saved-id',
    symbol: 'NIFTY19OCT2622600CE',
    mode: 'live',
    created: 1792038600,
    status: 'closed',
    remaining: 0,
    entry_quantity: 65,
    reason: 'Broker confirmed flat',
    ops: [{ role: 'entry', orderid: 'broker-123', state: 'accepted' }],
    lifecycle: [
      {
        at: 1792038600,
        status: 'entry_pending',
        reason: 'Awaiting fills',
        filled: 0,
        remaining: 0,
        orders: [],
      },
      {
        at: 1792038700,
        status: 'closed',
        reason: 'Broker confirmed flat',
        filled: 65,
        remaining: 0,
        orders: [],
      },
    ],
  } as unknown as Trade
  render(<TradeTracking trades={[trade]} mode="live" />)
  expect(screen.getByText('NIFTY19OCT2622600CE')).toBeInTheDocument()
  expect(screen.getByText(/broker-123/)).toBeInTheDocument()
  expect(screen.getByText(/saved-id/)).toBeInTheDocument()
  expect(screen.getByText('entry pending').closest('li')).toHaveTextContent('Awaiting fills')
  expect(screen.getByText('closed', { exact: true }).closest('li')).toHaveTextContent(
    '65 filled / 0 remaining'
  )
})

it('does not present Paper records as Live tracking', () => {
  const paper = { id: 'paper', symbol: 'PAPERCE', mode: 'analyze' } as Trade
  render(<TradeTracking trades={[paper]} mode="live" />)
  expect(screen.queryByText('PAPERCE')).not.toBeInTheDocument()
  expect(screen.getByText(/No terminal trades recorded/)).toBeInTheDocument()
})

it('does not imply that a definitively rejected submission is waiting for a broker ID', () => {
  const rejected = {
    id: 'rejected-id',
    symbol: 'NIFTY19OCT2623150CE',
    mode: 'live',
    created: 1792042650,
    status: 'rejected',
    entry_quantity: 0,
    remaining: 0,
    reason: 'Kotak rejected order: unauthorized (HTTP 401 · code 100008).',
    ops: [{ role: 'entry', state: 'rejected', orderid: null }],
    lifecycle: [],
  } as unknown as Trade
  render(<TradeTracking trades={[rejected]} mode="live" />)
  expect(screen.getByText(/Broker orders:/)).toHaveTextContent('No broker ID returned')
  expect(screen.getByText(/Broker orders:/)).not.toHaveTextContent('awaiting ID')
  expect(screen.getByText(/Kotak rejected order:/)).toHaveTextContent('100008')
})
