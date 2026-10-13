import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { it, expect, vi } from 'vitest'
import { RecordedTradeHistory } from './RecordedTradeHistory'
import { neoReportsApi } from '@/api/neoReports'
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
        fill_count: 2,
        fees_known_fill_count: 0,
      },
      coverage: { fill_count: 2, recorded_dates: ['2026-10-09'], lifetime_complete: false },
      fee_estimate: { breakdown: { brokerage: '20' }, source: 'estimate' },
    }),
  },
}))
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
  expect(neoReportsApi.history).toHaveBeenCalledWith('', '', '', 0, 'free_offer')
  expect(screen.getByLabelText('Charge estimate plan')).toBeVisible()
})
