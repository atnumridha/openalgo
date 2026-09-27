import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'

const rest = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/client', () => ({ webClient: rest }))

import DailyOptionsHistory from './DailyOptionsHistory'

const archive = {
  status: 'empty',
  session_count: 0,
  start: null,
  end: null,
  processed_dates: 0,
  total_dates: 0,
  unavailable_count: 0,
  error_count: 0,
  option_rows: 0,
  intraday_eligible: false,
}
const response = (data: unknown) => ({ data: { data } })
function show() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false, gcTime: 0 },
            mutations: { retry: false },
          },
        })
      }
    >
      <DailyOptionsHistory />
    </QueryClientProvider>
  )
}
beforeEach(() => {
  rest.get.mockReset()
  rest.post.mockReset()
  rest.get.mockImplementation(async (url: string) =>
    response(url.endsWith('/snapshot') ? { session: null, contracts: [] } : archive)
  )
})

it('starts the official download without asking for an upload and displays progress', async () => {
  const running = { ...archive, status: 'running', total_dates: 2357, processed_dates: 10 }
  rest.post.mockImplementation(async () => {
    rest.get.mockResolvedValue(response(running))
    return response(running)
  })
  show()
  await userEvent.click(await screen.findByRole('button', { name: 'Download NSE history' }))
  expect(await screen.findByText(/10 of 2,357 dates checked/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Downloading…' })).toBeDisabled()
  expect(rest.post).toHaveBeenCalledWith('/strategy/api/research/daily-options', {})
  expect(screen.getByText(/cannot test five-minute entries/)).toBeInTheDocument()
})

it('shows daily coverage and a CSV export without presenting it as an intraday dataset', async () => {
  rest.get.mockResolvedValue(
    response({
      ...archive,
      status: 'completed_with_gaps',
      session_count: 100,
      start: '2026-05-01',
      end: '2026-09-25',
      unavailable_count: 40,
    })
  )
  show()
  expect(await screen.findByText('100 sessions saved')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Download latest NIFTY CSV' })).toHaveAttribute(
    'href',
    '/strategy/api/research/daily-options/export?session=2026-09-25&symbol=NIFTY'
  )
  expect(screen.queryByRole('button', { name: /run.*test/i })).not.toBeInTheDocument()
})

it('keeps download failures visible and permits retry', async () => {
  rest.post.mockRejectedValue(new Error('Network unavailable'))
  show()
  await userEvent.click(await screen.findByRole('button', { name: 'Download NSE history' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(/could not start/i)
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Download NSE history' })).toBeEnabled()
  )
})
