import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { SavedCharts } from './SavedCharts'

vi.mock('@/api/neoReports', () => ({
  neoReportsApi: {
    storage: async () => ({
      backend: 'SQL · SQLite',
      live_fills: 4,
      paper_fills: 2,
      history_events: 20,
      last_backup: '2026-10-14T15:00:00+05:30',
      charts: [
        {
          symbol: 'NIFTY',
          exchange: 'NSE_INDEX',
          interval: '15m',
          start: '2025-10-14',
          end: '2026-10-14',
          count: 6300,
        },
      ],
    }),
  },
}))
vi.mock('./NeoMarketChart', () => ({
  NeoMarketChart: ({ savedRange }: { savedRange: { start: string; end: string } }) => (
    <div role="img" aria-label="Saved TradingView chart">
      {savedRange.start} to {savedRange.end}
    </div>
  ),
}))

it('opens a date-filtered SQL chart and identifies the retention and backup status', async () => {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SavedCharts />
    </QueryClientProvider>
  )
  expect(await screen.findByText(/6,300/)).toBeVisible()
  fireEvent.change(screen.getByLabelText('Chart from'), { target: { value: '2025-11-03' } })
  fireEvent.change(screen.getByLabelText('Chart through'), { target: { value: '2025-11-03' } })
  fireEvent.click(screen.getByRole('button', { name: 'Load saved chart' }))
  expect(screen.getByRole('img', { name: 'Saved TradingView chart' })).toHaveTextContent(
    '2025-11-03 to 2025-11-03'
  )
  expect(screen.getByText(/Last verified backup/)).toBeVisible()
})
