import { beforeEach, expect, it } from 'vitest'
import {
  readStrategy51Preferences,
  saveStrategy51Preferences,
  normalizeStrategy51Settings,
  STRATEGY51_KEY,
} from './preferences'
beforeEach(() => localStorage.clear())
it('defaults to a compact latest10 confirmed-only study and never changes other study storage', () => {
  localStorage.setItem('neo.book-guide.v1', 'old')
  const s = readStrategy51Preferences()
  expect(s).toMatchObject({
    selected: 'auto',
    showPending: false,
    fullHistory: false,
    showOtherSetups: false,
    cleanChart: true,
    labelLookback: 10,
    equity: 0,
    riskPercent: 0.25,
  })
  saveStrategy51Preferences({ ...s, selected: '7.7' })
  expect(readStrategy51Preferences().selected).toBe('7.7')
  expect(localStorage.getItem('neo.book-guide.v1')).toBe('old')
})
it('handles malformed storage and hostile numeric/instrument settings', () => {
  localStorage.setItem(STRATEGY51_KEY, '{')
  expect(readStrategy51Preferences().selected).toBe('auto')
  const s = normalizeStrategy51Settings({
    selected: 'delete-everything',
    targetR: Infinity,
    riskPercent: -10,
    labelLookback: 10000,
    voFast: 0,
    supplied: [null],
  })
  expect(s.selected).toBe('auto')
  expect(s.targetR).toBe(3)
  expect(s.riskPercent).toBe(0.25)
  expect(s.labelLookback).toBeLessThanOrEqual(100)
  expect(s.voFast).toBeGreaterThan(0)
  expect(s.supplied).toEqual([])
})

it('temporarily isolates the new study without rewriting saved indicator choices', async () => {
  const { strategy51VisibleStudies } = await import('./visibility')
  const saved = ['book-pattern-risk-guide', 'ma-signals', 'rsi', 'volume', 'strategies-51-guide']
  expect(strategy51VisibleStudies(saved, readStrategy51Preferences())).toEqual([
    'volume',
    'strategies-51-guide',
  ])
  expect(saved).toHaveLength(5)
  saveStrategy51Preferences({
    ...readStrategy51Preferences(),
    cleanChart: false,
    showOtherSetups: true,
  })
  expect(strategy51VisibleStudies(saved, readStrategy51Preferences())).toEqual(saved)
  expect(strategy51VisibleStudies(['ma-signals'], readStrategy51Preferences())).toEqual([
    'ma-signals',
  ])
})
