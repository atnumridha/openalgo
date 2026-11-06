import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { neoReportsApi } from '@/api/neoReports'
import { RecordedTradeHistory } from './RecordedTradeHistory'

vi.mock('@/api/neoReports', () => ({
  neoReportsApi: {
    history: vi.fn().mockResolvedValue({
      symbols: [],
      rows: [],
      total: 0,
      open_inventory: [],
      summary: {
        gross_pnl: '650',
        actual_fees: null,
        estimated_fees: '28.4',
        net_pnl: null,
        estimated_net_pnl: '621.60',
        estimated_net_known_count: 1,
        fill_count: 2,
        fees_known_fill_count: 0,
      },
      coverage: { fill_count: 2, recorded_dates: ['2026-10-09'], lifetime_complete: false },
      fee_estimate: {
        breakdown: { brokerage: '20' },
        source: 'estimate',
        storage: 'SQL saved estimate',
        calculated_at: '2026-10-23T08:00:00+05:30',
      },
    }),
  },
}))
beforeEach(() => {
  cleanup()
  localStorage.clear()
  vi.clearAllMocks()
})

it('separates unknown actual fees from estimates and unverified lifetime coverage', async () => {
  vi.stubEnv('VITE_NEO_DESK_ENABLED', 'true')
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <RecordedTradeHistory />
    </QueryClientProvider>
  )
  expect(await screen.findByText('Lifetime completeness unverified')).toBeVisible()
  expect(screen.getByText('Actual fees paid')).toBeVisible()
  expect(screen.getAllByText('Estimated charges')[0]).toBeVisible()
  expect(screen.getByText(/Gross P&L before fees/)).toBeVisible()
  expect(screen.getByText('Not reported by Kotak')).toBeVisible()
  expect(screen.queryByText('Unavailable')).not.toBeInTheDocument()
  expect(neoReportsApi.history).toHaveBeenCalledWith('', '', '', 0, 'account', 'live')
  expect(screen.getByLabelText('Charge estimate plan')).toHaveValue('account')
  expect(screen.getByText('Estimated net P&L · resolved closes')).toBeVisible()
  expect(screen.getByText('₹621.60')).toBeVisible()
  expect(screen.getByText(/Fee estimates saved in local database/)).toBeVisible()
})

it('selects any stored date and keeps Sandbox reports separate from Live', async () => {
  vi.stubEnv('VITE_NEO_DESK_ENABLED', 'true')
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <RecordedTradeHistory />
    </QueryClientProvider>
  )
  await screen.findAllByText('Lifetime completeness unverified')
  fireEvent.change(screen.getAllByLabelText('Report mode').at(-1)!, {
    target: { value: 'sandbox' },
  })
  await waitFor(() =>
    expect(screen.getAllByRole('option', { name: '2026-10-09' }).length).toBeGreaterThan(0)
  )
  fireEvent.change(screen.getAllByLabelText('Recorded date').at(-1)!, {
    target: { value: '2026-10-09' },
  })
  await waitFor(() =>
    expect(neoReportsApi.history).toHaveBeenCalledWith(
      '',
      '2026-10-09',
      '2026-10-09',
      0,
      'account',
      'sandbox'
    )
  )
})

it('does not inherit the old automatic zero-brokerage default', async () => {
  vi.stubEnv('VITE_NEO_DESK_ENABLED', 'true')
  localStorage.setItem('neo.history.costPlan', 'free_offer')
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <RecordedTradeHistory />
    </QueryClientProvider>
  )
  await screen.findByText('Lifetime completeness unverified')
  expect(screen.getByLabelText('Charge estimate plan')).toHaveValue('account')
})

vi.mock('./RecordedTradeReplay', () => ({
  RecordedTradeReplay: () => <div>Saved replay chart fixture</div>,
}))

it('opens a selected trade replay immediately in a visible dialog', async () => {
  vi.stubEnv('VITE_NEO_DESK_ENABLED', 'true')
  vi.mocked(neoReportsApi.history).mockResolvedValueOnce({
    symbols: ['NIFTY13OCT2622500CE'],
    total: 1,
    open_inventory: [],
    rows: [
      {
        trade_id: 'fixture-trade',
        symbol: 'NIFTY13OCT2622500CE',
        quantity: 65,
        entry_time: '2026-10-09T10:00:00+05:30',
        exit_time: '2026-10-09T10:05:00+05:30',
        entry_price: '50',
        exit_price: '60',
        gross_pnl: '650',
        fees: null,
        net_pnl: null,
        status: 'closed',
        estimated_fees: '28.40',
        estimated_net_pnl: '621.60',
      },
    ],
    summary: {
      gross_pnl: '650',
      actual_fees: null,
      estimated_fees: '28.40',
      net_pnl: null,
      fill_count: 2,
      fees_known_fill_count: 0,
    },
    coverage: { fill_count: 2, recorded_dates: ['2026-10-09'], lifetime_complete: false },
    fee_estimate: { breakdown: {}, source: 'estimate' },
  })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <RecordedTradeHistory />
    </QueryClientProvider>
  )
  fireEvent.click(await screen.findByRole('button', { name: /Replay recorded trade/ }))
  expect(await screen.findByRole('dialog', { name: 'Recorded trade replay' })).toBeVisible()
  expect(screen.getByText('Saved replay chart fixture')).toBeVisible()
})
