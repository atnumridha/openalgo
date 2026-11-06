import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { DeltaOrderNotice } from './DeltaOrderNotice'
const popups = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
  loading: vi.fn(),
  dismiss: vi.fn(),
}))
vi.mock('sonner', () => ({ toast: popups }))
beforeEach(() => vi.clearAllMocks())
it('shows a persistent red failure with its reason and a popup', () => {
  render(<DeltaOrderNotice notice="Order not sent: Price is moving sideways." />)
  expect(screen.getByRole('alert')).toHaveTextContent('Order not placed')
  expect(screen.getByRole('alert')).toHaveTextContent('Price is moving sideways.')
  expect(popups.error).toHaveBeenCalledWith(
    'Order not placed',
    expect.objectContaining({
      description: 'Order not sent: Price is moving sideways.',
      duration: Infinity,
    })
  )
})
it('shows accepted only after explicit acknowledgement and never labels it filled', () => {
  render(
    <DeltaOrderNotice notice="Broker accepted. Broker acknowledgement, not a fill. Check position and fills." />
  )
  expect(screen.getByRole('status')).toHaveTextContent('Order accepted')
  expect(screen.getByRole('status')).toHaveTextContent('not a fill')
  expect(popups.success).toHaveBeenCalledOnce()
})
it('keeps uncertainty amber, never reports not placed and does not suggest retry', () => {
  render(
    <DeltaOrderNotice notice="Outcome unknown. Do not resubmit. Check broker orders. Request abc" />
  )
  expect(screen.getByRole('status')).toHaveTextContent('Confirmation pending')
  expect(screen.queryByText('Order accepted')).not.toBeInTheDocument()
  expect(screen.queryByText('Order not placed')).not.toBeInTheDocument()
  expect(popups.warning).toHaveBeenCalledWith(
    'Confirmation pending',
    expect.objectContaining({ duration: Infinity })
  )
})
it('replaces the checking popup with a result using the same id and cleans up on unmount', () => {
  const v = render(<DeltaOrderNotice notice="Checking current broker data and best maker price…" />)
  const id = popups.loading.mock.calls[0][1].id
  v.rerender(<DeltaOrderNotice notice="Rejected: insufficient balance" />)
  expect(popups.error.mock.calls[0][1].id).toBe(id)
  v.unmount()
  expect(popups.dismiss).toHaveBeenCalledWith(id)
})
it('removes the pending popup when the typed order alert owns the accepted event', () => {
  const view = render(
    <DeltaOrderNotice notice="Checking current broker data and best maker price…" quietSuccess />
  )
  const id = popups.loading.mock.calls[0][1].id
  view.rerender(
    <DeltaOrderNotice notice="Accepted. Broker acknowledgement, not a fill." quietSuccess />
  )
  expect(popups.dismiss).toHaveBeenCalledWith(id)
  expect(popups.success).not.toHaveBeenCalled()
})
