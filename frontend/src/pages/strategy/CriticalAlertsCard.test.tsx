import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, it, vi } from 'vitest'

const strategyApi = vi.hoisted(() => ({
  getCriticalAlerts: vi.fn(),
  strategyQueryKeys: {
    criticalAlerts: () => ['strategy-module', 'automation', 'critical-alerts'],
  },
}))

vi.mock('@/api/strategy_module', () => strategyApi)

import CriticalAlertsCard from './CriticalAlertsCard'

beforeEach(() => strategyApi.getCriticalAlerts.mockReset())

it('keeps a failed alert from a deleted strategy visible with original time', async () => {
  strategyApi.getCriticalAlerts.mockResolvedValue([{
    id: 8,
    source_key: 'strategy:42:2026-09-25T04:00:00',
    source_id: 42,
    strategy_id: 7,
    user_id: 'owner',
    event_ts: '2026-09-25T04:00:00+00:00',
    kind: 'protective_stop_uncovered',
    severity: 'critical',
    message: 'Uncovered position',
    run_id: 2,
    status: 'failed',
    attempts: 5,
    last_attempt_at: '2026-09-25T04:05:00+00:00',
    accepted_at: null,
    expires_at: '2026-09-25T16:00:00+00:00',
    last_error: 'WhatsApp did not accept the alert',
  }])
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <CriticalAlertsCard savedStrategyIds={new Set()} />
      </MemoryRouter>
    </QueryClientProvider>
  )
  expect(await screen.findByText('Uncovered position')).toBeInTheDocument()
  expect(screen.getByText('Deleted strategy #7')).toBeInTheDocument()
  expect(screen.getByText('WhatsApp failed')).toBeInTheDocument()
  expect(screen.getByText(/Original event:/)).toBeInTheDocument()
  expect(screen.getByText(/Last attempt:/)).toBeInTheDocument()
  expect(screen.getByText(/upstream acceptance is not human receipt/i)).toBeInTheDocument()
})

it('keeps failures visible while collapsing older accepted alerts', async () => {
  strategyApi.getCriticalAlerts.mockResolvedValue([
    ...Array.from({ length: 5 }, (_, index) => ({
      id: index + 1,
      strategy_id: null,
      status: 'sent',
      kind: 'routine',
      message: `Accepted alert ${index + 1}`,
      event_ts: '2026-09-25T04:00:00+00:00',
      last_attempt_at: null,
      last_error: null,
    })),
    {
      id: 6,
      strategy_id: null,
      status: 'failed',
      kind: 'broker_disconnected',
      message: 'Important delivery failure',
      event_ts: '2026-09-25T04:00:00+00:00',
      last_attempt_at: null,
      last_error: 'Provider rejected the message',
    },
  ])
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <CriticalAlertsCard savedStrategyIds={new Set()} />
      </MemoryRouter>
    </QueryClientProvider>
  )

  expect(await screen.findByText('Important delivery failure')).toBeVisible()
  expect(screen.getByText('Accepted alert 1')).toBeVisible()
  expect(screen.queryByText('Accepted alert 5')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /show all 6 alerts/i }))
  expect(screen.getByText('Accepted alert 5')).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: /show fewer alerts/i }))
  expect(screen.queryByText('Accepted alert 5')).not.toBeInTheDocument()
})
