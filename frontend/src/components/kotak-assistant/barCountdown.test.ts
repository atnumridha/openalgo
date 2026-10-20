import { describe, expect, it } from 'vitest'
import { barCountdown } from './barCountdown'

const start = Date.parse('2026-10-15T09:15:00+05:30') / 1000
// Broker chart history stores IST-shifted Unix seconds.
const bar = start + 19800

describe('Current candle close timer', () => {
  it('counts down from the latest bar start in the selected timeframe', () => {
    expect(barCountdown(bar, '1m', start)).toMatchObject({ state: 'forming', text: '01:00' })
    expect(barCountdown(bar, '1m', start + 37.1)).toMatchObject({ state: 'forming', text: '00:23' })
    expect(barCountdown(bar, '5m', start + 61)).toMatchObject({ state: 'forming', text: '03:59' })
    expect(barCountdown(bar, '15m', start + 61)).toMatchObject({ state: 'forming', text: '13:59' })
  })
  it('does not restart a timer until data actually contains the next candle', () => {
    expect(barCountdown(bar, '1m', start + 59.9).text).toBe('00:01')
    expect(barCountdown(bar, '1m', start + 60)).toMatchObject({ state: 'closed', text: 'Closed' })
    expect(barCountdown(bar + 60, '1m', start + 60).text).toBe('01:00')
  })
  it('marks historical bars closed and does not invent a current bar', () => {
    expect(barCountdown(bar, '1m', start + 86400).state).toBe('closed')
    expect(barCountdown(null, '1m', start).state).toBe('waiting')
    expect(barCountdown(bar + 60, '1m', start).state).toBe('waiting')
    expect(barCountdown(bar, 'unsupported', start).state).toBe('waiting')
    expect(barCountdown(bar, '1m', NaN).state).toBe('waiting')
  })
})
