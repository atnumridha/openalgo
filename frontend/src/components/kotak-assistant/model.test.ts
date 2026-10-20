import type { Snapshot } from '@/api/kotakAssistant'
import { describe, expect, it } from 'vitest'
import {
  expiryAscending,
  executableQuote,
  estimatedNet,
  deskPlaceholder,
  rewardTarget,
} from './model'

describe('Kotak desk data', () => {
  it('keeps net unavailable until the fee estimate exists', () => {
    expect(estimatedNet(100, 90, undefined)).toBeNull()
    expect(estimatedNet(100, 90, 70)).toBe(80)
    expect(estimatedNet(null, 90, 70)).toBeNull()
  })
  it('orders expiry by date across months and years', () => {
    expect(expiryAscending(['28OCT26', '07JAN27', '31DEC26', 'bad', '28OCT26'])).toEqual([
      '28OCT26',
      '31DEC26',
      '07JAN27',
    ])
  })
  it('does not invent a quote from missing or crossed prices', () => {
    expect(executableQuote(undefined)).toBe(false)
    expect(executableQuote({ bid: 101, ask: 100, time: Date.now() / 1000 })).toBe(false)
    expect(executableQuote({ bid: 99, ask: 100, time: Date.now() / 1000 - 6 })).toBe(false)
    expect(executableQuote({ bid: 99, ask: 100, time: Date.now() / 1000 })).toBe(true)
  })
})

describe('Scoped snapshot continuity', () => {
  const key = ['kotak-desk', 'user', 'live', 'NIFTY', '19OCT26', 8, 'oldCE']
  const prior = {
    chain: { chain: [] },
    selected_plan: { entry: 100 },
    trades: [],
  } as unknown as Snapshot
  it('retains the chain while discarding the previous contract plan', () => {
    const value = deskPlaceholder(prior, key, [...key.slice(0, 6), 'newPE'])
    expect(value?.chain).toBe(prior.chain)
    expect(value?.selected_plan).toBeUndefined()
  })
  it('never carries account, mode, index or expiry data across a scope change', () => {
    for (const index of [1, 2, 3, 4]) {
      const next = [...key]
      next[index] = 'different'
      expect(deskPlaceholder(prior, key, next)).toBeUndefined()
    }
  })
})

describe('Option premium risk/reward targets', () => {
  it('calculates the requested multiples from entry minus stop loss', () => {
    expect(rewardTarget(100, 90, 1.5, 0.05)).toBe(115)
    expect(rewardTarget(100, 90, 2, 0.05)).toBe(120)
    expect(rewardTarget(100, 90, 5, 0.05)).toBe(150)
  })
  it('rounds upward to a valid tick without understating the reward', () => {
    expect(rewardTarget(100.05, 99.9, 1.5, 0.05)).toBe(100.3)
  })
  it('requires a valid stop below entry and a known contract tick', () => {
    expect(rewardTarget(100, 0, 2, 0.05)).toBeNull()
    expect(rewardTarget(100, 100, 2, 0.05)).toBeNull()
    expect(rewardTarget(100, 105, 2, 0.05)).toBeNull()
    expect(rewardTarget(100, 90, 2, 0)).toBeNull()
  })
})
