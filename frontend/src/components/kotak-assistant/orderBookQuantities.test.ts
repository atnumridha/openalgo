import { expect, it } from 'vitest'
import { orderBookQuantities } from './orderBookQuantities'
it('reports only visible pending quantities, without treating them as traded volume', () => {
  const data = {
    depth: {
      buy: [
        { price: 100, quantity: 65, orders: 1 },
        { price: 99, quantity: 130, orders: 2 },
      ],
      sell: [{ price: 101, quantity: 260, orders: 1 }],
    },
  }
  expect(orderBookQuantities(data)).toEqual({
    buy_quantity: 195,
    sell_quantity: 260,
    buy_levels: 2,
    sell_levels: 1,
  })
  expect(orderBookQuantities({}).buy_quantity).toBeUndefined()
  expect(orderBookQuantities({ bid_size: 0, ask_size: 65 })).toMatchObject({
    buy_quantity: 0,
    sell_quantity: 65,
    buy_levels: 1,
  })
})
