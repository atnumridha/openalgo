import { fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@/test/test-utils'
import type { Position } from '@/types/trading'
import { DeltaProfitProtection } from './DeltaProfitProtection'

const mocks = vi.hoisted(() => ({
  status: vi.fn(),
  preview: vi.fn(),
  enable: vi.fn(),
  pause: vi.fn(),
}))
vi.mock('@/api/deltaProfitProtection', () => ({ deltaProfitApi: mocks }))
const onPlans = vi.fn()
const position = {
  symbol: 'BTCUSDFUT',
  exchange: 'CRYPTO',
  quantity: -15,
  average_price: 1000,
} as Position
const plan = {
  symbol: 'BTCUSDFUT',
  side: -1,
  quantity: -15,
  entry: 1000,
  stop: 1100,
  target: 700,
  gap: 50,
  initial_stop: 1100,
  reward_multiple: 3,
  tick: 1,
  opened_at: 'known',
  stop_id: '1',
  eligible: true,
  exit_at: 1740,
  window_end: 1800,
  preview_id: 'preview',
  enabled: false,
  state: 'watching',
}
const mount = () =>
  render(
    <DeltaProfitProtection
      positions={[position]}
      now={100000}
      visible={false}
      scope="test"
      onPlans={onPlans}
    />
  )
beforeEach(() => {
  vi.clearAllMocks()
  mocks.status.mockResolvedValue({ plans: [], heartbeat: 100 })
  mocks.preview.mockResolvedValue(plan)
  mocks.enable.mockResolvedValue({ ...plan, enabled: true })
  mocks.pause.mockResolvedValue({})
})
describe('Delta profit protection', () => {
  it('never enables protection from mount, a quote refresh, or preview', async () => {
    mount()
    await screen.findByText('Server monitor ready · 1-second snapshots')
    expect(mocks.enable).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Preview protection' }))
    await screen.findByRole('button', { name: 'Enable live profit protection' })
    expect(mocks.preview).toHaveBeenCalledWith({
      symbol: 'BTCUSDFUT',
      mode: 'live',
      reward_multiple: 3,
      trailing_mode: 'net_usd',
      profit_arm_usd: 2,
      profit_lock_usd: 1.5,
      profit_gap_usd: 0.5,
    })
    expect(mocks.enable).not.toHaveBeenCalled()
    expect(screen.getByText(/checks begin in 27:20/)).toBeInTheDocument()
  })
  it('requires the displayed preview and explicit enable action', async () => {
    mount()
    await screen.findByText('Server monitor ready · 1-second snapshots')
    fireEvent.click(screen.getByRole('button', { name: 'Preview protection' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Enable live profit protection' }))
    await waitFor(() =>
      expect(mocks.enable).toHaveBeenCalledWith({
        symbol: 'BTCUSDFUT',
        mode: 'live',
        reward_multiple: 3,
        trailing_mode: 'net_usd',
        profit_arm_usd: 2,
        profit_lock_usd: 1.5,
        profit_gap_usd: 0.5,
        preview_id: 'preview',
      })
    )
  })
  it('invalidates the preview when the trailing gap changes', async () => {
    mount()
    fireEvent.click(screen.getByRole('button', { name: 'Preview protection' }))
    await screen.findByRole('button', { name: 'Enable live profit protection' })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Net profit trailing gap USD' }), {
      target: { value: '30' },
    })
    expect(
      screen.queryByRole('button', { name: 'Enable live profit protection' })
    ).not.toBeInTheDocument()
    expect(mocks.enable).not.toHaveBeenCalled()
  })
  it('does not enable against an unavailable monitor heartbeat', async () => {
    mocks.status.mockResolvedValue({ plans: [], heartbeat: 0 })
    mount()
    fireEvent.click(screen.getByRole('button', { name: 'Preview protection' }))
    expect(
      await screen.findByRole('button', { name: 'Enable live profit protection' })
    ).toBeDisabled()
  })
  it('pauses automation without a cancel-order action', async () => {
    mocks.status.mockResolvedValue({
      plans: [{ ...plan, enabled: true, message: 'Watching' }],
      heartbeat: 100,
    })
    mount()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Pause automation · keep broker orders' })
    )
    await waitFor(() => expect(mocks.pause).toHaveBeenCalledWith('BTCUSDFUT'))
    expect(mocks.enable).not.toHaveBeenCalled()
  })
})
