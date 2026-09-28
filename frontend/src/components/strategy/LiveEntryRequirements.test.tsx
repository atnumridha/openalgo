import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'

const rest = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('@/api/client', () => ({ webClient: rest }))

import LiveEntryRequirements from './LiveEntryRequirements'

const policy = { research_required: true, revision: 0, updated_at: null, reason: null }
beforeEach(() => vi.clearAllMocks())
function show(value: typeof policy | undefined = policy) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}
    >
      <LiveEntryRequirements policy={value} />
    </QueryClientProvider>
  )
}

it('requires a reason and acknowledgement before saving optional research without starting live', async () => {
  rest.post.mockResolvedValue({
    data: { data: { ...policy, research_required: false, revision: 1 } },
  })
  show()
  const save = screen.getByRole('button', { name: 'Save entry requirement' })
  expect(save).toBeDisabled()
  await userEvent.selectOptions(screen.getByLabelText('Research qualification'), 'optional')
  expect(save).toBeDisabled()
  await userEvent.type(
    screen.getByLabelText('Review reason'),
    'Reviewed discretionary research requirement'
  )
  expect(save).toBeDisabled()
  await userEvent.click(screen.getByRole('checkbox', { name: /does not start live trading/ }))
  await userEvent.click(save)
  await waitFor(() => expect(rest.post).toHaveBeenCalledTimes(1))
  expect(rest.post).toHaveBeenCalledWith('/strategy/api/risk/live-entry-policy', {
    research_required: false,
    expected_revision: 0,
    reason: 'Reviewed discretionary research requirement',
    confirm: true,
  })
  expect(await screen.findByRole('status')).toHaveTextContent('Live trading has not been started')
})

it('keeps a failed save visible and never claims it changed the saved requirement', async () => {
  rest.post.mockRejectedValue(new Error('Live positions must be closed first'))
  show()
  await userEvent.selectOptions(screen.getByLabelText('Research qualification'), 'optional')
  await userEvent.type(screen.getByLabelText('Review reason'), 'Reviewed setting')
  await userEvent.click(screen.getByRole('checkbox', { name: /does not start live trading/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Save entry requirement' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Live positions must be closed first')
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(screen.getByText('Currently required')).toBeInTheDocument()
})

it('cannot edit a setting whose current value is unavailable', () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <LiveEntryRequirements />
    </QueryClientProvider>
  )
  expect(screen.getByLabelText('Research qualification')).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Save entry requirement' })).toBeDisabled()
  expect(rest.post).not.toHaveBeenCalled()
})
