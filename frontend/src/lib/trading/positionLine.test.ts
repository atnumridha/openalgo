/**
 * The position line's label for a Delta BTCUSD long opened outside OpenAlgo:
 * 59 contracts of 0.001 BTC, so a 11-dollar move is worth 65 cents, not 649
 * rupees.
 */
import { describe, expect, it } from 'vitest'
import { DEFAULT_FEE_PROFILE, positionFees } from '@/lib/cryptoFees'
import { fmtPrice } from './format'
import { grossPnl, positionFromRow, positionLabel, valuationPrice } from './positionLine'

const fmt = (n: number) => fmtPrice(n, 0.5, n)

const BTC_ROW = {
  symbol: 'BTCUSDFUT',
  exchange: 'CRYPTO',
  product: 'NRML',
  quantity: 59,
  average_price: 84646.5,
  ltp: 84657.5,
  mark_price: 84657.5,
  lot_size: 0.001,
  pnl: 0.649,
}

describe('a crypto position is valued per contract, in dollars', () => {
  it('applies the 0.001 BTC contract value to 59 BTCUSD contracts', () => {
    const position = positionFromRow(BTC_ROW)
    expect(position).not.toBeNull()
    expect(position?.contractValue).toBe(0.001)
    expect(grossPnl(position!, 84657.5)).toBeCloseTo(0.649, 9)
  })

  it('values at the mark price, as the Positions page does, not the last trade', () => {
    const position = positionFromRow({ ...BTC_ROW, mark_price: 84650 })!
    expect(valuationPrice(position, 84700)).toBe(84650)
  })

  it('labels gross and net in dollars, net matching the Positions row', () => {
    const now = Date.parse('2026-10-03T12:00:00Z')
    const position = positionFromRow(BTC_ROW)!
    const label = positionLabel(position, 84700, fmt, DEFAULT_FEE_PROFILE, now)
    expect(label).toContain('Gross +$0.65')
    expect(label).not.toContain('₹')
    const net = positionFees(BTC_ROW, DEFAULT_FEE_PROFILE, {}, now).net
    const shown = `${net >= 0 ? '+' : '-'}$${Math.abs(net).toFixed(2)}`
    expect(label).toContain(`Net ${shown}`)
    expect(label.startsWith('@ 84,646.50')).toBe(true)
  })

  it('keeps rupees and the last trade for an Indian position', () => {
    const position = positionFromRow({
      symbol: 'BHEL',
      exchange: 'NSE',
      product: 'MIS',
      quantity: 10,
      average_price: 250,
      lot_size: 1,
    })!
    expect(position.contractValue).toBe(1)
    expect(positionLabel(position, 252, fmt)).toBe('@ 250.00  +₹20.00')
  })

  it('reads a flat or missing row as no position', () => {
    expect(positionFromRow({ ...BTC_ROW, quantity: 0 })).toBeNull()
    expect(positionFromRow(undefined)).toBeNull()
  })
})
