import { beforeEach, expect, it } from 'vitest'
import {
  CHART_STUDIES,
  readDeltaStudyPreferences,
  saveDeltaStudyPreferences,
} from './chartStudyChoices'

beforeEach(() => localStorage.clear())

it('provides one unified candle-pattern indicator, separate from probability', () => {
  expect(CHART_STUDIES.filter(([id]) => id === 'candle-patterns')).toHaveLength(1)
})

it.each([
  { fallback: [] },
  { fallback: ['neo-toolkit'] },
  { fallback: ['candle-patterns'] },
])('enables candle patterns on a new Delta chart with fallback $fallback', ({ fallback }) => {
  const selected = readDeltaStudyPreferences(fallback)
  expect(selected.filter((id) => id === 'candle-patterns')).toHaveLength(1)
  expect(selected).not.toContain('candle-probability')
})

it('restores the candle-pattern default when saved preferences are malformed', () => {
  localStorage.setItem('neo.delta.chart.indicators', '{invalid')
  expect(readDeltaStudyPreferences(['neo-toolkit'])).toContain('candle-patterns')
})

it('remembers manual off across future chart loads without changing non-Delta preferences', () => {
  localStorage.setItem('neo.native.chart.indicators', '["bb-chikou"]')
  const first = readDeltaStudyPreferences(['neo-toolkit'])
  saveDeltaStudyPreferences(first.filter((id) => id !== 'candle-patterns'))
  expect(readDeltaStudyPreferences(['neo-toolkit', 'candle-patterns'])).not.toContain(
    'candle-patterns'
  )
  expect(JSON.parse(localStorage.getItem('neo.native.chart.indicators')!)).toEqual(['bb-chikou'])
})
it('adds the source strategy guide once and respects the user turning it off later',()=>{
 const selected=readDeltaStudyPreferences([])
 expect(selected).toContain('video-strategy-guide')
 saveDeltaStudyPreferences(selected.filter(id=>id!=='video-strategy-guide'))
 expect(readDeltaStudyPreferences([])).not.toContain('video-strategy-guide')
})

it('registers the independent book guide without adding it to fresh or saved defaults',()=>{
 expect(CHART_STUDIES.filter(([id])=>id==='book-pattern-risk-guide')).toEqual([['book-pattern-risk-guide','Book patterns & risk · single plan']])
 expect(readDeltaStudyPreferences(['neo-toolkit'])).not.toContain('book-pattern-risk-guide')
 saveDeltaStudyPreferences(['bb-chikou','book-pattern-risk-guide'])
 expect(readDeltaStudyPreferences([])).toEqual(['bb-chikou','book-pattern-risk-guide'])
})
