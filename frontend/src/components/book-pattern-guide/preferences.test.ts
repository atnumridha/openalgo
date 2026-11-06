import { beforeEach, expect, it } from 'vitest'
import {
  bookInstrumentForScope,
  BOOK_PREFERENCES_KEY,
  readBookPreferences,
  saveBookPreferences,
} from './preferences'
beforeEach(() => localStorage.clear())
it('keeps defaults independent and does not invent money units', () => {
  localStorage.setItem('neo.native.chart.indicators', '["neo-toolkit"]')
  const p = readBookPreferences()
  expect(p.settings.labelLookback).toBe(10)
  expect(p.settings.showPending).toBe(false)
  expect(p.settings.riskPercent).toBe(0.25)
  expect(p.instrument).toEqual({})
  saveBookPreferences({ ...p, settings: { ...p.settings, equity: 250000, showPending: true } })
  expect(readBookPreferences().settings.equity).toBe(250000)
  expect(localStorage.getItem('neo.native.chart.indicators')).toBe('["neo-toolkit"]')
  expect(BOOK_PREFERENCES_KEY).toBe('neo.book-pattern-risk-guide.v1')
})
it('rejects malformed storage and unsafe typed settings without affecting old keys', () => {
  localStorage.setItem(
    BOOK_PREFERENCES_KEY,
    JSON.stringify({
      settings: { equity: '100', showPending: 'yes', maxDrawings: 9999 },
      instrument: { kind: 'magic', valuePerPriceUnit: 1 },
    })
  )
  expect(localStorage.getItem(BOOK_PREFERENCES_KEY)).toContain('magic')
  const p = readBookPreferences()
  expect(p.settings.equity).toBe(0)
  expect(p.settings.showPending).toBe(false)
  expect(p.settings.maxDrawings).toBe(40)
  expect(p.instrument).toEqual({})
  localStorage.setItem(BOOK_PREFERENCES_KEY, '{')
  expect(localStorage.getItem(BOOK_PREFERENCES_KEY)).toBe('{')
  expect(readBookPreferences().settings.equity).toBe(0)
})

it('scopes explicitly entered sizing units to the exact symbol and exchange', () => {
  const p = readBookPreferences()
  saveBookPreferences({
    ...p,
    instrumentScope: 'DELTA:BTCUSD',
    instrument: {
      kind: 'linear',
      unitDefinition: 'contract',
      valuePerPriceUnit: 0.001,
      quantityStep: 1,
    },
  })
  expect(bookInstrumentForScope(readBookPreferences(), 'DELTA:BTCUSD').valuePerPriceUnit).toBe(
    0.001
  )
  expect(bookInstrumentForScope(readBookPreferences(), 'NFO:NIFTYCE')).toEqual({})
  expect(bookInstrumentForScope(readBookPreferences(), 'NSE_INDEX:NIFTY')).toEqual({})
})
