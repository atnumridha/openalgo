import { expect, it } from 'vitest'
import { finalPatternEvents } from './finalPatternEngine'
import { archivePatternEvents } from './archivePatternEngine'
import type { Bar } from './model'
const bars: Bar[] = [
  [130, 132, 128, 130],
  [120, 122, 118, 120],
  [110, 112, 108, 110],
  [100, 102, 98, 100],
  [90, 101, 90, 100],
  [100, 104, 99, 103],
].map(([open, high, low, close], i) => ({
  time: 1000 + i * 60,
  open,
  high,
  low,
  close,
  volume: 10,
}))
it('combines all confirmed families through one final entry point and omits raw directional hints', () => {
  const all = archivePatternEvents(bars, 'all', 60)
  expect(all.some((e) => e.side !== 'NEUTRAL' && !e.confirmed)).toBe(true)
  expect(finalPatternEvents(bars, 60)).toEqual(
    all.filter((e) => e.confirmed === true || e.side === 'NEUTRAL')
  )
  expect(finalPatternEvents(bars, 60)).toContainEqual(
    expect.objectContaining({ name: 'Belt Hold confirmed', time: 1300, confirmed: true })
  )
})
it('keeps historical prefixes stable and resets after missing candles', () => {
  const first = finalPatternEvents(bars.slice(0, -1), 60)
  expect(finalPatternEvents(bars, 60).filter((e) => e.time < 1300)).toEqual(first)
  const gap = bars.map((b) => ({ ...b }))
  gap.at(-1)!.time += 600
  expect(
    finalPatternEvents(gap, 60).some((e) => e.name === 'Belt Hold confirmed' && e.time === 1900)
  ).toBe(false)
})
it('retains both bullish and bearish chart-shape geometry in the final version', () => {
  const values = [120, 100, 112, 100, 108],
    prices: number[] = []
  for (let i = 0; i < values.length - 1; i++)
    for (let j = 0; j < 4; j++) prices.push(values[i] + ((values[i + 1] - values[i]) * j) / 4)
  prices.push(108, 111.5, 115)
  const source = prices.map((close, i) => ({
    time: i + 1,
    open: close,
    close,
    high: close + 0.1,
    low: close - 0.1,
    volume: 100,
  }))
  expect(finalPatternEvents(source, 1)).toContainEqual(
    expect.objectContaining({ pattern: 'double-bottom', side: 'CALL', confirmed: true, entry: 115 })
  )
  const inverse = source.map((b) => ({
    ...b,
    open: 200 - b.open,
    close: 200 - b.close,
    high: 200 - b.low,
    low: 200 - b.high,
  }))
  expect(finalPatternEvents(inverse, 1)).toContainEqual(
    expect.objectContaining({ pattern: 'double-top', side: 'PUT', confirmed: true, entry: 85 })
  )
})
it('uses the same primary pattern for the candle and final reading', async () => {
  const { finalPatternReading } = await import('./finalPatternEngine')
  const { primaryArchiveLabels } = await import('./archivePatternLabels')
  const events = [
    {
      time: 1300,
      side: 'CALL' as const,
      name: 'Slingshot',
      pattern: 'slingshot',
      confirmed: true,
      extreme: 99,
    },
    {
      time: 1300,
      side: 'CALL' as const,
      name: 'Piercing Pattern confirmed',
      pattern: 'confirmed-guide-piercing',
      confirmed: true,
      extreme: 98,
    },
  ]
  expect(finalPatternReading(events, bars).name).toBe(primaryArchiveLabels(events)[0].name)
})
it('waits when genuine confirmed directions conflict, regardless of detector family', async () => {
  const { finalPatternReading } = await import('./finalPatternEngine')
  expect(
    finalPatternReading(
      [
        {
          time: 1300,
          side: 'CALL',
          name: 'Hammer at demand',
          pattern: 'zone-hammer',
          confirmed: true,
          extreme: 99,
        },
        {
          time: 1300,
          side: 'PUT',
          name: 'Double Top',
          pattern: 'double-top',
          confirmed: true,
          extreme: 110,
          entry: 103,
          target: 90,
        },
      ],
      bars
    )
  ).toMatchObject({ side: 'WAIT', name: 'Mixed signals' })
})
