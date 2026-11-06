import type { BookBar, BookContext } from './types'

export function bar(open: number, high: number, low: number, close: number, index = 0): BookBar {
  return { time: 1_700_000_000 + index * 60, open, high, low, close, volume: 100 }
}
export function timed(rows: BookBar[]): BookBar[] {
  return rows.map((b, i) => ({ ...b, time: 1_700_000_000 + i * 60 }))
}
export function trendBars(side: 'long' | 'short', count = 70): BookBar[] {
  return Array.from({ length: count }, (_, i) => {
    const p = side === 'long' ? 60 + i * 0.5 : 140 - i * 0.5
    return bar(
      p,
      p + (side === 'long' ? 0.6 : 0.2),
      p - (side === 'long' ? 0.2 : 0.6),
      p + (side === 'long' ? 0.3 : -0.3),
      i
    )
  })
}
export const TEST_CONTEXT: BookContext = {
  symbol: 'TEST',
  intervalSeconds: 60,
  now: 1_800_000_000,
  observedAt: 1_800_000_000,
  sourceReady: true,
  connected: true,
  marketOpen: true,
  chartType: 'standard',
  tickSize: 0.01,
  instrument: {
    kind: 'linear',
    unitDefinition: 'underlying',
    accountCurrency: 'INR',
    quoteCurrency: 'INR',
    valuePerPriceUnit: 1,
    quantityStep: 1,
    lotSize: 1,
  },
}
export const CANDLE_FIXTURES: {
  id: string
  rows: BookBar[]
  side: 'long' | 'short' | 'neutral'
  stop: number
}[] = [
  {
    id: 'rising-three-methods',
    side: 'long',
    stop: 102,
    rows: [
      bar(100, 111, 99, 110),
      bar(108, 109, 104, 107),
      bar(107, 108, 103, 106),
      bar(106, 107, 102, 105),
      bar(105, 113, 104, 112),
    ],
  },
  {
    id: 'falling-three-methods',
    side: 'short',
    stop: 108,
    rows: [
      bar(110, 111, 99, 100),
      bar(102, 106, 101, 103),
      bar(103, 107, 102, 104),
      bar(104, 108, 103, 105),
      bar(105, 106, 97, 98),
    ],
  },
  {
    id: 'tweezer-bottom',
    side: 'long',
    stop: 99,
    rows: [bar(105, 106, 99, 100), bar(100, 107, 99, 106)],
  },
  {
    id: 'tweezer-top',
    side: 'short',
    stop: 111,
    rows: [bar(105, 111, 104, 110), bar(110, 111, 103, 104)],
  },
  {
    id: 'three-white-soldiers',
    side: 'long',
    stop: 99,
    rows: [bar(100, 106.2, 99, 106), bar(105, 112.2, 104, 112), bar(111, 118.2, 110, 118)],
  },
  {
    id: 'three-black-crows',
    side: 'short',
    stop: 121,
    rows: [bar(120, 121, 113.8, 114), bar(115, 116, 107.8, 108), bar(109, 110, 101.8, 102)],
  },
  {
    id: 'bull-harami',
    side: 'long',
    stop: 103,
    rows: [bar(110, 111, 99, 100), bar(104.5, 107, 103, 105.5)],
  },
  {
    id: 'bear-harami',
    side: 'short',
    stop: 111,
    rows: [bar(100, 111, 99, 110), bar(105.5, 107, 103, 104.5)],
  },
  {
    id: 'piercing-line',
    side: 'long',
    stop: 98,
    rows: [bar(110, 111, 99, 100), bar(99, 109, 98, 107)],
  },
  {
    id: 'dark-cloud-cover',
    side: 'short',
    stop: 112,
    rows: [bar(100, 111, 99, 110), bar(111, 112, 101, 103)],
  },
  {
    id: 'morning-star',
    side: 'long',
    stop: 96,
    rows: [bar(110, 111, 99, 100), bar(98, 99, 96, 97.5), bar(99, 109, 98, 108)],
  },
  {
    id: 'evening-star',
    side: 'short',
    stop: 114,
    rows: [bar(100, 111, 99, 110), bar(112, 114, 111, 112.5), bar(111, 112, 101, 102)],
  },
  {
    id: 'bull-engulfing',
    side: 'long',
    stop: 98,
    rows: [bar(106, 108, 99, 100), bar(99, 109, 98, 107)],
  },
  {
    id: 'bear-engulfing',
    side: 'short',
    stop: 112,
    rows: [bar(104, 111, 102, 110), bar(111, 112, 101, 103)],
  },
  { id: 'hammer', side: 'long', stop: 100, rows: [bar(108, 110.1, 100, 110)] },
  { id: 'hanging-man', side: 'short', stop: 110.1, rows: [bar(108, 110.1, 100, 110)] },
  { id: 'inverted-hammer', side: 'long', stop: 99.9, rows: [bar(100, 110, 99.9, 102)] },
  { id: 'shooting-star', side: 'short', stop: 110, rows: [bar(100, 110, 99.9, 102)] },
  { id: 'bull-marubozu', side: 'long', stop: 100, rows: [bar(100, 110, 100, 110)] },
  { id: 'bear-marubozu', side: 'short', stop: 110, rows: [bar(110, 110, 100, 100)] },
  { id: 'doji', side: 'neutral', stop: 95, rows: [bar(100, 105, 95, 100.5)] },
  { id: 'long-legged-doji', side: 'neutral', stop: 95, rows: [bar(100, 105, 95, 100.5)] },
  { id: 'dragonfly-doji', side: 'neutral', stop: 90, rows: [bar(100, 100.5, 90, 100.2)] },
  { id: 'gravestone-doji', side: 'neutral', stop: 99.5, rows: [bar(100, 110, 99.5, 100.2)] },
  {
    id: 'double-doji',
    side: 'neutral',
    stop: 95,
    rows: [bar(100, 105, 95, 100.5), bar(100, 105, 95, 100.5)],
  },
  { id: 'spinning-top', side: 'neutral', stop: 95, rows: [bar(99, 105, 95, 101)] },
]
