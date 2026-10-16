import { describe, expect, it } from 'vitest'
import { type FvgCandle, fairValueGaps } from './fairValueGaps'

// Candle timestamps use the chart's IST-shifted axis.
const start = Date.parse('2026-10-15T09:15:00Z') / 1000
const interval = 60
const utc = (axisTime: number) => axisTime - 19800

function candle(offset: number, low: number, high: number): FvgCandle {
  return { time: start + offset * interval, open: low, high, low, close: high }
}

const bullish = [candle(0, 95, 100), candle(1, 99, 111), candle(2, 105, 115)]

describe('Fair value gaps', () => {
  it('confirms a bullish three-wick gap at the third candle close', () => {
    expect(fairValueGaps(bullish, interval, utc(start + 180))).toEqual([
      {
        id: expect.any(String),
        direction: 'bullish',
        lower: 100,
        upper: 105,
        startTime: start + 60,
        confirmedAt: start + 180,
        touched: false,
      },
    ])
  })

  it('waits for the third candle to close before creating a gap', () => {
    expect(fairValueGaps(bullish, interval, utc(start + 179.9))).toEqual([])
  })

  it('does not inspect a future candle when creating a gap', () => {
    expect(fairValueGaps(bullish, interval, utc(start + 119))).toEqual([])
  })

  it('confirms bearish gaps using the first and third candle wicks', () => {
    const bearish = [candle(0, 110, 120), candle(1, 99, 115), candle(2, 95, 105)]

    expect(fairValueGaps(bearish, interval, utc(start + 180))).toEqual([
      {
        id: expect.any(String),
        direction: 'bearish',
        lower: 105,
        upper: 110,
        startTime: start + 60,
        confirmedAt: start + 180,
        touched: false,
      },
    ])
  })

  it('marks a bullish gap touched without shrinking its original bounds', () => {
    const input = [...bullish, candle(3, 103, 112), candle(4, 104, 112)]

    expect(fairValueGaps(input, interval, utc(start + 300))).toEqual([
      expect.objectContaining({ lower: 100, upper: 105, touched: true }),
    ])
  })

  it('removes a bullish gap when a later candle reaches its lower bound', () => {
    expect(fairValueGaps([...bullish, candle(3, 100, 112)], interval, utc(start + 240))).toEqual([])
  })

  it('uses an observed forming candle to touch and fill confirmed gaps', () => {
    expect(fairValueGaps([...bullish, candle(3, 103, 112)], interval, utc(start + 181))).toEqual([
      expect.objectContaining({ lower: 100, upper: 105, touched: true }),
    ])
    expect(fairValueGaps([...bullish, candle(3, 99, 112)], interval, utc(start + 181))).toEqual([])
  })

  it('ignores future candles that would otherwise fill a confirmed gap', () => {
    expect(fairValueGaps([...bullish, candle(4, 99, 112)], interval, utc(start + 181))).toEqual([
      expect.objectContaining({ lower: 100, upper: 105, touched: false }),
    ])
  })

  it('requires entry inside the gap to count as a touch', () => {
    expect(fairValueGaps([...bullish, candle(3, 105, 112)], interval, utc(start + 240))).toEqual([
      expect.objectContaining({ touched: false }),
    ])
  })

  it('touches and fills bearish gaps from their lower boundary', () => {
    const bearish = [candle(0, 110, 120), candle(1, 99, 115), candle(2, 95, 105)]

    expect(fairValueGaps([...bearish, candle(3, 99, 105)], interval, utc(start + 240))).toEqual([
      expect.objectContaining({ lower: 105, upper: 110, touched: false }),
    ])
    expect(fairValueGaps([...bearish, candle(3, 99, 108)], interval, utc(start + 181))).toEqual([
      expect.objectContaining({ lower: 105, upper: 110, touched: true }),
    ])
    expect(fairValueGaps([...bearish, candle(3, 99, 110)], interval, utc(start + 240))).toEqual([])
  })

  it('does not form a gap across a missing interval', () => {
    const missingMiddle = [candle(0, 95, 100), candle(2, 99, 111), candle(3, 105, 115)]
    const missingThird = [candle(0, 95, 100), candle(1, 99, 111), candle(3, 105, 115)]

    expect(fairValueGaps(missingMiddle, interval, utc(start + 240))).toEqual([])
    expect(fairValueGaps(missingThird, interval, utc(start + 240))).toEqual([])
  })

  it('does not form a gap across the IST session date boundary', () => {
    const midnight = Date.parse('2026-10-16T00:00:00Z') / 1000
    const input = bullish.map((bar, index) => ({ ...bar, time: midnight - 120 + index * 60 }))

    expect(fairValueGaps(input, interval, utc(midnight + 60))).toEqual([])
  })

  it.each([
    { open: 101 },
    { close: 94 },
    { high: 94 },
    { low: 101 },
    { open: Number.NaN },
    { close: Number.POSITIVE_INFINITY },
    { time: Number.NaN },
  ])('rejects a triple containing invalid OHLC or time: %o', (invalid) => {
    expect(
      fairValueGaps(
        [{ ...bullish[0], ...invalid }, ...bullish.slice(1)],
        interval,
        utc(start + 180)
      )
    ).toEqual([])
  })

  it('ignores invalid later candles when updating an active gap', () => {
    const invalid = { ...candle(3, 90, 112), open: 120 }

    expect(fairValueGaps([...bullish, invalid], interval, utc(start + 240))).toEqual([
      expect.objectContaining({ lower: 100, upper: 105, touched: false }),
    ])
  })

  it.each([
    0,
    -60,
    Number.NaN,
    Number.POSITIVE_INFINITY,
  ])('returns no gaps for an invalid interval: %s', (invalidInterval) => {
    expect(fairValueGaps(bullish, invalidInterval, utc(start + 180))).toEqual([])
  })

  it.each([
    Number.NaN,
    Number.POSITIVE_INFINITY,
  ])('returns no gaps for an invalid clock: %s', (now) => {
    expect(fairValueGaps(bullish, interval, now)).toEqual([])
  })

  it('returns active gaps chronologically without mutating unsorted input', () => {
    const input = Object.freeze(
      [candle(4, 115, 125), bullish[0], bullish[2], candle(3, 113, 121), bullish[1]].map((bar) =>
        Object.freeze(bar)
      )
    )

    expect(fairValueGaps(input, interval, utc(start + 300))).toEqual([
      expect.objectContaining({ lower: 100, upper: 105, startTime: start + 60 }),
      expect.objectContaining({ lower: 111, upper: 113, startTime: start + 120 }),
    ])
    expect(input.map((bar) => bar.time)).toEqual([
      start + 240,
      start,
      start + 120,
      start + 180,
      start + 60,
    ])
  })

  it('limits gap detection to the most recent 600 observed candles', () => {
    const input = [
      ...bullish,
      ...Array.from({ length: 598 }, (_, index) => candle(index + 3, 105, 115)),
    ]

    expect(fairValueGaps(input, interval, utc(start + 601 * 60))).toEqual([])
  })

  it('does not reach outside the 600-candle window when recent OHLC is invalid', () => {
    const invalid = Array.from({ length: 598 }, (_, index) => ({
      ...candle(index + 3, 105, 115),
      open: 120,
    }))

    expect(fairValueGaps([...bullish, ...invalid], interval, utc(start + 601 * 60))).toEqual([])
  })

  it('does not let future candles displace the observed 600-candle window', () => {
    const future = Array.from({ length: 600 }, (_, index) => candle(index + 3, 99, 115))

    expect(fairValueGaps([...bullish, ...future], interval, utc(start + 180 - 0.1))).toEqual([])
    expect(fairValueGaps([...bullish, ...future.slice(1)], interval, utc(start + 180))).toEqual([
      expect.objectContaining({ lower: 100, upper: 105, touched: false }),
    ])
  })
})
