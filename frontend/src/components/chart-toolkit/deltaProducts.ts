/** Public Delta India product discovery. No account credentials or trading endpoints. */
export interface DeltaPublicProduct {
  id: number
  symbol: string
  name: string
  tick_size: number
}

export const isDeltaChartSymbol = (symbol: string) => /^[A-Z0-9]{3,20}USD$/.test(symbol)
let cache: { expires: number; products: readonly DeltaPublicProduct[] } | undefined
let pending: Promise<readonly DeltaPublicProduct[]> | undefined

async function fetchProducts(): Promise<readonly DeltaPublicProduct[]> {
  const products = new Map<string, DeltaPublicProduct>()
  const cursors = new Set<string>()
  const signal = AbortSignal.timeout(15000)
  let after: string | undefined
  for (let page = 0; page < 10; page++) {
    const params = new URLSearchParams({
      contract_types: 'perpetual_futures',
      states: 'live',
      page_size: '100',
    })
    if (after) params.set('after', after)
    const response = await fetch(`https://api.india.delta.exchange/v2/products?${params}`, {
      credentials: 'omit',
      signal,
    })
    if (!response.ok) throw Error(`Delta products unavailable (${response.status})`)
    const data = await response.json()
    if (!data?.success || !Array.isArray(data.result))
      throw Error('Delta returned invalid products')
    for (const value of data.result) {
      if (!value || typeof value !== 'object') continue
      const { id, symbol, state, contract_type } = value
      const tick = Number(value.tick_size)
      if (
        !Number.isSafeInteger(id) ||
        id <= 0 ||
        typeof symbol !== 'string' ||
        !isDeltaChartSymbol(symbol) ||
        state !== 'live' ||
        contract_type !== 'perpetual_futures' ||
        !Number.isFinite(tick) ||
        tick <= 0
      )
        continue
      products.set(
        symbol,
        Object.freeze({
          id,
          symbol,
          name: typeof value.description === 'string' ? value.description : `${symbol} perpetual`,
          tick_size: tick,
        })
      )
    }
    const cursor = data.meta?.after
    if (cursor == null || cursor === '')
      return Object.freeze([...products.values()].sort((a, b) => a.symbol.localeCompare(b.symbol)))
    if (typeof cursor !== 'string' || cursor.length > 4096 || cursors.has(cursor))
      throw Error('Invalid Delta product pagination')
    cursors.add(cursor)
    after = cursor
  }
  throw Error('Delta product pagination exceeded the request limit')
}

/** Concurrent searches share one bounded fetch; aborting a reader never cancels other readers. */
export async function readDeltaProducts(
  signal?: AbortSignal
): Promise<readonly DeltaPublicProduct[]> {
  signal?.throwIfAborted()
  if (cache && Date.now() < cache.expires) return cache.products
  if (!pending) {
    pending = fetchProducts()
      .then((products) => {
        cache = { expires: Date.now() + 60000, products }
        return products
      })
      .finally(() => {
        pending = undefined
      })
  }
  const request = pending
  if (!signal) return request
  return new Promise((resolve, reject) => {
    const aborted = () => reject(signal.reason ?? new DOMException('Aborted', 'AbortError'))
    signal.addEventListener('abort', aborted, { once: true })
    request.then(resolve, reject).finally(() => signal.removeEventListener('abort', aborted))
    if (signal.aborted) aborted()
  })
}
