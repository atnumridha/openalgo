import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@/test/test-utils'
import { useLivePrice } from './useLivePrice'

/**
 * The closed-position branch.
 *
 * `useLivePrice` freezes an item's REST values when its quantity is zero, so a
 * closed position's realized P&L percentage does not drift as the market moves.
 * `quantity` is optional on `PriceableItem`, and `item.quantity || 0` read the
 * same zero for "this position is closed" and "this is not a position at all",
 * which silently froze every watchlist row at its REST price.
 *
 * The gate is now on the field being present. These tests pin both readings,
 * because this hook also prices Positions and Holdings and nothing else covered
 * it.
 */
const marketData = new Map<
  string,
  { data: { ltp: number; mark_price?: number }; lastUpdate: number }
>()

vi.mock('./useMarketData', () => ({
  useMarketData: () => ({
    data: marketData,
    isConnected: true,
    isAuthenticated: true,
    isPaused: false,
    isFallbackMode: false,
    error: null,
  }),
}))

vi.mock('./useMarketStatus', () => ({
  useMarketStatus: () => ({
    isMarketOpen: () => true,
    isAnyMarketOpen: () => true,
  }),
}))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ apiKey: 'k' }),
}))

vi.mock('@/api/trading', () => ({
  tradingApi: {
    getMultiQuotes: vi.fn(async () => ({
      status: 'success',
      results: [{ symbol: 'RELIANCE', exchange: 'NSE', data: { ltp: 1300, prev_close: 1280 } }],
    })),
  },
}))

describe('useLivePrice closed-position gate', () => {
  beforeEach(() => {
    marketData.clear()
    marketData.set('NSE:RELIANCE', { data: { ltp: 1350 }, lastUpdate: Date.now() })
  })

  it('takes live prices for an item that carries no quantity at all', async () => {
    // A watchlist row. Not a position, so it must never be frozen.
    const { result } = renderHook(() =>
      useLivePrice([{ symbol: 'RELIANCE', exchange: 'NSE' }], { enabled: true })
    )

    await waitFor(() => expect(result.current.data[0].ltp).toBe(1350))
  })

  it('keeps the REST values for a position that has been closed', async () => {
    // quantity is present and zero, which is what "closed" means here.
    const { result } = renderHook(() =>
      useLivePrice([{ symbol: 'RELIANCE', exchange: 'NSE', quantity: 0, ltp: 1000 }], {
        enabled: true,
      })
    )

    await waitFor(() => expect(result.current.data).toHaveLength(1))
    expect(result.current.data[0].ltp).toBe(1000)
  })

  it('takes live prices for an open position', async () => {
    const { result } = renderHook(() =>
      useLivePrice([{ symbol: 'RELIANCE', exchange: 'NSE', quantity: 5, ltp: 1000 }], {
        enabled: true,
      })
    )

    await waitFor(() => expect(result.current.data[0].ltp).toBe(1350))
  })
})

describe('useLivePrice P&L% on a contract multiplier', () => {
  beforeEach(() => {
    marketData.clear()
    marketData.set('CRYPTO:BTCUSDFUT', { data: { ltp: 84000 }, lastUpdate: Date.now() })
  })

  it('measures P&L% against the contract notional, not price x contracts', async () => {
    // One Delta BTCUSD contract is 0.001 BTC: $85 notional at $85,000. A $1,000
    // drop is $1 on that, -1.18%. Without the multiplier the base was $85,000
    // and the row read -0.00%.
    const { result } = renderHook(() =>
      useLivePrice(
        [
          {
            symbol: 'BTCUSDFUT',
            exchange: 'CRYPTO',
            quantity: 1,
            average_price: 85000,
            ltp: 85000,
            lot_size: 0.001,
          },
        ],
        { enabled: true }
      )
    )

    await waitFor(() => expect(result.current.data[0].ltp).toBe(84000))
    expect(result.current.data[0].pnl).toBeCloseTo(-1, 6)
    expect(result.current.data[0].pnlpercent).toBeCloseTo(-1.1765, 3)
  })

  it('values the position at the mark price when the feed carries one', async () => {
    // Delta marks positions to its mark price, not the last trade. The row
    // shows the last trade as LTP but its P&L must match the exchange's.
    marketData.set('CRYPTO:BTCUSDFUT', {
      data: { ltp: 84000, mark_price: 84100 },
      lastUpdate: Date.now(),
    })
    const { result } = renderHook(() =>
      useLivePrice(
        [
          {
            symbol: 'BTCUSDFUT',
            exchange: 'CRYPTO',
            quantity: -2,
            average_price: 85000,
            ltp: 85000,
            lot_size: 0.001,
          },
        ],
        { enabled: true }
      )
    )

    await waitFor(() => expect(result.current.data[0].ltp).toBe(84000))
    expect(result.current.data[0].pnl).toBeCloseTo(1.8, 6)
  })
})
