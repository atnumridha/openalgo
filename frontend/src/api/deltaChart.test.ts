import { expect, it, vi } from 'vitest'
import { webClient } from './client'
import { deltaChartApi, type DeltaChartAction } from './deltaChart'
vi.mock('./client', () => ({ webClient: { get: vi.fn(), post: vi.fn() } }))
it('surfaces an explicit broker rejection even when HTTP reports conflict', async () => {
  const body: DeltaChartAction = {
    request_id: 'rid',
    symbol: 'BTCUSD',
    account: 'a',
    action: 'close',
    position_version: 'pv',
  }
  const result = { request_id: 'rid', status: 'rejected', message: 'Position changed' }
  vi.mocked(webClient.post).mockRejectedValue({
    isAxiosError: true,
    response: { status: 409, data: result },
  })
  await expect(deltaChartApi.action(body)).resolves.toEqual(result)
})
it('keeps a transport failure uncertain rather than calling it rejected', async () => {
  const error = new Error('timeout')
  vi.mocked(webClient.post).mockRejectedValue(error)
  await expect(
    deltaChartApi.action({ request_id: 'rid', symbol: 'BTCUSD', account: 'a', action: 'entry' })
  ).rejects.toBe(error)
})
