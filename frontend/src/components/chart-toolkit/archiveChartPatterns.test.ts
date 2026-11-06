import { expect, it } from 'vitest'
import { recognizeArchiveChartPatterns, parabolicSAR } from './archiveChartPatterns'
import type { Bar } from './model'
function path(values: number[]): Bar[] {
  const out: number[] = []
  for (let i = 0; i < values.length - 1; i++)
    for (let j = 0; j < 4; j++) out.push(values[i] + ((values[i + 1] - values[i]) * j) / 4)
  out.push(values.at(-1)!)
  return out.map((close, i) => ({
    time: (i + 1) * 60,
    open: close,
    close,
    high: close + 0.1,
    low: close - 0.1,
    volume: 1,
  }))
}
const reflect = (bs: Bar[]) =>
  bs.map((b) => ({
    ...b,
    open: 300 - b.open,
    close: 300 - b.close,
    high: 300 - b.low,
    low: 300 - b.high,
  }))
it('detects V reversal only after reclaiming the prior shoulder', () => {
  const bars = path([130, 120, 110, 100, 110, 119])
  bars.push({ ...bars.at(-1)!, time: bars.at(-1)!.time + 60, open: 119, close: 131, high: 132 })
  expect(recognizeArchiveChartPatterns(bars)).toContainEqual(
    expect.objectContaining({ pattern: 'v-bottom', side: 'CALL' })
  )
  expect(recognizeArchiveChartPatterns(reflect(bars))).toContainEqual(
    expect.objectContaining({ pattern: 'v-top', side: 'PUT' })
  )
  expect(
    recognizeArchiveChartPatterns(bars.slice(0, -1)).some((p) => p.pattern === 'v-bottom')
  ).toBe(false)
})
it('recognizes broadening boundary break with three widening touches each', () => {
  const bars = path([110, 120, 100, 125, 95, 130, 90, 115])
  bars.push({ ...bars.at(-1)!, time: bars.at(-1)!.time + 60, open: 115, close: 142, high: 143 })
  expect(recognizeArchiveChartPatterns(bars)).toContainEqual(
    expect.objectContaining({ pattern: 'broadening-wedge', side: 'CALL' })
  )
  expect(recognizeArchiveChartPatterns(reflect(bars))).toContainEqual(
    expect.objectContaining({ pattern: 'broadening-wedge', side: 'PUT' })
  )
})
it('SAR trails without future input and flips after range penetration', () => {
  const bars = path([100, 110, 120, 130])
  bars.push({ time: bars.at(-1)!.time + 60, open: 130, high: 131, low: 90, close: 91, volume: 1 })
  const points = parabolicSAR(bars)
  expect(points.at(-1)).toMatchObject({ side: 'PUT', flip: true })
  expect(points.slice(0, -1)).toEqual(parabolicSAR(bars.slice(0, -1)))
  expect(points.every((p) => Number.isFinite(p.value))).toBe(true)
  expect(parabolicSAR([{ ...bars[0], high: NaN }])).toEqual([])
})
it('rejects invalid, unsorted or flat data without mutating it', () => {
  const bars = path([100, 100, 100])
  const before = JSON.stringify(bars)
  expect(recognizeArchiveChartPatterns(bars)).toEqual([])
  expect(recognizeArchiveChartPatterns([...bars].reverse())).toEqual([])
  expect(JSON.stringify(bars)).toBe(before)
})
it('does not recycle a V after an earlier completed breakout', () => {
  const bars = [109, 105, 101, 97, 93, 89, 94, 99, 104, 111, 109, 112].map((close, i) => ({
    time: (i + 1) * 60,
    open: close,
    close,
    high: close + 1,
    low: close - 1,
    volume: 1,
  }))
  expect(recognizeArchiveChartPatterns(bars).some((m) => m.pattern === 'v-bottom')).toBe(false)
  expect(recognizeArchiveChartPatterns(reflect(bars)).some((m) => m.pattern === 'v-top')).toBe(
    false
  )
})
it('requires a support sweep and closing recovery for Slingshot', () => {
  const bars = path([120, 100, 120, 105, 115])
  bars.push({ time: bars.at(-1)!.time + 60, open: 110, close: 116, high: 117, low: 104, volume: 1 })
  expect(recognizeArchiveChartPatterns(bars)).toContainEqual(
    expect.objectContaining({ pattern: 'slingshot', side: 'CALL' })
  )
  expect(recognizeArchiveChartPatterns(reflect(bars))).toContainEqual(
    expect.objectContaining({ pattern: 'slingshot', side: 'PUT' })
  )
  bars[bars.length - 1].low = 105
  expect(recognizeArchiveChartPatterns(bars).some((m) => m.pattern === 'slingshot')).toBe(false)
})

it('distinguishes a sloping expanding cylinder from a megaphone and draws both boundaries', () => {
  const bars = path([110, 120, 100, 130, 104, 140, 108, 125])
  bars.push({ ...bars.at(-1)!, time: bars.at(-1)!.time + 60, open: 125, close: 153, high: 154 })
  for (const source of [bars, reflect(bars)]) {
    const matches = recognizeArchiveChartPatterns(source)
    const match = matches.find((m) => m.pattern === 'livermore-cylinder')
    expect(match).toBeDefined()
    expect(match!.structure).toHaveLength(2)
    expect(matches.some((m) => m.pattern === 'broadening-wedge')).toBe(false)
    expect(
      recognizeArchiveChartPatterns(source.slice(0, -1)).some(
        (m) => m.pattern === 'livermore-cylinder'
      )
    ).toBe(false)
  }
})
