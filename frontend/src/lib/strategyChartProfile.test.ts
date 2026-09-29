import { describe, expect, it } from 'vitest'
import { strategyChartProfile } from './strategyChartProfile'

describe('strategyChartProfile', () => {
  it('maps NIFTY EMA 9/15 to index 5m overlays', () => {
    const profile = strategyChartProfile({
      underlying: 'NIFTY',
      underlying_exchange: 'NSE_INDEX',
      scalp_profile: 'ema915',
    })
    expect(profile).toMatchObject({
      symbol: 'NIFTY',
      exchange: 'NSE_INDEX',
      session: 'index',
      interval: '5m',
      confirmationInterval: null,
      indicators: ['ema9', 'ema15'],
    })
  })

  it('maps SENSEX receiver to BSE_INDEX 5m with 15m confirmation', () => {
    const profile = strategyChartProfile({
      underlying: 'SENSEX',
      underlying_exchange: 'BSE_INDEX',
      scalp_profile: 'receiver_retest',
    })
    expect(profile).toMatchObject({
      symbol: 'SENSEX',
      exchange: 'BSE_INDEX',
      session: 'index',
      interval: '5m',
      confirmationInterval: '15m',
    })
  })

  it.each([
    'GOLDM',
    'CRUDEOILM',
    'SILVERM',
    'NATGASMINI',
  ] as const)('maps %s MCX receiver onto the commodity session', (underlying) => {
    const profile = strategyChartProfile({
      underlying,
      underlying_exchange: 'MCX',
      scalp_profile: 'receiver_momentum',
    })
    expect(profile).toMatchObject({
      symbol: underlying,
      exchange: 'MCX',
      session: 'mcx',
      interval: '5m',
      confirmationInterval: '15m',
    })
  })

  it('uses a Kotak basket saved underlying instead of hardcoding NIFTY', () => {
    const profile = strategyChartProfile({
      underlying: 'SENSEX',
      underlying_exchange: 'BSE_INDEX',
      scalp_profile: null,
    })
    expect(profile).toMatchObject({
      symbol: 'SENSEX',
      exchange: 'BSE_INDEX',
      interval: '5m',
      indicators: [],
    })
  })

  it('returns null when the strategy has no chartable underlying', () => {
    expect(strategyChartProfile({ underlying: '', underlying_exchange: 'NSE_INDEX' })).toBeNull()
    expect(strategyChartProfile({ underlying: 'NIFTY', underlying_exchange: '' })).toBeNull()
  })
})
