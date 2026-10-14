import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, it, vi } from 'vitest'
import { NeoStrategyResearch } from './NeoStrategyResearch'

vi.mock('@/api/neoResearch', () => ({
  neoResearchApi: {
    datasets: async () => [],
    latest: async () => [
      {
        request: { start: '2026-10-14', end: '2026-10-14', expiry: '2026-10-19' },
        result: {
          profile: 'orb_trail',
          closed_count: 0,
          unresolved_count: 1,
          wins: 0,
          known_realized_net: '0',
          coverage: { complete: false },
        },
      },
      {
        result: {
          profile: 'donchian_controls',
          closed_count: 1,
          unresolved_count: 1,
          wins: 1,
          known_realized_net: '1035.65',
          coverage: { complete: false },
        },
      },
    ],
  },
}))
it('distinguishes unresolved entries from zero profit and discloses them alongside resolved profits', async () => {
  render(
    <MemoryRouter>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <NeoStrategyResearch />
      </QueryClientProvider>
    </MemoryRouter>
  )
  expect(await screen.findByText('₹1035.65')).toBeVisible()
  const orb = screen.getByRole('row', { name: /ORB · index trail/ }),
    donchian = screen.getByRole('row', { name: /Donchian · trend/ })
  expect(orb).toHaveTextContent('Unresolved')
  expect(orb).toHaveTextContent('2026-10-14 → 2026-10-14')
  expect(orb).toHaveTextContent('Expiry 2026-10-19')
  expect(orb).not.toHaveTextContent('₹0.00')
  expect(donchian).toHaveTextContent('1 unresolved entry')
})
