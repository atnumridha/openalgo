import type { MarketData } from '@/hooks/useMarketData'

export function orderBookQuantities(data: Pick<MarketData, 'depth' | 'bid_size' | 'ask_size'>) {
  const side = (rows: Array<{ quantity: number }> | undefined, best: number | undefined) => {
    if (rows?.length && rows.every((row) => Number.isFinite(row.quantity) && row.quantity >= 0))
      return { quantity: rows.reduce((sum, row) => sum + row.quantity, 0), levels: rows.length }
    return best != null && Number.isFinite(best) && best >= 0
      ? { quantity: best, levels: 1 }
      : { quantity: undefined, levels: 0 }
  }
  const buy = side(data.depth?.buy, data.bid_size),
    sell = side(data.depth?.sell, data.ask_size)
  return {
    buy_quantity: buy.quantity,
    sell_quantity: sell.quantity,
    buy_levels: buy.levels,
    sell_levels: sell.levels,
  }
}
