import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { neoReportsApi } from '@/api/neoReports'
import { TodayTradeReplays } from './TodayTradeReplays'

vi.mock('@/api/neoReports', () => ({ neoReportsApi: { history: vi.fn() } }))
vi.mock('./RecordedTradeReplay', () => ({
  RecordedTradeReplay: ({ tradeId, mode }: { tradeId: string; mode: string }) => (
    <output>
      {mode} replay {tradeId}
    </output>
  ),
}))
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(neoReportsApi.history).mockResolvedValue({
    total: 2,
    summary: { fill_count: 4 },
    rows: [
      {
        trade_id: 'first',
        symbol: 'NIFTY19OCT2622200PE',
        entry_time: '2026-10-14T10:00:12+05:30',
        exit_time: '2026-10-14T10:02:12+05:30',
        entry_price: '50',
        exit_price: '60',
        quantity: 65,
        status: 'closed',
        gross_pnl: '650',
      },
      {
        trade_id: 'second',
        symbol: 'NIFTY19OCT2622250CE',
        entry_time: '2026-10-14T11:00:12+05:30',
        exit_time: '2026-10-14T11:02:12+05:30',
        entry_price: '50',
        exit_price: '45',
        quantity: 65,
        status: 'closed',
        gross_pnl: '-325',
      },
    ],
  } as never)
})
it('opens each actual trade and keeps Sandbox and Live replays separate', async () => {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <TodayTradeReplays />
    </QueryClientProvider>
  )
  const buttons = await screen.findAllByRole('button', { name: /Replay today's trade/ })
  fireEvent.click(buttons[0])
  expect(screen.getByText('live replay first')).toBeVisible()
  fireEvent.click(buttons[1])
  expect(screen.getByText('live replay second')).toBeVisible()
  fireEvent.change(screen.getByLabelText('Trade mode'), { target: { value: 'sandbox' } })
  await waitFor(() =>
    expect(neoReportsApi.history).toHaveBeenLastCalledWith(
      '',
      expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      expect.any(String),
      0,
      'free_offer',
      'sandbox'
    )
  )
  expect(screen.queryByText('live replay second')).toBeNull()
})
