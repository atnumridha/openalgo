import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { it, expect, vi } from 'vitest'
import NeoBacktests from './NeoBacktests'
vi.mock('@/api/neoResearch', () => ({
  neoResearchApi: {
    datasets: vi
      .fn()
      .mockResolvedValue([
        {
          id: 'actual',
          start: '2026-09-10',
          end: '2026-10-09',
          expiries: ['2026-10-13'],
          source: { name: 'Actual Kotak observations' },
          gaps: ['Only one expiry; missing minutes'],
        },
      ]),
  },
}))
it('shows actual coverage and does not imply that one-year selection creates missing data', async () => {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoBacktests />
    </QueryClientProvider>
  )
  expect(await screen.findByText('Actual Kotak observations')).toBeVisible()
  expect(screen.getByText(/Only one expiry/)).toBeVisible()
  expect(screen.getByLabelText('Reinvest profits within the two-lot maximum')).toBeVisible()
  expect(screen.getByText(/up to one year/)).toBeVisible()
  expect(screen.queryByText('Guaranteed profit')).toBeNull()
})
