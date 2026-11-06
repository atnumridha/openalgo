import { afterEach, expect, it, vi } from 'vitest'
const product = (symbol: string, id = 1) => ({
  id,
  symbol,
  state: 'live',
  contract_type: 'perpetual_futures',
  tick_size: '0.01',
  description: `${symbol} perpetual`,
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
async function service() {
  vi.resetModules()
  return import('./deltaProducts')
}
it('paginates public live USD perpetuals, validates and deduplicates, then caches for 60 seconds', async () => {
  let now = 100000
  vi.spyOn(Date, 'now').mockImplementation(() => now)
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        success: true,
        result: [
          product('SOLUSD'),
          product('BAD/USD'),
          product('OLDUSD', 3),
          { ...product('OPTUSD', 4), contract_type: 'call_options' },
        ].map((p) => (p.symbol === 'OLDUSD' ? { ...p, state: 'expired' } : p)),
        meta: { after: 'next' },
      }),
    })
    .mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        result: [product('SOLUSD'), product('JUPUSD', 2)],
        meta: { after: null },
      }),
    })
  vi.stubGlobal('fetch', fetcher)
  const { readDeltaProducts } = await service()
  const rows = await readDeltaProducts()
  expect(rows.map((r) => r.symbol)).toEqual(['JUPUSD', 'SOLUSD'])
  expect(rows[0]).toMatchObject({ id: 2, tick_size: 0.01 })
  expect(String(fetcher.mock.calls[0][0])).toContain('contract_types=perpetual_futures')
  expect(String(fetcher.mock.calls[1][0])).toContain('after=next')
  expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: 'omit' })
  await readDeltaProducts()
  expect(fetcher).toHaveBeenCalledTimes(2)
  now += 60001
  await readDeltaProducts()
  expect(fetcher).toHaveBeenCalledTimes(3)
})
it('deduplicates simultaneous lookups and respects an aborted reader without poisoning the cache', async () => {
  let finish!: (value: unknown) => void
  const fetcher = vi.fn(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  vi.stubGlobal('fetch', fetcher)
  const { readDeltaProducts } = await service()
  const controller = new AbortController()
  const first = readDeltaProducts(controller.signal)
  const rejection = expect(first).rejects.toMatchObject({ name: 'AbortError' })
  const second = readDeltaProducts()
  controller.abort()
  await rejection
  finish({ ok: true, json: async () => ({ success: true, result: [product('SOLUSD')], meta: {} }) })
  expect((await second)[0].symbol).toBe('SOLUSD')
  expect(fetcher).toHaveBeenCalledTimes(1)
})
it('rejects malformed pages and repeated cursors instead of caching incomplete lists', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, result: [product('SOLUSD')], meta: { after: 'same' } }),
    })
  vi.stubGlobal('fetch', fetcher)
  const { readDeltaProducts } = await service()
  await expect(readDeltaProducts()).rejects.toThrow(/pagination/i)
  expect(fetcher).toHaveBeenCalledTimes(2)
  fetcher.mockResolvedValue({ ok: true, json: async () => ({ success: true, result: null }) })
  await expect(readDeltaProducts()).rejects.toThrow(/products/i)
})
it('limits pagination to ten requests and never requests for an already aborted reader', async () => {
  const fetcher = vi.fn(async () => ({
    ok: true,
    json: async () => ({
      success: true,
      result: [product('SOLUSD')],
      meta: { after: `page-${fetcher.mock.calls.length}` },
    }),
  }))
  vi.stubGlobal('fetch', fetcher)
  const { readDeltaProducts } = await service()
  const controller = new AbortController()
  controller.abort()
  await expect(readDeltaProducts(controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
  expect(fetcher).not.toHaveBeenCalled()
  await expect(readDeltaProducts()).rejects.toThrow(/request limit/)
  expect(fetcher).toHaveBeenCalledTimes(10)
})
