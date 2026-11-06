import { beforeEach, expect, it } from 'vitest'
import {
  readDeltaTradeDefaults,
  saveDeltaTradeDefaults,
  DELTA_TRADE_DEFAULTS_KEY,
} from './deltaTradeDefaults'
beforeEach(() => localStorage.clear())
it('starts at 50x and 100% and persists percentage or fixed whole lots', () => {
  expect(readDeltaTradeDefaults()).toEqual({
    leverage: 50,
    balanceFraction: 1,
    manualQuantity: '1',
  })
  expect(saveDeltaTradeDefaults({ leverage: 25, balanceFraction: 0.5, manualQuantity: '2' })).toBe(
    true
  )
  expect(readDeltaTradeDefaults().leverage).toBe(25)
  expect(saveDeltaTradeDefaults({ leverage: 10, balanceFraction: null, manualQuantity: '3' })).toBe(
    true
  )
  expect(readDeltaTradeDefaults()).toEqual({
    leverage: 10,
    balanceFraction: null,
    manualQuantity: '3',
  })
})
it('rejects invalid defaults and falls back safely from malformed stored data', () => {
  expect(saveDeltaTradeDefaults({ leverage: 201, balanceFraction: 1, manualQuantity: '1' })).toBe(
    false
  )
  expect(saveDeltaTradeDefaults({ leverage: 50, balanceFraction: null, manualQuantity: '0' })).toBe(
    false
  )
  localStorage.setItem(DELTA_TRADE_DEFAULTS_KEY, 'null')
  expect(readDeltaTradeDefaults().leverage).toBe(50)
})
