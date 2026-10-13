import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { it, expect, vi } from 'vitest'
import { MarketOverview } from './MarketOverview'
vi.mock('@/api/neoOverview', () => ({
  neoOverviewApi: {
    overview: vi
      .fn()
      .mockResolvedValue({
        price: '22500',
        change: null,
        change_pct: null,
        rsi14: null,
        advances: 2,
        declines: 1,
        unchanged: 1,
        covered: 4,
        missing: 46,
        market_session: 'closed',
        observed_at: '2026-10-13T18:00:00+05:30',
        source: 'broker',
        errors: ['Constituent quotes partial'],
        timestamp_note: 'Exchange timestamp unavailable',
      }),
  },
}))
it('shows partial breadth and immediate errors without inventing RSI or price change', async () => {
  vi.stubEnv('VITE_NEO_DESK_ENABLED', 'true')
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MarketOverview />
    </QueryClientProvider>
  )
  expect(await screen.findByText(/4 \/ 50/)).toBeVisible()
  expect(screen.getByRole('alert')).toHaveTextContent('Constituent quotes partial')
  expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0)
})
