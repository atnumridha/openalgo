import { expect, it, vi } from 'vitest'
import { scalpingApi } from './scalping'
import { webClient } from './client'
vi.mock('./client', () => ({
  webClient: { get: vi.fn(async () => ({ data: { status: 'success', chain: [] } })) },
}))
it('requests premium quotes only when explicitly requested by a configuration preview', async () => {
  await scalpingApi.getStrikes('NIFTY', 'NFO', '03NOV26', 20, { quotes: true })
  expect(webClient.get).toHaveBeenLastCalledWith('/scalping/api/strikes', {
    params: {
      underlying: 'NIFTY',
      exchange: 'NFO',
      expiry: '03NOV26',
      strike_count: 20,
      quotes: true,
    },
  })
  await scalpingApi.getStrikes('NIFTY', 'NFO', '03NOV26', 20)
  expect(webClient.get).toHaveBeenLastCalledWith('/scalping/api/strikes', {
    params: { underlying: 'NIFTY', exchange: 'NFO', expiry: '03NOV26', strike_count: 20 },
  })
})
