import { describe, expect, it } from 'vitest'
import { recognizeChartShapes } from './chartShapePatterns'
import type { Bar } from './model'
// Four candles per leg makes turns independently confirmable before breakout.
function path(values: number[], breakout: number): Bar[] {
  const prices: number[] = []
  for (let i = 0; i < values.length - 1; i++)
    for (let j = 0; j < 4; j++) prices.push(values[i] + ((values[i + 1] - values[i]) * j) / 4)
  prices.push(values.at(-1)!, (values.at(-1)! + breakout) / 2, breakout)
  return prices.map((close, i) => ({
    time: i + 1,
    open: close,
    close,
    high: close + 0.1,
    low: close - 0.1,
    volume: 100,
  }))
}
const mirror = (bars: Bar[]) =>
  bars.map((b) => ({
    ...b,
    open: 200 - b.open,
    close: 200 - b.close,
    high: 200 - b.low,
    low: 200 - b.high,
  }))
const fixtures: [string, string, number[], number][] = [
  ['double-bottom', 'double-top', [120, 100, 112, 100, 108], 115],
  ['triple-bottom', 'triple-top', [120, 100, 112, 100, 112, 100, 108], 115],
  ['inverse-head-and-shoulders', 'head-and-shoulders', [120, 104, 114, 96, 114, 104, 110], 117],
  ['ascending-triangle', 'descending-triangle', [104, 120, 100, 120, 105, 120, 110, 115], 123],
  ['symmetrical-triangle', 'symmetrical-triangle', [110, 124, 96, 120, 100, 116, 104, 109], 114],
  ['rectangle', 'rectangle', [110, 120, 100, 120, 100, 120, 100, 110], 123],
  ['falling-wedge', 'rising-wedge', [118, 130, 100, 124, 98, 118, 96, 105], 114],
  ['channel', 'channel', [110, 120, 100, 124, 104, 128, 108, 120], 135],
  ['bull-flag', 'bear-flag', [70, 100, 120, 110, 118, 108, 116, 106, 112], 114],
  ['bull-pennant', 'bear-pennant', [65, 100, 124, 96, 120, 100, 116, 104, 109], 114],
]
describe('confirmed geometric chart shapes', () => {
  for (const [bull, bear, values, breakout] of fixtures) {
    it(`recognizes ${bull} only at an upward close crossing`, () => {
      const bars = path(values, breakout)
      expect(recognizeChartShapes(bars)).toEqual(
        expect.arrayContaining([expect.objectContaining({ pattern: bull, side: 'CALL' })])
      )
      expect(recognizeChartShapes(bars.slice(0, -1)).some((x) => x.pattern === bull)).toBe(false)
    })
    it(`recognizes mirrored ${bear}`, () => {
      expect(recognizeChartShapes(mirror(path(values, breakout)))).toEqual(
        expect.arrayContaining([expect.objectContaining({ pattern: bear, side: 'PUT' })])
      )
    })
  }
  it('rejects malformed OHLC and nonfinite history', () => {
    const bars = path(fixtures[0][2], 115)
    for (const patch of [{ high: NaN }, { low: 999 }, { time: 0 }]) {
      const bad = bars.map((b) => ({ ...b }))
      Object.assign(bad[5], patch)
      expect(recognizeChartShapes(bad)).toEqual([])
    }
  })
  it('does not repeat an already crossed boundary', () => {
    const bars = path(fixtures[0][2], 115)
    bars.push({ ...bars.at(-1)!, time: bars.at(-1)!.time + 1, close: 116, high: 116.1 })
    expect(recognizeChartShapes(bars).some((x) => x.pattern === 'double-bottom')).toBe(false)
  })
  it('requires independently confirmed, separated swings', () => {
    expect(recognizeChartShapes(path([100, 101, 100, 101], 103).slice(-7))).toEqual([])
    expect(recognizeChartShapes([])).toEqual([])
  })
  it('does not mutate history or depend on bars after supplied prefix', () => {
    const bars = path(fixtures[0][2], 115),
      prefix = bars.slice(0, -1),
      before = JSON.stringify(prefix)
    const result = recognizeChartShapes(prefix)
    recognizeChartShapes([...bars, ...path([150, 140, 160], 170)])
    expect(recognizeChartShapes(prefix)).toEqual(result)
    expect(JSON.stringify(prefix)).toBe(before)
  })
})

