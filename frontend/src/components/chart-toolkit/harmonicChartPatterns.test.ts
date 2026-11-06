import { expect, it } from 'vitest'
import { recognizeHarmonicPatterns } from './harmonicChartPatterns'
import { finalPatternEvents } from './finalPatternEngine'
import { cryptoFormationSegments } from './TrendLineLayer'
import type { Bar } from './model'
export function harmonicFixture(kind: 'gartley' | 'cypher', points?: number[]): Bar[] {
  const values =
    points ??
    (kind === 'gartley'
      ? [110, 100, 120, 107.64, 116.12, 104.28]
      : [110, 100, 120, 110, 126, 105.564])
  const prices: number[] = []
  for (let i = 0; i < values.length - 1; i++)
    for (let j = 0; j < 4; j++) prices.push(values[i] + ((values[i + 1] - values[i]) * j) / 4)
  const d = values.at(-1)!
  prices.push(d, d + 0.15, d + 0.3, d + 1)
  return prices.map((close, i) => ({
    time: 60 * (i + 1),
    open: close,
    close,
    high: close + 0.01,
    low: close - 0.01,
    volume: 100,
  }))
}
const mirror = (bs: Bar[]) =>
  bs.map((b) => ({
    ...b,
    open: 300 - b.open,
    close: 300 - b.close,
    high: 300 - b.low,
    low: 300 - b.high,
  }))
for (const kind of ['gartley', 'cypher'] as const) {
  it(`confirms ${kind} and its bearish mirror only after the reversal closes`, () => {
    const bars = harmonicFixture(kind)
    for (const source of [bars, mirror(bars)]) {
      const expected = source === bars ? 'CALL' : 'PUT'
      const m = recognizeHarmonicPatterns(source).find((m) => m.pattern === kind)
      expect(m).toMatchObject({ side: expected, entry: source.at(-1)!.close })
      expect(recognizeHarmonicPatterns(source.slice(0, -1))).toEqual([])
      expect(m!.structure![0]).toHaveLength(5)
      const times = new Set(source.map((b) => b.time))
      expect(
        m!
          .structure!.flat()
          .every((p) => p.price > 0 && times.has(p.time) && p.time <= source.at(-1)!.time)
      ).toBe(true)
      const events = finalPatternEvents(source, 60)
      expect(events).toContainEqual(
        expect.objectContaining({ pattern: kind, confirmed: true, side: expected })
      )
      expect(
        cryptoFormationSegments(events, source, source[0].time, source.at(-1)!.time).length
      ).toBeGreaterThan(0)
    }
  })
  it(`keeps ${kind} history stable, rejects malformed candles and avoids repeating its break`, () => {
    const bars = harmonicFixture(kind)
    const before = JSON.stringify(bars)
    const first = recognizeHarmonicPatterns(bars)
    expect(
      recognizeHarmonicPatterns(bars.map((b, i) => (i === 5 ? { ...b, low: b.high + 1 } : b)))
    ).toEqual([])
    const extended = [
      ...bars,
      {
        ...bars.at(-1)!,
        time: bars.at(-1)!.time + 60,
        close: bars.at(-1)!.close + 0.5,
        high: bars.at(-1)!.high + 0.5,
      },
    ]
    expect(recognizeHarmonicPatterns(extended).some((m) => m.pattern === kind)).toBe(false)
    expect(recognizeHarmonicPatterns(bars)).toEqual(first)
    expect(JSON.stringify(bars)).toBe(before)
    expect(finalPatternEvents(extended, 60).filter((e) => e.time <= bars.at(-1)!.time)).toEqual(
      finalPatternEvents(bars, 60)
    )
  })
}
it('rejects approximate M/W drawings with wrong Fibonacci ratios or an invalidated X', () => {
  for (const points of [
    [110, 100, 120, 114, 116.12, 104.28],
    [110, 100, 120, 107.64, 119.5, 104.28],
    [110, 100, 120, 107.64, 116.12, 98],
    [110, 100, 120, 110, 122, 105.564],
    [110, 100, 120, 110, 126, 112],
  ])
    expect(recognizeHarmonicPatterns(harmonicFixture('gartley', points))).toEqual([])
})
it('requires a close rather than a wick through the confirmation level', () => {
  const bars = harmonicFixture('gartley')
  bars.at(-1)!.close = 104.5
  bars.at(-1)!.open = 104.5
  expect(recognizeHarmonicPatterns(bars)).toEqual([])
})
