import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import type { MonitorStrategy } from '@/api/automation_monitor'
import CandleProgress from './CandleProgress'

const logs = vi.hoisted(() => vi.fn())
vi.mock('@/api/automation_monitor', () => ({ getAutomationLogs: logs }))
const now = Date.now()
const row = {
  id: 26,
  mode: 'sandbox',
  configuration: { profile: 'receiver_momentum' },
} as MonitorStrategy
const event = (candles = 7, mode = 'sandbox') => ({
  id: 100,
  kind: 'signal_evaluation',
  at: new Date(now - 120000).toISOString(),
  details: {
    mode,
    profile: 'receiver_momentum',
    reason: 'Collecting ten contiguous completed five-minute candles',
    history: [
      {
        symbol: 'CRUDEOILM19OCT26FUT',
        interval: '5m',
        candles,
        last_bar_at: new Date(now - 120000).toISOString(),
      },
    ],
  },
})
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  render(
    <QueryClientProvider client={client}>
      <CandleProgress row={row} clock={now} />
    </QueryClientProvider>
  )
  return client
}
beforeEach(() => vi.clearAllMocks())
it('retains the last recorded candle assessment between scheduler checks and refreshes progress', async () => {
  logs.mockResolvedValue({
    items: [
      {
        id: 101,
        kind: 'signal_evaluation',
        at: new Date(now).toISOString(),
        details: {
          mode: 'sandbox',
          profile: 'receiver_momentum',
          history: [],
          reason: 'Signal expired; waiting for the next receiver candle',
        },
      },
      event(),
    ],
  })
  const client = setup()
  await screen.findByText(/7 \/ 10 completed candles/)
  expect(screen.getByText(/Last recorded candle assessment/)).toBeInTheDocument()
  expect(screen.getByText(/Counts alone do not confirm/)).toBeInTheDocument()
  logs.mockResolvedValue({ items: [event(8)] })
  await client.invalidateQueries({ queryKey: ['automation-candle-progress'] })
  await waitFor(() => expect(screen.getByText(/8 \/ 10 completed candles/)).toBeInTheDocument())
})
it('does not mix live evidence into a sandbox assessment', async () => {
  logs.mockResolvedValue({ items: [event(10, 'live')] })
  setup()
  await screen.findByText(/No candle assessment recorded in the latest events for this mode/)
  expect(screen.queryByText(/10 \/ 10/)).not.toBeInTheDocument()
})
it('labels stale evidence instead of presenting it as current readiness', async () => {
  logs.mockResolvedValue({ items: [{ ...event(), at: new Date(now - 900000).toISOString() }] })
  setup()
  await screen.findByText(/Historical assessment — more than 6 minutes old/)
})
it('reports unavailable evidence when the log request fails', async () => {
  logs.mockRejectedValue(new Error('unavailable'))
  setup()
  await screen.findByRole('alert')
  expect(screen.getByRole('alert')).toHaveTextContent('Candle assessment unavailable')
})
