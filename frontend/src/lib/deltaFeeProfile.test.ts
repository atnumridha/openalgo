import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_FEE_PROFILE } from './cryptoFees'
import { knownDeltaFeeProfile, rememberDeltaFeeProfile } from './deltaFeeProfile'
describe('shared configured Delta fees', () => {
  beforeEach(() => {
    rememberDeltaFeeProfile('u', undefined)
  })
  it('does not silently substitute a fee offer for an unknown account', () => {
    expect(knownDeltaFeeProfile('u')).toBeNull()
    rememberDeltaFeeProfile('u', { ...DEFAULT_FEE_PROFILE, scalper_offer: false })
    expect(knownDeltaFeeProfile('u')?.scalper_offer).toBe(false)
    expect(knownDeltaFeeProfile('other')).toBeNull()
  })
  it('expires a stale fee snapshot', () => {
    vi.useFakeTimers()
    try {
      rememberDeltaFeeProfile('u', DEFAULT_FEE_PROFILE)
      expect(knownDeltaFeeProfile('u')).not.toBeNull()
      vi.advanceTimersByTime(20000)
      expect(knownDeltaFeeProfile('u')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})
