import { tradingViewChartPattern } from './tradingViewPatternCoverage'
/** Reference coverage in the existing unified detector, not a separate indicator.
 * https://fomo.family/blog/learn/crypto-chart-patterns-the-15-patterns-that-actually-matter
 * Geometric breakouts are observations, not measured probabilities.
 */
export const CRYPTO_CHART_PATTERNS: { name: string; ids: string[]; meaning: string }[] = [
  {
    name: 'Head and Shoulders',
    ids: ['head-and-shoulders'],
    meaning:
      'Three peaks form, with the middle peak highest. A close below the neckline between the peaks can mark a turn downward.',
  },
  {
    name: 'Inverse Head and Shoulders',
    ids: ['inverse-head-and-shoulders'],
    meaning:
      'Three troughs form, with the middle trough deepest. A close above the neckline between them can mark a turn upward.',
  },
  {
    name: 'Double Top',
    ids: ['double-top'],
    meaning:
      'Price fails near the same high twice. A close below the low between those peaks can mark a turn downward.',
  },
  {
    name: 'Double Bottom',
    ids: ['double-bottom'],
    meaning:
      'Price holds near the same low twice. A close above the high between those lows can mark a turn upward.',
  },
  {
    name: 'Rising Wedge',
    ids: ['rising-wedge'],
    meaning:
      'Price rises between two narrowing upward lines. A close below the lower line can signal weakening buying pressure.',
  },
  {
    name: 'Falling Wedge',
    ids: ['falling-wedge'],
    meaning:
      'Price falls between two narrowing downward lines. A close above the upper line can signal weakening selling pressure.',
  },
  {
    name: 'Bull Flag',
    ids: ['bull-flag'],
    meaning:
      'A sharp rise is followed by a small downward channel. A close above the channel may resume the earlier rise.',
  },
  {
    name: 'Bear Flag',
    ids: ['bear-flag'],
    meaning:
      'A sharp fall is followed by a small upward channel. A close below the channel may resume the earlier fall.',
  },
  {
    name: 'Bull Pennant',
    ids: ['bull-pennant'],
    meaning:
      'A sharp rise pauses inside a small narrowing triangle. A close above its upper line may resume the rise.',
  },
  {
    name: 'Ascending Triangle',
    ids: ['ascending-triangle'],
    meaning:
      'Higher lows press against a roughly flat upper level. A close outside either boundary gives the direction; an upward break is not guaranteed.',
  },
  {
    name: 'Descending Triangle',
    ids: ['descending-triangle'],
    meaning:
      'Lower highs press against a roughly flat lower level. A close outside either boundary gives the direction; a downward break is not guaranteed.',
  },
  {
    name: 'Cup and Handle',
    ids: ['cup-and-handle'],
    meaning:
      'Price makes a rounded U-shaped recovery and a smaller pullback near the rim. A close above the rim may continue the rise.',
  },
  {
    name: 'Symmetrical Triangle',
    ids: ['symmetrical-triangle'],
    meaning:
      'Lower highs and higher lows squeeze price into a narrowing triangle. The completed breakout can go either way.',
  },
  {
    name: 'Rectangle / Range',
    ids: ['rectangle'],
    meaning:
      'Price repeatedly moves between a flat upper and lower level. A close outside the range gives the possible next direction.',
  },
  {
    name: 'Diamond',
    ids: ['diamond-bottom', 'diamond-top'],
    meaning:
      'Swings first widen, then narrow into a diamond. The completed break outside its final boundary gives the direction.',
  },
]
export function cryptoChartPattern(id: string) {
  return (
    CRYPTO_CHART_PATTERNS.find((pattern) => pattern.ids.includes(id)) ?? tradingViewChartPattern(id)
  )
}
