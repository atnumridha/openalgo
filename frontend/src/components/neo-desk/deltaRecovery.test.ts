import { beforeEach, expect, it } from 'vitest'
import {
  readAutoRecovery,
  saveAutoRecovery,
  clearAutoRecovery,
  recoveryPauseReason,
} from './deltaRecovery'
import type { DeltaChartState } from '@/api/deltaChart'
beforeEach(() => localStorage.clear())
it('persists an armed scope across restarts with its exact settings, and OFF removes it', () => {
  const record = {
    version: 1 as const,
    generation: 'arm-1',
    account: 'a',
    symbol: 'BTCUSD',
    seconds: 60,
    settings: { leverage: 25, balanceFraction: 0.5 as const, manualQuantity: '1' },
  }
  expect(saveAutoRecovery(record)).toBe(true)
  expect(readAutoRecovery('a', 'BTCUSD', 60)).toEqual(record)
  expect(readAutoRecovery('other', 'BTCUSD', 60)).toBeNull()
  expect(clearAutoRecovery('a', 'BTCUSD', 60)).toBe(true)
  expect(readAutoRecovery('a', 'BTCUSD', 60)).toBeNull()
})
it('waits for the trade journal and pending requests before resuming a flat account', () => {
  const state = {
    position: null,
    orders: [],
    pending: [],
    managed_plans: [],
  } as unknown as DeltaChartState
  expect(recoveryPauseReason(state, 60)).toBeNull()
  expect(
    recoveryPauseReason(
      { ...state, pending: [{ request_id: 'x', action: 'entry', message: 'Unknown' }] },
      60
    )
  ).toMatch(/pending/)
  expect(recoveryPauseReason({ ...state, managed_plans: undefined }, 60)).toMatch(/journal/)
})

it('rejects malformed fixed lots and rejects a revoked or replaced generation', () => {
  const key = 'delta-chart:auto-resume:v1:a:BTCUSD:60'
  localStorage.setItem(
    key,
    JSON.stringify({
      version: 1,
      generation: 'g1',
      account: 'a',
      symbol: 'BTCUSD',
      seconds: 60,
      settings: { leverage: 50, balanceFraction: null, manualQuantity: 2 },
    })
  )
  expect(() => readAutoRecovery('a', 'BTCUSD', 60)).toThrow()
})

it('isolates scalp recovery from legacy chart permissions and revokes only the selected strategy', () => {
  const record = {
    version: 1 as const,
    generation: 'legacy',
    account: 'a',
    symbol: 'BTCUSD',
    seconds: 60,
    settings: { leverage: 50, balanceFraction: 1 as const, manualQuantity: '1' },
  }
  expect(saveAutoRecovery(record)).toBe(true)
  expect(readAutoRecovery('a', 'BTCUSD', 60, 'scalp-1m-5m-v1')).toBeNull()
  const scalp = { ...record, generation: 'scalp', strategy: 'scalp-1m-5m-v1' }
  expect(saveAutoRecovery(scalp)).toBe(true)
  expect(readAutoRecovery('a', 'BTCUSD', 60, 'scalp-1m-5m-v1')).toEqual(scalp)
  expect(clearAutoRecovery('a', 'BTCUSD', 60, 'scalp-1m-5m-v1')).toBe(true)
  expect(readAutoRecovery('a', 'BTCUSD', 60, 'scalp-1m-5m-v1')).toBeNull()
  expect(readAutoRecovery('a', 'BTCUSD', 60)?.generation).toBe('legacy')
})