function bowl(handle: boolean): Bar[] {
  const prices = [112, 114, 116, 118]
  for (let i = 0; i <= 40; i++) prices.push(100 + 20 * ((2 * i) / 40 - 1) ** 2)
  if (handle) prices.push(119, 117, 115, 116, 118, 119)
  prices.push(122)
  return prices.map((close, i) => ({
    time: i + 1,
    open: close,
    high: close + 0.1,
    low: close - 0.1,
    close,
    volume: 100,
  }))
}
for (const handle of [false, true]) {
  const bull = handle ? 'cup-and-handle' : 'rounding-bottom'
  const bear = handle ? 'inverse-cup-and-handle' : 'rounding-top'
  it(`recognizes smooth ${bull} with a confirmed central trough`, () => {
    expect(recognizeChartShapes(bowl(handle))).toEqual(
      expect.arrayContaining([expect.objectContaining({ pattern: bull, side: 'CALL' })])
    )
    expect(recognizeChartShapes(bowl(handle).slice(0, -1)).some((x) => x.pattern === bull)).toBe(
      false
    )
  })
  it(`recognizes smooth mirrored ${bear}`, () => {
    expect(recognizeChartShapes(mirror(bowl(handle)))).toEqual(
      expect.arrayContaining([expect.objectContaining({ pattern: bear, side: 'PUT' })])
    )
  })
}
it('does not label a sharp V as a rounding bottom or cup', () => {
  expect(
    recognizeChartShapes(path([110, 120, 100, 119], 122)).some((x) =>
      /rounding|cup/.test(x.pattern)
    )
  ).toBe(false)
})
it('does not label a pole-free consolidation as a flag or pennant', () => {
  expect(
    recognizeChartShapes(path(fixtures[4][2], fixtures[4][3])).some((x) =>
      /flag|pennant/.test(x.pattern)
    )
  ).toBe(false)
})
it('requires a close breakout even when the wick crosses resistance', () => {
  const bars = path(fixtures[0][2], 111)
  bars[bars.length - 1].high = 118
  expect(recognizeChartShapes(bars).some((x) => x.pattern === 'double-bottom')).toBe(false)
})

const extraFixtures: [string, string, number[], number][] = [
  ['three-rising-valleys', 'three-descending-peaks', [122, 100, 114, 104, 118, 108, 114], 121],
  ['measured-move-up', 'measured-move-down', [105, 96, 120, 108, 116], 123],
  ['diamond-bottom', 'diamond-top', [110, 118, 104, 124, 96, 120, 100, 116, 104, 110], 113],
]
for (const [bull, bear, values, breakout] of extraFixtures) {
  it(`recognizes confirmed ${bull} and mirrored ${bear}`, () => {
    for (const [bars, pattern, side] of [
      [path(values, breakout), bull, 'CALL'],
      [mirror(path(values, breakout)), bear, 'PUT'],
    ] as const) {
      expect(recognizeChartShapes(bars)).toEqual(
        expect.arrayContaining([expect.objectContaining({ pattern, side })])
      )
      expect(recognizeChartShapes(bars.slice(0, -1)).some((x) => x.pattern === pattern)).toBe(false)
      const next = { ...bars.at(-1)!, time: bars.at(-1)!.time + 1 }
      expect(recognizeChartShapes([...bars, next]).some((x) => x.pattern === pattern)).toBe(false)
    }
  })
}
it('exposes executable geometry for every existing family in either direction', () => {
  for (const [, , values, breakout] of fixtures) {
    for (const bars of [path(values, breakout), mirror(path(values, breakout))]) {
      const matches = recognizeChartShapes(bars)
      expect(matches.length).toBeGreaterThan(0)
      for (const match of matches) {
        expect(match.entry).toBe(bars.at(-1)!.close)
        expect(match.startTime).toBeLessThan(bars.at(-1)!.time)
        expect(match.boundary).toHaveLength(2)
        const direction = match.side === 'CALL' ? 1 : -1
        expect(direction * (match.target! - match.entry!)).toBeGreaterThan(0)
        expect(direction * (match.entry! - match.extreme)).toBeGreaterThan(0)
      }
    }
  }
})
it('rejects a breakout whose measured target is already exhausted', () => {
  const bars = path(fixtures[0][2], 115)
  Object.assign(bars[bars.length - 1], { open: 140, close: 140, high: 140.1, low: 139.9 })
  expect(recognizeChartShapes(bars).some((m) => m.pattern === 'double-bottom')).toBe(false)
})
it('supports downward ascending-triangle and upward descending-triangle breakouts', () => {
  const bars = path([104, 120, 100, 120, 105, 120, 110, 115], 111.5)
  expect(recognizeChartShapes(bars)).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ pattern: 'ascending-triangle', side: 'PUT' }),
    ])
  )
  expect(recognizeChartShapes(mirror(bars))).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ pattern: 'descending-triangle', side: 'CALL' }),
    ])
  )
})
function scallop(): Bar[] {
  const prices = [112, 114, 116, 118]
  for (let j = 0; j <= 40; j++) prices.push(100 + 20 * ((2 * j) / 40 - 1) ** 2 + j / 5)
  prices.push(130)
  return prices.map((close, i) => ({
    time: i + 1,
    open: close,
    close,
    high: close + 0.1,
    low: close - 0.1,
    volume: 100,
  }))
}
it('recognizes tilted smooth ascending and descending scallops, rejecting sharp turns', () => {
  expect(recognizeChartShapes(scallop())).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ pattern: 'ascending-scallop', side: 'CALL' }),
    ])
  )
  expect(recognizeChartShapes(mirror(scallop()))).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ pattern: 'descending-scallop', side: 'PUT' }),
    ])
  )
  expect(
    recognizeChartShapes(path([112, 120, 100, 128], 130)).some((m) => m.pattern.includes('scallop'))
  ).toBe(false)
})

