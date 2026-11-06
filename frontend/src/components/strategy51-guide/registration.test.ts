import { expect, it } from 'vitest'
import {
  CHART_STUDIES,
  readDeltaStudyPreferences,
  saveDeltaStudyPreferences,
} from '../neo-desk/chartStudyChoices'
it('registers the separate51 study and preserves a prior saved off choice', () => {
  expect(CHART_STUDIES.filter(([id]) => id === 'strategies-51-guide')).toEqual([
    ['strategies-51-guide', '51 strategies · live guide'],
  ])
  saveDeltaStudyPreferences(['rsi'])
  expect(readDeltaStudyPreferences([])).toEqual(['rsi'])
})
