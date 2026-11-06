import { expect, it } from 'vitest'
import { indicatorAction, resolveIndicatorChart } from './indicatorChartContext'

it.each([
  ['NIFTY03NOV2623000CE', 'NFO', 'CE', 'NIFTY', 'NSE_INDEX', '03NOV26'],
  ['NIFTY03NOV2623000PE', 'NFO', 'PE', 'NIFTY', 'NSE_INDEX', '03NOV26'],
  ['SENSEX05NOV2675000PE', 'BFO', 'PE', 'SENSEX', 'BSE_INDEX', '05NOV26'],
  ['RELIANCE24NOV262500CE', 'NFO', 'CE', 'RELIANCE', 'NSE', '24NOV26'],
])('resolves %s without using its premium as the underlying', (symbol, exchange, side, root, venue, expiry) => {
  const c = resolveIndicatorChart(symbol, exchange)
  expect(c.kind).toBe('option')
  expect(c.optionSide).toBe(side)
  expect(c.underlying).toEqual({ symbol: root, exchange: venue })
  expect(c.expiry).toBe(expiry)
})

it('rejects a stale NIFTY reference when the displayed contract is SENSEX', () => {
  const c = resolveIndicatorChart('SENSEX05NOV2675000PE', 'BFO', {
    underlying: 'NIFTY',
    exchange: 'NSE_INDEX',
    optionExchange: 'NFO',
    expiry: '03NOV26',
    pe: { symbol: 'NIFTY03NOV2623000PE', strike: 23000 },
  })
  expect(c.underlying).toEqual({ symbol: 'SENSEX', exchange: 'BSE_INDEX' })
  expect(c.reference).toBeUndefined()
})

it('does not guess an underlying for an unrecognized contract', () => {
  const c = resolveIndicatorChart('UNKNOWN-PE', 'NFO')
  expect(c.kind).toBe('option')
  expect(c.underlying).toBeUndefined()
})

it.each([
  ['CE', 'underlying', 'CALL', 'ma', 'BUY CE', 'CALL'],
  ['CE', 'underlying', 'PUT', 'ma', 'AVOID CE', 'PUT'],
  ['PE', 'underlying', 'PUT', 'ma', 'BUY PE', 'CALL'],
  ['PE', 'underlying', 'CALL', 'ma', 'AVOID PE', 'PUT'],
  ['PE', 'premium', 'CALL', 'ma', 'BUY PE', 'CALL'],
  ['PE', 'premium', 'PUT', 'ma', 'AVOID PE', 'PUT'],
  ['PE', 'premium', 'PUT', 'pcr', 'BUY PE', 'CALL'],
  ['PE', 'premium', 'CALL', 'iv', 'AVOID PE', 'PUT'],
  ['CE', 'premium', 'WAIT', 'oi', 'WAIT', 'WAIT'],
] as const)('maps %s %s %s %s to the displayed contract action', (side, source, bias, key, label, tone) => {
  const c = resolveIndicatorChart(`NIFTY03NOV2623000${side}`, 'NFO')
  expect(indicatorAction(bias, c, source, key)).toEqual({ label, side: tone })
})

it('preserves index labels and uses price direction on other markets', () => {
  expect(
    indicatorAction('PUT', resolveIndicatorChart('NIFTY', 'NSE_INDEX'), 'underlying', 'ma').label
  ).toBe('BUY PUT')
  expect(
    indicatorAction('CALL', resolveIndicatorChart('BTCUSD', 'DELTA'), 'premium', 'ma').label
  ).toBe('LONG')
})

it.each([
  'CE',
  'PE',
] as const)('keeps every premium-price study in %s contract direction', (optionSide) => {
  const chart = resolveIndicatorChart(`NIFTY03NOV2623000${optionSide}`, 'NFO')
  for (const key of ['rsi', 'bb', 'imi', 'mfi', 'macd', 'ma'] as const) {
    expect(indicatorAction('CALL', chart, 'premium', key)).toEqual({
      label: `BUY ${optionSide}`,
      side: 'CALL',
    })
    expect(indicatorAction('PUT', chart, 'premium', key)).toEqual({
      label: `AVOID ${optionSide}`,
      side: 'PUT',
    })
    expect(indicatorAction('WAIT', chart, 'premium', key)).toEqual({ label: 'WAIT', side: 'WAIT' })
  }
})

it.each([
  'MCX',
  'CDS',
])('keeps %s bought-premium signals long without guessing a cash underlying', (exchange) => {
  const chart = resolveIndicatorChart('GOLD30NOV26100000PE', exchange)
  expect(chart.kind).toBe('option')
  expect(chart.optionSide).toBe('PE')
  expect(chart.underlying).toBeUndefined()
  expect(indicatorAction('CALL', chart, 'premium', 'macd').label).toBe('BUY PE')
  expect(indicatorAction('PUT', chart, 'premium', 'macd').label).toBe('AVOID PE')
})

it('labels perpetual directional events LONG and SHORT without options terminology', () => {
  const crypto = resolveIndicatorChart('BTCUSD', 'DELTA')
  expect(indicatorAction('CALL', crypto, 'premium', 'macd').label).toBe('LONG')
  expect(indicatorAction('PUT', crypto, 'premium', 'ma').label).toBe('SHORT')
})
