import { describe, expect, it } from 'vitest'
import { activeExpiries, nearestExpiry, underlyingPriceExchange } from './neoOptionSelection'
describe('active NIFTY expiry selection', () => {
  it('sorts by actual date descending while defaulting to the nearest active expiry', () => {
    const dates = ['05JAN27', '19OCT26', '13OCT26', '27OCT26', 'invalid', '06OCT26']
    const active = activeExpiries(dates, new Date('2026-10-13T10:00:00+05:30'))
    expect(active).toEqual(['05JAN27', '27OCT26', '19OCT26', '13OCT26'])
    expect(nearestExpiry(active)).toBe('13OCT26')
  })
  it('rolls expiry-day defaults after the market close without guessing calendar dates', () => {
    const active = activeExpiries(['13OCT26', '19OCT26'], new Date('2026-10-13T15:30:00+05:30'))
    expect(active).toEqual(['19OCT26'])
    expect(nearestExpiry(active)).toBe('19OCT26')
  })
})

it('never queries an index on the option exchange while chain metadata is loading', () => {
  expect(underlyingPriceExchange('NIFTY','NFO')).toBe('NSE_INDEX')
  expect(underlyingPriceExchange('SENSEX','BFO')).toBe('BSE_INDEX')
  expect(underlyingPriceExchange('RELIANCE','NFO')).toBe('')
  expect(underlyingPriceExchange('RELIANCE','NFO','NSE')).toBe('NSE')
})
