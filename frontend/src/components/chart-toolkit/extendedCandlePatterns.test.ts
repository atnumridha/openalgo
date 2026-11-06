import { describe, expect, it } from 'vitest'
import type { Bar } from './model'
import { recognizeExtendedCandles } from './extendedCandlePatterns'

type OHLC = [number, number, number, number]
const bar = ([open, high, low, close]: OHLC, i = 0): Bar => ({
  open,
  high,
  low,
  close,
  time: 1000 + i * 60,
  volume: 10,
})
const down: OHLC[] = [
  [130, 132, 128, 130],
  [120, 122, 118, 120],
  [110, 112, 108, 110],
  [100, 102, 98, 100],
]
const mirror = ([o, h, l, c]: OHLC): OHLC => [200 - o, 200 - l, 200 - h, 200 - c]
const cases: [string, string, OHLC[], boolean?][] = [
  ['Bullish Marubozu', 'Bearish Marubozu', [[90, 100.1, 89.9, 100]]],
  [
    'Tweezer Bottom',
    'Tweezer Top',
    [
      [104, 105, 95, 96],
      [96, 103, 95.1, 102],
    ],
  ],
  [
    'Three White Soldiers',
    'Three Black Crows',
    [
      [90, 96.2, 89.8, 96],
      [94, 100.2, 93.8, 100],
      [98, 104.2, 97.8, 104],
    ],
  ],
  [
    'Three Inside Up',
    'Three Inside Down',
    [
      [104, 105, 93, 94],
      [96, 100, 95, 99],
      [99, 108, 98, 107],
    ],
  ],
  [
    'Three Outside Up',
    'Three Outside Down',
    [
      [100, 101, 95, 96],
      [95, 103, 94, 102],
      [101, 107, 100, 106],
    ],
  ],
  [
    'Bullish Kicker',
    'Bearish Kicker',
    [
      [100, 100.1, 89.9, 90],
      [103, 113.1, 102.9, 113],
    ],
  ],
  [
    'Bullish Abandoned Baby',
    'Bearish Abandoned Baby',
    [
      [110, 111, 99, 100],
      [95, 96, 94, 95.1],
      [101, 109, 100, 108],
    ],
  ],
  [
    'Bullish Three-Line Strike',
    'Bearish Three-Line Strike',
    [
      [90, 96.2, 89.8, 96],
      [94, 100.2, 93.8, 100],
      [98, 104.2, 97.8, 104],
      [105, 106, 88, 89],
    ],
    true,
  ],
  [
    'Morning Doji Star',
    'Evening Doji Star',
    [
      [110, 111, 99, 100],
      [97, 100.5, 95, 97.1],
      [99, 109, 98, 108],
    ],
  ],
]

describe('extended candlestick observations', () => {
  for (const [bullName, bearName, pattern, continuation] of cases) {
    for (const bearish of [false, true]) {
      const name = bearish ? bearName : bullName
      it(`recognizes ${name} and uses the pattern extreme`, () => {
        const prefix = continuation ? down.map(mirror) : down
        const values = [...prefix, ...pattern].map((v) => (bearish ? mirror(v) : v))
        const bars = values.map(bar)
        const match = recognizeExtendedCandles(bars).find((m) => m.name === name)
        expect(match).toMatchObject({ name, side: bearish ? 'PUT' : 'CALL' })
        expect(match?.pattern).toMatch(/^extended-/)
        expect(match?.extreme).toBe(
          bearish
            ? Math.max(...pattern.map((v) => 200 - v[2]))
            : Math.min(...pattern.map((v) => v[2]))
        )
      })
    }
  }
  it.each<[string, OHLC]>([
    ['Doji', [100, 105, 95, 100.2]],
    ['Spinning Top', [99, 105, 94, 101]],
  ])('keeps %s neutral even after a strong trend', (name, shape) => {
    for (const prefix of [down, down.map(mirror)]) {
      const matches = recognizeExtendedCandles([...prefix, shape].map(bar))
      expect(matches).toEqual([
        {
          name,
          pattern: name === 'Doji' ? 'extended-doji' : 'extended-spinning-top',
          side: 'NEUTRAL',
          extreme: shape[3],
        },
      ])
    }
  })
  it('requires all supplied pattern candles and never changes an earlier supplied prefix', () => {
    const values = [...down, ...cases[6][2]].map(bar)
    const before = recognizeExtendedCandles(values.slice(0, -1))
    expect(before.some((m) => m.name === 'Bullish Abandoned Baby')).toBe(false)
    expect(recognizeExtendedCandles(values).some((m) => m.name === 'Bullish Abandoned Baby')).toBe(
      true
    )
    expect(recognizeExtendedCandles(values.slice(0, -1))).toEqual(before)
  })
  it('requires prior trend for contextual multi-candle patterns', () => {
    const flat: OHLC[] = Array.from({ length: 4 }, () => [100, 102, 98, 100])
    for (const [name, , shape] of cases.slice(1)) {
      expect(
        recognizeExtendedCandles([...flat, ...shape].map(bar)).some((m) => m.name === name)
      ).toBe(false)
    }
  })
  it('does not call an overlapping reversal a kicker', () => {
    const values: OHLC[] = [...down, [100, 100.1, 89.9, 90], [99, 109.1, 98.9, 109]]
    expect(recognizeExtendedCandles(values.map(bar)).some((m) => m.name === 'Bullish Kicker')).toBe(
      false
    )
  })
  it('requires full wick isolation on both sides of an abandoned baby', () => {
    const values: OHLC[] = [...down, [110, 111, 99, 100], [97, 100, 94, 97.1], [101, 109, 100, 108]]
    expect(
      recognizeExtendedCandles(values.map(bar)).some((m) => m.name === 'Bullish Abandoned Baby')
    ).toBe(false)
  })
  it('rejects soldiers with descending closes and tweezers with unequal lows', () => {
    const soldiers: OHLC[] = [
      ...down,
      [90, 96.2, 89.8, 96],
      [94, 100.2, 93.8, 100],
      [92, 98.2, 91.8, 98],
    ]
    expect(
      recognizeExtendedCandles(soldiers.map(bar)).some((m) => m.name === 'Three White Soldiers')
    ).toBe(false)
    const tweezers: OHLC[] = [...down, [104, 105, 95, 96], [96, 103, 92, 102]]
    expect(
      recognizeExtendedCandles(tweezers.map(bar)).some((m) => m.name === 'Tweezer Bottom')
    ).toBe(false)
  })
  it('retains a contextual pattern from the existing guide', () => {
    expect(
      recognizeExtendedCandles([...down, [100, 103, 90, 102] as OHLC].map(bar))
    ).toContainEqual({ name: 'Hammer', side: 'CALL', pattern: 'guide-hammer', extreme: 90 })
  })
  it('returns no observations for empty history', () => {
    expect(recognizeExtendedCandles([])).toEqual([])
  })
})
