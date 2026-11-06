import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { TradeGuide } from './TradeGuide'
import { optionRiskApi } from './optionRiskApi'
import type { GuideBrokerContext, GuidePlan } from './tradeGuidance'
vi.mock('./optionRiskApi', () => ({ optionRiskApi: { preview: vi.fn() } }))
const now = Date.now() / 1000
const plan: GuidePlan = { entry: 100, stop: 95, target: 110, side: 'buy', asOf: now - 60, label: 'Chart plan', protection: 'planned' }
const base = { symbol: 'NIFTY03NOV2623600PE', exchange: 'NFO', interval: '1m', seconds: 60, live: true,
  current: { direction: 'up' as const, time: now - 60, reason: 'Premium is rising.' }, higher: null,
  plan, quote: { price: 100, time: now }, tick: 0.05, lotSize: 65 }
function view(props: Partial<React.ComponentProps<typeof TradeGuide>> = {}) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><TradeGuide {...base} {...props} /></QueryClientProvider>
}
beforeEach(() => { localStorage.clear(); vi.mocked(optionRiskApi.preview).mockReset() })

it('keeps the guide collapsible and has no order action', () => {
  render(view())
  expect(screen.getByRole('group', { name: 'Trade guide' })).toBeInTheDocument()
  fireEvent.click(screen.getByText('Trade guide'))
  expect(screen.queryByLabelText('Planning lots')).not.toBeVisible()
  expect(screen.queryByRole('button', { name: /place|buy|sell|close/i })).not.toBeInTheDocument()
})
it('keeps bought PE risk below premium entry and explicitly scopes Flattrade fees', async () => {
  vi.mocked(optionRiskApi.preview).mockImplementation(async (body) => ({ ...body, broker: body.broker,
    quantity: 65 * body.lots, lot_size: 65, net_profit: '640.00', net_loss: '335.00', profit_fees: '10.00', loss_fees: '10.00',
    fee_source: 'Flattrade calculator', fee_date: new Date().toISOString().slice(0, 10) } as never))
  render(view())
  fireEvent.change(screen.getByLabelText('Planning fee profile'), { target: { value: 'flattrade' } })
  await waitFor(() => expect(optionRiskApi.preview).toHaveBeenCalledWith(expect.objectContaining({ broker: 'flattrade', stop: '95', target: '110' }), expect.anything()))
  expect(await screen.findByLabelText('Guide net at SL')).toHaveTextContent('335.00')
  expect(screen.getByText(/Bought PE/)).toBeInTheDocument()
  expect(screen.getByText(/Recent trade history unavailable/)).toBeInTheDocument()
})
it('does not substitute available cash for a verified account balance', () => {
  const context: GuideBrokerContext = { symbol: base.symbol, exchange: 'NFO', broker: 'flattrade', asOf: now, quantity: 65, lotSize: 65, plan, quote: base.quote, historyVerified: false }
  render(view({ context }))
  expect(screen.getByText(/Account balance unavailable/)).toBeInTheDocument()
  expect(screen.queryByLabelText('Guide balance risk')).not.toBeInTheDocument()
})
it('does not request a current fee estimate for replay', () => {
  render(view({ live: false }))
  expect(screen.getByText('Historical review')).toBeInTheDocument()
  expect(optionRiskApi.preview).not.toHaveBeenCalled()
})

it('does not fetch a new plan using a stale selected broker snapshot', () => {
  const context: GuideBrokerContext = { symbol: base.symbol, exchange: 'NFO', broker: 'flattrade', asOf: now - 60, quantity: 130, lotSize: 65, plan, quote: base.quote, historyVerified: true }
  render(view({ context }))
  expect(screen.getByText(/Broker snapshot is old/)).toBeInTheDocument()
  expect(optionRiskApi.preview).not.toHaveBeenCalled()
})


it('does not replace an unavailable broker position basis with a chart planning estimate', () => {
  const context: GuideBrokerContext = { symbol: base.symbol, exchange: 'NFO', broker: 'flattrade', asOf: now, quantity: 65, lotSize: 65, plan: null, quote: base.quote, historyVerified: true }
  render(view({ context }))
  expect(screen.getByText(/Plan unavailable/)).toBeInTheDocument()
  expect(optionRiskApi.preview).not.toHaveBeenCalled()
})


it('names the short side explicitly when the chart and separate planning setup differ', () => {
  const context: GuideBrokerContext = { symbol: 'BTCUSD', exchange: 'DELTA', broker: 'delta', asOf: now, quantity: 4, lotSize: null,
    plan: { ...plan, side: 'sell', stop: 105, target: 90, label: 'Auto timeframe plan' }, quote: base.quote, historyVerified: false }
  render(view({ symbol: 'BTCUSD', exchange: 'DELTA', context }))
  expect(screen.getByText('Short · Auto timeframe plan · planning only')).toBeInTheDocument()
})
