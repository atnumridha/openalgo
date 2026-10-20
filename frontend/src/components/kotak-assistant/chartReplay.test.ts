import { describe, expect, it } from 'vitest'
import {
  freezeReplay,
  replayBars,
  replayInput,
  parseReplayInput,
  replayIndex,
  istSessionDate,
  sessionBounds,
  sessionBars,
  chartRangeBars,
  chartRangeBounds,
} from './chartReplay'

const start = Date.UTC(2026, 9, 15, 9, 15) / 1000
const bars = (count: number) =>
  Array.from({ length: count }, (_, i) => ({
    time: start + i * 300,
    open: 100,
    high: 105,
    low: 99,
    close: 102,
    volume: i * 10,
  }))
describe('Chart replay clock', () => {
  it('freezes completed candles and uses only shared closing times', () => {
    const ce = bars(6),
      pe = bars(5).filter((_, i) => i !== 2)
    const result = freezeReplay(
      [
        { key: 'ce', bars: ce },
        { key: 'pe', bars: pe },
      ],
      '5m',
      start + 5 * 300 - 19800 + 20
    )
    expect(result?.timeline).toEqual([start + 300, start + 600, start + 1200, start + 1500])
    ce[0].close = 900
    expect(result?.series.ce[0].close).toBe(102)
    expect(result?.series.ce).toHaveLength(5)
    expect(replayBars(result!.series.ce, 300, start + 600)).toHaveLength(2)
  })
  it('requires history in every pane and enough common candles', () => {
    expect(
      freezeReplay(
        [
          { key: 'a', bars: bars(3) },
          { key: 'b', bars: [] },
        ],
        '5m',
        start
      )
    ).toBeNull()
    expect(freezeReplay([{ key: 'a', bars: bars(1) }], '5m', start + 5000)).toBeNull()
  })
  it('parses and formats IST axis times without a second timezone shift', () => {
    expect(replayInput(start)).toBe('2026-10-15T09:15')
    expect(parseReplayInput('2026-10-15T09:15')).toBe(start)
    expect(parseReplayInput('2026-02-31T09:15')).toBeNull()
    expect(parseReplayInput('')).toBeNull()
    expect(replayIndex([100, 200, 300], 250)).toBe(1)
    expect(replayIndex([100, 200, 300], 99)).toBe(-1)
  })
})

describe('IST session filtering', () => {
  it('uses the Indian calendar date across UTC day boundaries', () => {
    expect(istSessionDate(Date.UTC(2026, 9, 14, 20) / 1000)).toBe('2026-10-15')
    expect(istSessionDate(Date.UTC(2026, 9, 14, 18, 29) / 1000)).toBe('2026-10-14')
    expect(sessionBounds('2026-02-31')).toBeNull()
  })
  it('filters true UTC and IST-axis candles consistently at day boundaries', () => {
    const first = Date.UTC(2026, 9, 14, 18, 30) / 1000
    const utc = [first - 1, first, first + 86399, first + 86400].map((time) => ({ time }))
    expect(sessionBars(utc, '2026-10-15').map((b) => b.time)).toEqual([first, first + 86399])
    expect(
      sessionBars(
        utc.map((b) => ({ time: b.time + 19800 })),
        '2026-10-15',
        19800
      ).map((b) => b.time)
    ).toEqual([first + 19800, first + 106199])
  })
  it('replays only the selected session while retaining earlier indicator warmup', () => {
    const yesterday = bars(4).map((b) => ({ ...b, time: b.time - 86400 }))
    const tomorrow = bars(3).map((b) => ({ ...b, time: b.time + 86400 }))
    const result = freezeReplay(
      [{ key: 'a', bars: [...yesterday, ...bars(4), ...tomorrow] }],
      '5m',
      start + 86400,
      '2026-10-15'
    )
    expect(result?.timeline).toEqual(bars(4).map((b) => b.time + 300))
    expect(result?.series.a).toHaveLength(8)
    expect(replayBars(result!.series.a, 300, result!.timeline[0])).toHaveLength(5)
    expect(
      freezeReplay([{ key: 'a', bars: yesterday }], '5m', start + 86400, '2026-10-15')
    ).toBeNull()
  })
})

it('includes both ends of a date range and keeps replay between those dates', () => {
  const all = [-2, -1, 0, 1].flatMap((day) =>
    bars(3).map((b) => ({ ...b, time: b.time + day * 86400 }))
  )
  expect(chartRangeBars(all, '2026-10-14', '2026-10-15', 19800)).toHaveLength(6)
  expect(chartRangeBounds('2026-10-15', '2026-10-14')).toBeNull()
  const result = freezeReplay(
    [{ key: 'a', bars: all }],
    '5m',
    start + 86400,
    '2026-10-14',
    '2026-10-15'
  )
  expect(result?.timeline).toHaveLength(6)
  expect(result?.timeline[0]).toBe(start - 86400 + 300)
  expect(result?.timeline.at(-1)).toBe(start + 900)
  expect(result?.series.a).toHaveLength(9)
})
