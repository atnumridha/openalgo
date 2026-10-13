import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { neoDeskApi } from '@/api/neoDesk'
import { NeoStrategyControls } from './NeoStrategyControls'

vi.mock('@/api/neoDesk', () => ({
  neoDeskApi: { state: vi.fn(), command: vi.fn(), settings: vi.fn() },
}))
const data = {
  profile: 'orb_trail',
  activation: 'Stopped',
  mode: 'sandbox',
  status: 'Waiting for a confirmed setup',
  can_edit: true,
  run_id: null,
  entries_today: 0,
  day_net_estimate: '0',
  protection: {},
  presets: [
    { profile: 'orb_trail', label: 'ORB index trail' },
    { profile: 'price_retest', label: 'Price Retest research' },
  ],
  runner: { running: false },
}
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
      }
    >
      <NeoStrategyControls />
    </QueryClientProvider>
  )
}
describe('native preset controls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubEnv('VITE_NEO_DESK_ENABLED','true')
    vi.mocked(neoDeskApi.state).mockResolvedValue(data)
  })
  it('shows one selected preset, the entry window and explicit Sandbox start', async () => {
    mount()
    expect(await screen.findByRole('button', { name: 'Start Sandbox' })).toBeVisible()
    expect(screen.getByText(/15:15/)).toBeVisible()
    expect(screen.getByText(/15:29/)).toBeVisible()
    expect(screen.queryByLabelText(/budget/i)).toBeNull()
  })
  it('submits one start command and waits for authoritative confirmation', async () => {
    let finish: (v: typeof data) => void = () => {}
    vi.mocked(neoDeskApi.command).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
    mount()
    const start = await screen.findByRole('button', { name: 'Start Sandbox' })
    fireEvent.click(start)
    fireEvent.click(start)
    await waitFor(() => expect(neoDeskApi.command).toHaveBeenCalledTimes(1))
    finish({ ...data, activation: 'Active' })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Stop entries' })).toBeEnabled())
  })
  it('displays command refusal immediately without reporting Active', async () => {
    vi.mocked(neoDeskApi.command).mockRejectedValue(
      new Error('Master data unavailable. Refresh instruments.')
    )
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Start Sandbox' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Master data unavailable')
    expect(screen.getByRole('button', { name: 'Start Sandbox' })).toBeEnabled()
  })
})
