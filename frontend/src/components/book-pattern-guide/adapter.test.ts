import { expect, it } from 'vitest'
import { bookChartBars, bookChartContext, validatedBookInstrument } from './adapter'
import { analyzeBookGuide } from './engine'
const session = { start: 555, end: 930, offset: 19800 }
const close = Date.parse('2026-11-05T10:00:00Z') / 1000
const b = { time: close - 1800, open: 100, high: 102, low: 99, close: 101, volume: 0 }
it('uses UTC chart times once and caps intraday/daily completion at session close', () => {
  expect(bookChartBars([b], 3600, session)[0]).toEqual({ ...b, closeTime: close })
  const daily = { ...b, time: Date.parse('2026-11-05T00:00:00Z') / 1000 }
  expect(bookChartBars([daily], 86400, session)[0].closeTime).toBe(close)
})
it('does not promote cached candles or fabricate quote freshness on a new history response', () => {
  const context = bookChartContext({
    symbol: 'TEST',
    exchange: 'NSE',
    intervalSeconds: 3600,
    now: close + 5,
    observedAt: close - 1,
    quoteObservedAt: close - 100,
    sourceReady: true,
    connected: true,
    tickSize: 0.05,
    session,
  })
  expect(analyzeBookGuide(bookChartBars([b], 3600, session), context).events).toEqual([])
  expect(context.quoteObservedAt).toBe(close - 100)
  expect(context.observedAt).toBe(close - 1)
  expect(context.marketOpen).toBe(false)
  const live = bookChartContext({ ...context, now: close - 100, marketOpen: undefined, session })
  expect(live.marketOpen).toBe(true)
  expect(bookChartContext({ ...context, sourceReady: false, session }).sourceReady).toBe(false)
})
it('requires explicit product kind and unit definition; never guesses a point value', () => {
  expect(validatedBookInstrument({})).toBeUndefined()
  expect(validatedBookInstrument({ valuePerPriceUnit: 1 })).toBeUndefined()
  expect(validatedBookInstrument({ kind: 'inverse', unitDefinition: 'contract' })).toEqual({
    kind: 'inverse',
    unitDefinition: 'contract',
  })
  expect(
    validatedBookInstrument({
      kind: 'linear',
      unitDefinition: 'contract',
      valuePerPriceUnit: 2,
      lotSize: 10,
    })?.valuePerPriceUnit
  ).toBe(2)
})

it('treats no-volume after-close bars as last-session references, with no fabricated live quote', () => {
  const context = bookChartContext({
    symbol: 'TEST',
    exchange: 'NSE',
    intervalSeconds: 3600,
    now: close + 1,
    observedAt: close + 1,
    quoteObservedAt: 0,
    sourceReady: true,
    connected: true,
    tickSize: 0.05,
    session,
  })
  const result = analyzeBookGuide(bookChartBars([b], 3600, session), context)
  expect(result.readiness).toBe('last-session')
  expect(result.unavailableReasons).not.toContain('Live quote is stale')
  const lost = analyzeBookGuide(bookChartBars([b], 3600, session), {
    ...context,
    sourceReady: false,
  })
  expect(lost.readiness).toBe('unavailable')
  expect(analyzeBookGuide(bookChartBars([b], 3600, session), context).readiness).toBe(
    'last-session'
  )
})

it('blocks linear index sizing and prevents underlying prices from being declared option premium', () => {
  const units = {
    kind: 'linear' as const,
    unitDefinition: 'option-premium' as const,
    chartPriceKind: 'premium' as const,
    valuePerPriceUnit: 1,
    quantityStep: 1,
  }
  expect(validatedBookInstrument(units, { symbol: 'NIFTY', exchange: 'NSE_INDEX' })?.kind).toBe(
    'index'
  )
  expect(
    validatedBookInstrument(units, { symbol: 'RELIANCE', exchange: 'NSE' })?.chartPriceKind
  ).toBe('underlying')
  expect(
    validatedBookInstrument(units, { symbol: 'NIFTY05NOV2624000CE', exchange: 'NFO' })
      ?.chartPriceKind
  ).toBe('premium')
})
