import { describe, expect, it } from 'vitest'
import type { Bar } from './model'
import { recognizeArchiveCandlesA } from './archiveCandlesA'
type OHLC = [number, number, number, number]
const down: OHLC[] = [
  [130, 132, 128, 130],
  [120, 122, 118, 120],
  [110, 112, 108, 110],
  [100, 102, 98, 100],
]
const bars = (rows: OHLC[]): Bar[] =>
  rows.map(([open, high, low, close], i) => ({
    open,
    high,
    low,
    close,
    time: 1000 + i * 60,
    volume: 10,
  }))
const mirror = ([o, h, l, c]: OHLC): OHLC => [300 - o, 300 - l, 300 - h, 300 - c]
const names = (rows: OHLC[]) => recognizeArchiveCandlesA(bars(rows)).map((x) => x.name)
const cases: [string, string, OHLC[], boolean?][] = [
  ['Bullish Belt Hold', 'Bearish Belt Hold', [[90, 101, 90, 100]]],
  [
    'Bullish Harami Cross',
    'Bearish Harami Cross',
    [
      [104, 105, 93, 94],
      [98, 100, 96, 98.1],
    ],
  ],
  [
    'Bullish Doji Star',
    'Bearish Doji Star',
    [
      [104, 105, 93, 94],
      [91, 92, 90, 91],
    ],
  ],
  ['Bullish Pin Bar', 'Bearish Pin Bar', [[95, 96, 86, 94]]],
  [
    'Matching Low',
    'Matching High',
    [
      [104, 105, 93, 94],
      [100, 101, 93, 94.1],
    ],
  ],
  [
    'Homing Pigeon',
    'Descending Hawk',
    [
      [104, 105, 93, 94],
      [100, 101, 96, 97],
    ],
  ],
  [
    'Bullish Counterattack / Meeting Lines',
    'Bearish Counterattack / Meeting Lines',
    [
      [104, 105, 93, 94],
      [89, 95, 88, 94.1],
    ],
  ],
  [
    'Bullish Separating Lines',
    'Bearish Separating Lines',
    [
      [95, 96, 88, 89],
      [95, 105, 95, 104],
    ],
    true,
  ],
  [
    'In Neck',
    'Mirrored In Neck',
    [
      [104, 105, 93, 94],
      [91, 95, 90, 94.3],
    ],
  ],
  [
    'On Neck',
    'Mirrored On Neck',
    [
      [104, 105, 93, 94],
      [91, 94, 90, 93.1],
    ],
  ],
  [
    'Thrusting',
    'Mirrored Thrusting',
    [
      [104, 105, 93, 94],
      [91, 98, 90, 97],
    ],
  ],
  [
    'Rising Window',
    'Falling Window',
    [
      [94, 96, 93, 95],
      [98, 102, 97, 101],
    ],
    true,
  ],
  [
    'Bullish Island Reversal',
    'Bearish Island Reversal',
    [
      [104, 105, 93, 94],
      [89, 90, 87, 88],
      [94, 103, 93, 102],
    ],
  ],
]
describe('archive candle families A', () => {
  for (const [name, opposite, shape, continuation] of cases)
    it(`recognizes ${name} and reflection`, () => {
      const rows = [...(continuation ? down.map(mirror) : down), ...shape]
      expect(names(rows)).toContain(name)
      expect(names(rows.map(mirror))).toContain(opposite)
      const neck = ['In Neck', 'On Neck', 'Thrusting'].includes(name)
      expect(recognizeArchiveCandlesA(bars(rows)).find((x) => x.name === name)?.side).toBe(
        neck ? 'PUT' : 'CALL'
      )
      expect(
        recognizeArchiveCandlesA(bars(rows.map(mirror))).find((x) => x.name === opposite)?.side
      ).toBe(neck ? 'CALL' : 'PUT')
    })
  it.each([
    ['High Wave', [100, 110, 90, 102]],
    ['Long Legged Doji', [100, 110, 90, 100.1]],
    ['Rickshaw Man', [100, 110, 90, 100.1]],
    ['Long Line', [90, 101, 89, 100]],
    ['Short Line', [100, 100.55, 99.95, 100.5]],
  ] as [string, OHLC][])('neutral %s', (name, row) => {
    const context: OHLC[] =
      name === 'Short Line'
        ? [
            [132, 133, 127, 128],
            [122, 123, 117, 118],
            [112, 113, 107, 108],
            [102, 103, 97, 98],
          ]
        : down
    expect(
      recognizeArchiveCandlesA(bars([...context, row])).find((x) => x.name === name)?.side
    ).toBe('NEUTRAL')
  })
  it('uses trend for northern and southern doji', () => {
    expect(names([...down, [95, 100, 90, 95]])).toContain('Southern Doji')
    expect(names([...down, [95, 100, 90, 95]].map(mirror))).toContain('Northern Doji')
  })
  it.each([
    [
      'Inside Bar',
      [
        [95, 105, 85, 100],
        [96, 102, 88, 98],
      ],
    ],
    [
      'Outside Bar',
      [
        [95, 101, 90, 100],
        [96, 105, 85, 98],
      ],
    ],
  ] as [string, OHLC[]][])('neutral %s', (name, rows) => {
    expect(
      recognizeArchiveCandlesA(bars([...down, ...rows])).find((x) => x.name === name)?.side
    ).toBe('NEUTRAL')
  })
  it('requires context', () => {
    for (const [, , shape] of cases)
      expect(recognizeArchiveCandlesA(bars(shape)).filter((x) => x.side !== 'NEUTRAL')).toEqual([])
  })
  it('requires strict window and both island gaps', () => {
    expect(names([...down.map(mirror), [94, 98, 93, 95], [98, 102, 98, 101]])).not.toContain(
      'Rising Window'
    )
    expect(
      names([...down, [104, 105, 93, 94], [89, 94, 87, 88], [94, 103, 93, 102]])
    ).not.toContain('Bullish Island Reversal')
  })
  it('only inspects final patterns without mutation', () => {
    const input = bars([...down, [90, 101, 90, 100]]),
      copy = structuredClone(bars([...down, [90, 101, 90, 100]]))
    expect(recognizeArchiveCandlesA(input).some((x) => x.name === 'Bullish Belt Hold')).toBe(true)
    expect(input).toEqual(copy)
    expect(names([...down, [90, 101, 90, 100], [100, 104, 98, 101]])).not.toContain(
      'Bullish Belt Hold'
    )
  })
  it('rejects invalid input', () => {
    for (const patch of [
      { open: NaN },
      { low: 0 },
      { high: 80 },
      { time: 0 },
      { close: Infinity },
    ]) {
      const input = bars([...down, [90, 101, 90, 100]])
      Object.assign(input.at(-1)!, patch)
      expect(recognizeArchiveCandlesA(input)).toEqual([])
    }
    expect(recognizeArchiveCandlesA([])).toEqual([])
  })
})
