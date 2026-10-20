import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { kotakAssistantApi, type Snapshot } from '@/api/kotakAssistant'
import { OtherPositions } from './OtherPositions'
vi.mock('@/api/kotakAssistant', () => ({
  kotakAssistantApi: { adopt: vi.fn(() => Promise.resolve({})) },
}))
it('direct exit does not require or submit blank SL or target', async () => {
  const desk = {
    mode: 'live',
    settings: { cutoff: '15:15' },
    trades: [],
    positions: [
      {
        symbol: 'NIFTYCE',
        exchange: 'NFO',
        product: 'MIS',
        quantity: 65,
        average_price: 100,
        ltp: 100,
      },
    ],
    orders: [],
  } as unknown as Snapshot
  render(<OtherPositions desk={desk} refresh={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Exit full' }))
  await waitFor(() => expect(kotakAssistantApi.adopt).toHaveBeenCalled())
  const payload = vi.mocked(kotakAssistantApi.adopt).mock.calls[0][1]
  expect(payload.close).toBe(true)
  expect('sl' in payload).toBe(false)
  expect('target' in payload).toBe(false)
})
