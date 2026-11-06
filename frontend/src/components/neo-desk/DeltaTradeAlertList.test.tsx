import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { DeltaTradeAlerts } from './DeltaTradeAlertList'
import { publishTradeAlert, readTradeAlerts } from './deltaTradeAlerts'
const mocks = vi.hoisted(() => ({
  success: vi.fn(),
  dismiss: vi.fn(),
  sound: vi.fn(),
  ready: vi.fn(),
}))
vi.mock('sonner', () => ({ toast: { success: mocks.success, dismiss: mocks.dismiss } }))
vi.mock('@/lib/trading/alertDelivery', () => ({
  playAlertSound: mocks.sound,
  readySound: mocks.ready,
}))
beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})
it('restores an undismissed alert quietly, keeps its popup indefinitely and permits manual dismissal', () => {
  publishTradeAlert({
    id: 'a',
    account: 'account',
    symbol: 'BTCUSD',
    title: 'Position exited',
    message: 'Fill verified',
    at: 100,
  })
  mocks.sound.mockClear()
  const view = render(<DeltaTradeAlerts account="account" symbol="BTCUSD" />)
  expect(screen.getByLabelText('Trade alerts')).toHaveTextContent('Position exited')
  expect(mocks.success).toHaveBeenCalledWith(
    'Position exited',
    expect.objectContaining({ duration: Infinity, closeButton: true })
  )
  expect(mocks.sound).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss Position exited' }))
  expect(readTradeAlerts('account', 'BTCUSD')).toEqual([])
  view.unmount()
  render(<DeltaTradeAlerts account="account" symbol="BTCUSD" />)
  expect(screen.queryByLabelText('Trade alerts')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Test / enable sound' }))
  expect(mocks.ready).toHaveBeenCalledOnce()
  expect(mocks.sound).toHaveBeenCalledOnce()
})
