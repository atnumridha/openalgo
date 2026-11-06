import { expect, it } from 'vitest'
import { recognizePattern } from './candlePatterns'
import type { Bar } from './model'
const candle = (open: number, high: number, low: number, close: number): Bar => ({
  time: 0,
  open,
  high,
  low,
  close,
  volume: 0,
})
const prefix = (bull: boolean) =>
  (bull ? [130, 120, 110, 100] : [70, 80, 90, 100]).map((close) =>
    candle(close, close + 1, close - 1, close)
  )
const cases: [string, 'CALL' | 'PUT', Bar[]][] = [
  ['Hammer', 'CALL', [candle(100, 103, 90, 102)]],
  ['Hanging Man', 'PUT', [candle(100, 103, 90, 102)]],
  ['Inverted Hammer', 'CALL', [candle(100, 112, 99, 102)]],
  ['Shooting Star', 'PUT', [candle(100, 112, 99, 102)]],
  ['Dragonfly Doji', 'CALL', [candle(100, 100.3, 90, 100.2)]],
  ['Gravestone Doji', 'PUT', [candle(100, 110, 99.9, 100.2)]],
  ['Bullish Engulfing', 'CALL', [candle(104, 105, 99, 100), candle(99, 106, 98, 105)]],
  ['Bearish Engulfing', 'PUT', [candle(100, 105, 99, 104), candle(105, 106, 98, 99)]],
  ['Piercing Pattern', 'CALL', [candle(104, 105, 95, 96), candle(95, 102, 94, 101)]],
  ['Dark Cloud Cover', 'PUT', [candle(96, 105, 95, 104), candle(105, 106, 98, 99)]],
  ['Bullish Harami', 'CALL', [candle(104, 105, 95, 96), candle(98, 102, 97, 101)]],
  ['Bearish Harami', 'PUT', [candle(96, 105, 95, 104), candle(102, 103, 98, 99)]],
  [
    'Morning Star',
    'CALL',
    [candle(110, 111, 99, 100), candle(100, 102, 99, 101), candle(101, 108, 100, 107)],
  ],
  [
    'Evening Star',
    'PUT',
    [candle(100, 111, 99, 110), candle(110, 111, 108, 109), candle(109, 110, 102, 103)],
  ],
]
it.each(cases)('recognizes %s from the supplied reversal guide', (name, side, pattern) => {
  const bars = [...prefix(side === 'CALL'), ...pattern].map((bar, i) => ({
    ...bar,
    time: 1000 + i * 60,
  }))
  expect(recognizePattern(bars, 'pinterest-reversals')).toMatchObject({ name, side })
})
it('uses the preceding trend to distinguish the same long-wick shape', () => {
  const shape = candle(100, 103, 90, 102)
  expect(recognizePattern([...prefix(true), shape], 'pinterest-reversals')?.name).toBe('Hammer')
  expect(recognizePattern([...prefix(false), shape], 'pinterest-reversals')?.name).toBe(
    'Hanging Man'
  )
  expect(
    recognizePattern([...Array(4).fill(candle(100, 101, 99, 100)), shape], 'pinterest-reversals')
  ).toBeNull()
})
it('rejects malformed candles and isolates guide evidence from older generic-pattern estimates', () => {
  expect(
    recognizePattern([...prefix(true), candle(100, 95, 90, 102)], 'pinterest-reversals')
  ).toBeNull()
  const match = recognizePattern(
    [...prefix(true), candle(104, 105, 99, 100), candle(99, 106, 98, 105)],
    'pinterest-reversals'
  )!
  expect(match.pattern).toBe('guide-engulfing')
  expect(
    recognizePattern(
      [...prefix(true), candle(104, 105, 99, 100), candle(99, 106, 98, 105)],
      'engulfing'
    )?.pattern
  ).toBe('engulfing')
})
