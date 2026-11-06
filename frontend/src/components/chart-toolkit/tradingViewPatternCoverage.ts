/** The 20 drawings, including the mirrored H&S/cup forms, in the supplied image.
 * Aliases point at ONE existing detector; this is coverage metadata, not a second indicator. */
export const TRADINGVIEW_PATTERN_SOURCE =
  'https://www.tradingview.com/chart/BTCUSDT/6puZ59qW-TOP-20-Key-Patterns-cheat-sheet/'
export const TRADINGVIEW_CHART_PATTERNS: { name: string; ids: string[]; meaning: string }[] = [
  {
    name: 'Pennant',
    ids: ['bull-pennant', 'bear-pennant'],
    meaning:
      'A sharp move pauses inside a narrowing range. The completed breakout gives the direction.',
  },
  {
    name: 'Megaphone',
    ids: ['broadening-wedge'],
    meaning:
      'Swings widen between rising highs and falling lows. A completed close outside either boundary confirms the observed breakout.',
  },
  {
    name: 'Bear Flag',
    ids: ['bear-flag'],
    meaning: 'A decline pauses in a small rising channel, then closes below it.',
  },
  {
    name: 'Bull Flag',
    ids: ['bull-flag'],
    meaning: 'A rise pauses in a small falling channel, then closes above it.',
  },
  {
    name: 'Channel',
    ids: ['channel', 'rectangle'],
    meaning:
      'Price moves between two roughly parallel boundaries. A completed outside close gives the breakout direction.',
  },
  {
    name: 'Symmetrical Triangle',
    ids: ['symmetrical-triangle'],
    meaning: 'Both boundaries narrow. The close can break either way.',
  },
  {
    name: 'Descending Triangle',
    ids: ['descending-triangle'],
    meaning: 'Lower highs approach a flat floor. Direction follows the completed breakout.',
  },
  {
    name: 'Ascending Triangle',
    ids: ['ascending-triangle'],
    meaning: 'Higher lows approach a flat ceiling. Direction follows the completed breakout.',
  },
  {
    name: 'Diamond',
    ids: ['diamond-bottom', 'diamond-top'],
    meaning:
      'Swings expand and then contract. A completed boundary break confirms the observed direction.',
  },
  {
    name: 'Livermore Cylinder',
    ids: ['livermore-cylinder'],
    meaning:
      'Operational expanding-range pattern: price swings between sloping boundaries that spread apart, then closes outside. The sketch does not establish accumulation or a guaranteed reversal.',
  },
  {
    name: 'Double Top',
    ids: ['double-top'],
    meaning:
      'Two similar peaks fail; a close below the intervening low confirms the downward break.',
  },
  {
    name: 'Double Bottom',
    ids: ['double-bottom'],
    meaning: 'Two similar lows hold; a close above the intervening high confirms the upward break.',
  },
  {
    name: 'Head and Shoulders',
    ids: ['head-and-shoulders'],
    meaning:
      'A higher middle peak sits between two shoulders. A neckline close confirms the downward break.',
  },
  {
    name: 'Inverse Head and Shoulders',
    ids: ['inverse-head-and-shoulders'],
    meaning:
      'A deeper middle low sits between two shoulders. A neckline close confirms the upward break.',
  },
  {
    name: 'Cup and Handle',
    ids: ['cup-and-handle'],
    meaning: 'A rounded recovery and small pullback close above their rim.',
  },
  {
    name: 'Inverse Cup and Handle',
    ids: ['inverse-cup-and-handle'],
    meaning: 'A rounded top and small rebound close below their floor.',
  },
  {
    name: 'Falling Wedge',
    ids: ['falling-wedge'],
    meaning: 'Two falling boundaries narrow; an upward close confirms the observed reversal.',
  },
  {
    name: 'Rising Wedge',
    ids: ['rising-wedge'],
    meaning: 'Two rising boundaries narrow; a downward close confirms the observed reversal.',
  },
  {
    name: 'Gartley',
    ids: ['gartley'],
    meaning:
      'Five confirmed swings meet Fibonacci ratios, including B near 61.8% and D near 78.6% of XA. A later reversal close confirms the label; the drawing alone is insufficient.',
  },
  {
    name: 'Cypher',
    ids: ['cypher'],
    meaning:
      'Five swings meet Fibonacci ratios: C extends beyond A, and D retraces about 78.6% of XC. A later reversal close confirms the label; D is measured from XC, not XA.',
  },
]
export function tradingViewChartPattern(id: string) {
  return TRADINGVIEW_CHART_PATTERNS.find((p) => p.ids.includes(id))
}
