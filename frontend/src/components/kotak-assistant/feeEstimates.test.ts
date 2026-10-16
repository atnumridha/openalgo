import { describe, expect, it } from 'vitest'
import { optionFees, ticketCosts, openTradeCosts } from './feeEstimates'
import type { Trade } from '@/api/kotakAssistant'

describe('Kotak zero API brokerage estimates', () => {
  it('includes current taxes on premium turnover with zero brokerage', () => {
    expect(optionFees(9373, 11251.5, 'NFO', 0, '2026-10-15')).toEqual({
      stt: 16.88,
      stamp: 0.28,
      exchange: 7.33,
      sebi: 0.02,
      ipft: 0,
      brokerage: 0,
      gst: 1.32,
      total: 25.83,
    })
    expect(optionFees(10000, 11000, 'BFO', 0, '2026-10-15')?.total).toBe(24.88)
    expect(optionFees(10000, 11000, 'NFO', 10, '2026-10-15')?.total).toBe(49.23)
  })
  it('calculates separate SL and target charges and includes configured slippage', () => {
    const order = { entry: 144.2, sl: 129.75, target: 173.1, quantity: 65 }
    expect(ticketCosts(order, 'NFO', 0, 0, '2026-10-15')).toMatchObject({
      premium: 9373,
      grossSL: -939.25,
      grossTarget: 1878.5,
      chargesSL: 20.42,
      chargesTarget: 25.83,
      netSL: -959.67,
      netTarget: 1852.67,
    })
    expect(ticketCosts(order, 'NFO', 0, 0.1, '2026-10-15')).toMatchObject({
      grossSL: -945.75,
      grossTarget: 1872,
      netSL: -966.16,
      netTarget: 1846.18,
      netRR: 1.91,
    })
  })
  it('does not invent costs for unsupported schedules or invalid inputs', () => {
    for (const [exchange, day] of [
      ['NSE', '2026-10-15'],
      ['NFO', '2027-01-01'],
      ['BFO', '2026-02-30'],
    ]) {
      expect(optionFees(100, 110, exchange, 0, day)).toBeNull()
    }
    expect(optionFees(NaN, 110, 'NFO', 0, '2026-10-15')).toBeNull()
    expect(ticketCosts({ entry: 100, sl: 105, target: 120, quantity: 65 }, 'NFO')).toBeNull()
    expect(ticketCosts({ entry: 100, sl: 90, target: 120, quantity: 0 }, 'NFO')).toBeNull()
  })
  it('uses the current bid and remaining quantity for open net P&L', () => {
    const trade = { average_entry: 100, remaining: 65, exchange: 'NFO' } as Trade
    const quote = { bid: 110, ask: 110.05, time: Date.now() / 1000 }
    expect(openTradeCosts(trade, quote, 0, '2026-10-15')).toMatchObject({
      gross: 650,
      charges: 16.66,
      net: 633.34,
    })
    expect(
      openTradeCosts(trade, { ...quote, bid: 120, ask: 120.05 }, 0, '2026-10-15')
    ).toMatchObject({ gross: 1300, charges: 17.91, net: 1282.09 })
    expect(
      openTradeCosts({ ...trade, average_entry_verified: false }, quote, 0, '2026-10-15')
    ).toBeNull()
    expect(openTradeCosts(trade, { ...quote, time: quote.time - 10 }, 0, '2026-10-15')).toBeNull()
    expect(openTradeCosts({ ...trade, remaining: 0 }, quote, 0, '2026-10-15')).toBeNull()
  })
})
