import { describe, expect, it } from 'vitest'
import { buildFrames, ema, rsi, sma, strictPivots } from './indicators'

const bar = (i: number, close: number, volume = 1) => ({
  time: Date.UTC(2026, 10, 2, 3, 45) / 1000 + i * 300,
  open: close,
  high: close + 1,
  low: close - 1,
  close,
  volume,
})
describe('causal shared indicator formulas', () => {
  it('seeds SMA and EMA with the specified number of samples', () => {
    expect(sma([1, 2, 3, 4], 3)).toEqual([undefined, undefined, 2, 3])
    expect(ema([1, 2, 3, 4, 5], 3)).toEqual([undefined, undefined, 2, 3, 4])
  })
  it('matches the standard Wilder RSI reference, without zero seeding', () => {
    const c = [
      44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.1, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61,
      46.28, 46.28,
    ]
    expect(rsi(c, 14).at(-1)).toBeCloseTo(70.464135, 5)
    expect(
      rsi(c, 14)
        .slice(0, 14)
        .every((x) => x === undefined)
    ).toBe(true)
  })
  it('computes session volume weights and prior-session traditional pivots', () => {
    const b = [bar(0, 100, 1), bar(1, 110, 3), { ...bar(2, 105), time: bar(0, 100).time + 86400 }]
    const f = buildFrames(b, 300)
    expect(f[1].vwap).toBeCloseTo(107.5)
    expect(f[1].vwapSD).toBeCloseTo(Math.sqrt(18.75))
    expect(f[2].pivot).toBeUndefined()
    expect(f[2].vwap).toBe(105)
  })
  it('does not give VWAP a price when traded volume is missing', () => {
    expect(buildFrames([bar(0, 100, 0)], 300)[0].vwap).toBeUndefined()
  })
  it('withholds truncated, gapped or unfinished session anchors and recovers after full coverage', () => {
    const full = Array.from({ length: 75 }, (_, i) => bar(i, i === 0 ? 100 : 110)),
      next = { ...bar(0, 105), time: bar(0, 100).time + 86400 }
    expect(buildFrames([...full, next], 300).at(-1)!.pivot).toBeCloseTo((111 + 99 + 110) / 3)
    for (const partial of [full.slice(21), full.filter((_, i) => i !== 20), full.slice(0, -1)]) {
      const f = buildFrames([...partial, next], 300)
      expect(f.at(-1)!.pivot).toBeUndefined()
      if (partial[0].time !== full[0].time) expect(f[0].vwap).toBeUndefined()
      const recovered = buildFrames(
        [
          ...partial,
          ...full.map((b) => ({ ...b, time: b.time + 86400 })),
          { ...next, time: next.time + 86400 },
        ],
        300
      )
      expect(recovered.at(-1)!.pivot).toBeCloseTo((111 + 99 + 110) / 3)
    }
    expect(
      buildFrames(
        full.filter((_, i) => i !== 20),
        300
      ).at(-1)!.vwap
    ).toBeUndefined()
  })
  it('requires midnight coverage for continuous-market session levels', () => {
    const midnight = Date.UTC(2026, 10, 2) / 1000,
      full = Array.from({ length: 24 }, (_, i) => ({ ...bar(i, 100), time: midnight + i * 3600 })),
      next = { ...full[0], time: midnight + 86400 }
    expect(buildFrames([...full, next], 3600, 0).at(-1)!.pivot).toBe(100)
    const partial = buildFrames([...full.slice(1), next], 3600, 0)
    expect(partial[0].vwap).toBeUndefined()
    expect(partial.at(-1)!.pivot).toBeUndefined()
  })
  it('recognizes the special four-right-bar fractal only after four closes', () => {
    const b = [1, 2, 3, 4, 10, 4, 3, 2, 1].map((c, i) => bar(i, c + 100))
    expect(strictPivots(b.slice(0, 8), 4).filter((p) => p.kind === 'high')).toHaveLength(0)
    expect(strictPivots(b, 4).find((p) => p.kind === 'high')).toMatchObject({
      index: 4,
      knownAt: 8,
      price: 111,
    })
  })
  it('compares against the cloud plotted now rather than a future projected cloud', () => {
    const f = buildFrames(
      Array.from({ length: 120 }, (_, i) => bar(i, 100 + i)),
      3600
    )
    expect(f[110].cloudA).toBe(f[84].rawSpanA)
    expect(f[110].cloudB).toBe(f[84].rawSpanB)
  })
  it('never changes an earlier calculated frame when future bars are appended', () => {
    const b = Array.from({ length: 100 }, (_, i) => bar(i, 100 + i / 10 + Math.sin(i)))
    expect(buildFrames(b, 300).slice(0, 70)).toEqual(buildFrames(b.slice(0, 70), 300))
  })
})
