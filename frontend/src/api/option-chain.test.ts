import { expect, it, vi } from 'vitest'
import { apiClient } from './client'
import { optionChainApi } from './option-chain'
vi.mock('./client', () => ({ apiClient: { post: vi.fn(async () => ({ data: {status:'success',chain:[]} })) } }))
it('requests the entire chain with explicit null while preserving the default bounded request', async () => {
  await optionChainApi.getOptionChain('key','NIFTY','NFO','03NOV26',null)
  expect(apiClient.post).toHaveBeenLastCalledWith('/optionchain',expect.objectContaining({strike_count:null}))
  await optionChainApi.getOptionChain('key','NIFTY','NFO','03NOV26')
  expect(apiClient.post).toHaveBeenLastCalledWith('/optionchain',expect.objectContaining({strike_count:20}))
})