it('rejects unequal-length or shallow pullbacks as measured moves', () => {
  for (const values of [
    [105, 96, 120, 119, 119.5],
    [105, 96, 120, 100, 116],
  ])
    expect(
      recognizeChartShapes(path(values, 123)).some((m) => m.pattern === 'measured-move-up')
    ).toBe(false)
})
it('rejects flat valleys and a diamond that does not expand on both sides', () => {
  expect(
    recognizeChartShapes(path([122, 100, 114, 100, 118, 100, 114], 121)).some(
      (m) => m.pattern === 'three-rising-valleys'
    )
  ).toBe(false)
  expect(
    recognizeChartShapes(path([110, 118, 96, 124, 100, 120, 104, 116, 108, 110], 113)).some(
      (m) => m.pattern === 'diamond-bottom'
    )
  ).toBe(false)
})

it('covers all 15 crypto reference patterns with real, completed-candle outlines', async () => {
  const { CRYPTO_CHART_PATTERNS } = await import('./cryptoChartPatterns')
  expect(CRYPTO_CHART_PATTERNS).toHaveLength(15)
  const samples = [...fixtures, ...extraFixtures]
    .flatMap(([, , values, breakout]) => {
      const bars = path(values, breakout)
      return [bars, mirror(bars)]
    })
    .concat([bowl(true)])
  const matches = samples.flatMap((bars) =>
    recognizeChartShapes(bars).map((match) => ({ match, bars }))
  )
  for (const reference of CRYPTO_CHART_PATTERNS) {
    const found = matches.find(({ match }) => reference.ids.includes(match.pattern))
    expect(found, reference.name).toBeDefined()
    const { match, bars } = found!
    expect(match.structure?.length, reference.name).toBeGreaterThan(0)
    for (const line of match.structure!) {
      expect(line.length).toBeGreaterThanOrEqual(2)
      for (const point of line) {
        expect(bars.some((b) => b.time === point.time)).toBe(true)
        expect(point.time).toBeLessThanOrEqual(bars.at(-1)!.time)
        expect(point.price).toBeGreaterThan(0)
      }
    }
  }
})

it('keeps unbroken classical geometry hidden by default and explicitly provisional when enabled',()=>{
 const bs=path([120,100,112,100,108],115).slice(0,-1)
 expect(recognizeChartShapes(bs).some(e=>e.pattern==='double-bottom')).toBe(false)
 const e=recognizeChartShapes(bs,true).find(e=>e.pattern==='double-bottom')
 expect(e).toMatchObject({confirmed:false,side:'CALL'})
 expect(e?.entry).toBeUndefined();expect(e?.structure?.length).toBeGreaterThan(0)
})
