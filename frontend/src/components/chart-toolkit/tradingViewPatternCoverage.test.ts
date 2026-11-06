import { expect, it } from 'vitest'
import { TRADINGVIEW_CHART_PATTERNS } from './tradingViewPatternCoverage'
import { cryptoChartPattern } from './cryptoChartPatterns'
import { patternExplanation } from './patternExplanation'
it('covers all20source drawings through canonical detector IDs and simple hover meanings', () => {
  expect(TRADINGVIEW_CHART_PATTERNS).toHaveLength(20)
  expect(new Set(TRADINGVIEW_CHART_PATTERNS.map((p) => p.name)).size).toBe(20)
  for (const p of TRADINGVIEW_CHART_PATTERNS) {
    expect(p.ids.length).toBeGreaterThan(0)
    for (const id of p.ids) {
      expect(cryptoChartPattern(id)).toBeDefined()
      expect(patternExplanation(p.name, 'CALL', id)).toContain('Price may rise')
    }
  }
  expect(patternExplanation('Cypher', 'PUT', 'cypher')).toContain('XC')
  expect(patternExplanation('Livermore Cylinder', 'CALL', 'livermore-cylinder')).toContain(
    'Operational'
  )
})
