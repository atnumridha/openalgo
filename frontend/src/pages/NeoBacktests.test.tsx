import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { neoResearchApi } from '@/api/neoResearch'
import NeoBacktests from './NeoBacktests'

vi.mock('@/components/neo-desk/ReplayChart', () => ({
  ReplayChart: ({ trade, source }: { trade: { symbol: string }; source: string }) => (
    <output>
      {source}: {trade.symbol}
    </output>
  ),
}))
beforeEach(() => localStorage.clear())

vi.mock('@/api/neoResearch', () => ({
  neoResearchApi: {
    job: vi.fn(),
    saved: vi.fn().mockResolvedValue([]),
    datasets: vi.fn().mockResolvedValue([
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

it('reopens the selected saved preset and each of its trades without rerunning', async () => {
  vi.mocked(neoResearchApi.saved).mockResolvedValue([
    {
      id: 'saved-orb',
      status: 'complete',
      request: {
        profile: 'orb_controls',
        start: '2026-10-14',
        end: '2026-10-14',
        expiry: '2026-10-19',
      },
    },
  ])
  vi.mocked(neoResearchApi.job).mockResolvedValue({
    id: 'saved-orb',
    status: 'complete',
    error: null,
    request: {
      profile: 'orb_controls',
      start: '2026-10-14',
      end: '2026-10-14',
      expiry: '2026-10-19',
    },
    result: {
      profile: 'orb_controls',
      known_realized_net: '10',
      net_complete: null,
      fees_estimate: '5',
      drawdown: '0',
      wins: 1,
      closed_count: 2,
      unresolved_count: 0,
      coverage: { complete: false, gaps: [] },
      assumptions: [],
      trades: [
        { symbol: 'first PE', entry_time: '2026-10-14T10:00:00+05:30', status: 'closed' },
        { symbol: 'second CE', entry_time: '2026-10-14T11:00:00+05:30', status: 'closed' },
      ] as never,
    },
  })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NeoBacktests />
    </QueryClientProvider>
  )
  expect(
    await screen.findByText(
      'Backtested orb_controls · modelled fills · preserved observations: first PE'
    )
  ).toBeVisible()
  const buttons = screen.getAllByRole('button', { name: 'Replay trade' })
  fireEvent.click(buttons[1])
  expect(
    screen.getByText('Backtested orb_controls · modelled fills · preserved observations: second CE')
  ).toBeVisible()
  await waitFor(() => expect(localStorage.getItem('neo.replay.savedJob.v1')).toBe('saved-orb'))
  expect(localStorage.getItem('neo.replay.selectedTrade.v1')).toBe('1')
  expect(neoResearchApi.job).toHaveBeenCalledWith('saved-orb')
})
