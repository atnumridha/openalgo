import { describe, expect, it } from 'vitest'
import { analyzeCandles, detectPattern, evidenceEstimate } from './candleProbability'
import type { Bar } from './model'
import type { CandleModel, CandleOptions } from './candleProbabilityTypes'

const start = Date.parse('2026-10-28T03:45:00Z') / 1000
const bar = (i: number, o = 100, h = 101, l = 99, c = 100): Bar => ({
  time: start + i * 60,
  open: o,
  high: h,
  low: l,
  close: c,
  volume: 0,
})
const setup = () => [
  ...Array.from({ length: 10 }, (_, i) => bar(i)),
  bar(10, 100.5, 100.8, 99.8, 100),
  bar(11, 99.9, 101, 99.5, 100.8),
]
const options = (asOf: number): CandleOptions => ({
  symbol: 'TEST',
  exchange: 'TEST',
  seconds: 60,
  indian: false,
  asOf,
})
const seed = (): CandleModel => ({
  version: 1,
  symbol: 'TEST',
  exchange: 'TEST',
  seconds: 60,
  indian: false,
  trainedThrough: start - 60,
  source: 'test evidence',
  counts: { 'engulfing:CALL:flat': { targets: 90, stops: 10, timeouts: 0, ambiguous: 0 } },
})

describe('candlestick geometry', () => {
  it('recognizes a bullish body engulf and uses causal extremes and 2R', () => {
    const p = detectPattern(setup())!
    expect(p.side).toBe('CALL')
    expect(p.pattern).toBe('engulfing')
    expect(p.entry).toBe(100.8)
    expect(p.stop).toBeCloseTo(99.315)
    expect(p.target).toBeCloseTo(103.77)
    expect([p.support, p.resistance]).toEqual([99, 101])
  })
  it('mirrors bearish geometry without a symbol or volume dependency', () => {
    const mirrored = setup().map((b) => ({
      ...b,
      open: 200 - b.open,
      high: 200 - b.low,
      low: 200 - b.high,
      close: 200 - b.close,
    }))
    const p = detectPattern(mirrored)!
    expect(p.side).toBe('PUT')
    expect(p.stop).toBeCloseTo(100.685)
    expect(p.target).toBeCloseTo(96.23)
  })
  it('recognizes a long lower wick but rejects a doji', () => {
    const history = Array.from({ length: 11 }, (_, i) => bar(i))
    expect(detectPattern([...history, bar(11, 100, 100.5, 98.5, 100.4)])?.pattern).toBe('rejection')
    expect(detectPattern([...history, bar(11, 100, 102, 98, 100)])).toBeNull()
  })
  it('requires a close through the mother bar for inside-bar breakout', () => {
    const history = [
      ...Array.from({ length: 10 }, (_, i) => bar(i)),
      bar(10, 100, 100.5, 99.5, 100.2),
    ]
    expect(detectPattern([...history, bar(11, 100.3, 101.2, 100.2, 101.1)])?.pattern).toBe(
      'inside-break'
    )
    expect(detectPattern([...history, bar(11, 100.3, 101.2, 100.2, 100.8)])).toBeNull()
  })
})

describe('outcome evidence', () => {
  it('shows uncertainty and never invents a probability without samples', () => {
    expect(
      evidenceEstimate({ targets: 0, stops: 0, timeouts: 0, ambiguous: 0 }).probability
    ).toBeNull()
    const e = evidenceEstimate({ targets: 8, stops: 1, timeouts: 1, ambiguous: 0 })
    expect(e.samples).toBe(10)
    expect(e.probability).toBeCloseTo(0.75)
    expect(e.lower).toBeCloseTo(0.4902, 3)
    expect(e.upper).toBeCloseTo(0.9433, 3)
  })
  it('does not use the signal candle to settle its own target', () => {
    const study = analyzeCandles(setup(), options(start + 12 * 60), seed())
    expect(study.outcomes).toHaveLength(0)
    expect(study.latest?.qualified).toBe(true)
    expect(study.active?.time).toBe(start + 11 * 60)
  })
  it('counts both-level candles as stops, not wins', () => {
    const study = analyzeCandles(
      [...setup(), bar(12, 100.8, 105, 98, 101)],
      options(start + 13 * 60),
      seed()
    )
    expect(study.outcomes[0].result).toBe('STOP')
    expect(study.outcomes[0].ambiguous).toBe(true)
    expect(study.outcomes[0].r).toBe(-1)
    expect(study.signalOutcomes[0].result).toBe('STOP')
  })
  it('records target and gap-through-stop outcomes conservatively', () => {
    const winner = analyzeCandles(
      [...setup(), bar(12, 101, 104, 100, 103)],
      options(start + 13 * 60)
    )
    expect(winner.outcomes[0].result).toBe('TARGET')
    expect(winner.outcomes[0].r).toBe(2)
    const loser = analyzeCandles([...setup(), bar(12, 98, 99, 97, 98)], options(start + 13 * 60))
    expect(loser.outcomes[0].result).toBe('STOP')
    expect(loser.outcomes[0].r).toBeLessThan(-1)
  })
  it('times out at ten later candles and includes timeout in the denominator', () => {
    const bars = [
      ...setup(),
      ...Array.from({ length: 10 }, (_, i) => bar(12 + i, 100.8, 101, 100, 100.8)),
    ]
    const study = analyzeCandles(bars, options(start + 22 * 60))
    expect(study.outcomes[0].result).toBe('TIMEOUT')
    expect(study.outcomes[0].time).toBe(start + 21 * 60)
    expect(study.model.counts['engulfing:CALL:flat'].timeouts).toBe(1)
    expect(study.outcomes[0].r).toBe(0)
  })
  it('invalidates missing-bar outcomes rather than filling a gap', () => {
    const study = analyzeCandles(
      [...setup(), bar(13, 101, 105, 100, 104)],
      options(start + 14 * 60)
    )
    expect(study.outcomes[0].result).toBe('UNKNOWN')
    expect(study.model.counts['engulfing:CALL:flat']).toBeUndefined()
  })
  it('does not confirm a forming bar or use future evidence', () => {
    expect(analyzeCandles(setup(), options(start + 11 * 60 + 59), seed()).latest).toBeNull()
    const future = { ...seed(), trainedThrough: start + 14 * 60 }
    const study = analyzeCandles(setup(), options(start + 12 * 60), future)
    expect(study.seedUsed).toBe(false)
    expect(study.latest?.estimate.samples).toBe(0)
  })
  it('rejects seeds from a different instrument, exchange or timeframe', () => {
    for (const mismatch of [
      { symbol: 'OTHER' },
      { exchange: 'NFO' },
      { seconds: 300 },
      { indian: true },
    ]) {
      expect(
        analyzeCandles(setup(), options(start + 12 * 60), { ...seed(), ...mismatch }).latest
          ?.estimate.samples
      ).toBe(0)
    }
  })
  it('requires enough evidence and the chosen probability threshold', () => {
    const low = seed()
    low.counts['engulfing:CALL:flat'] = { targets: 49, stops: 0, timeouts: 0, ambiguous: 0 }
    expect(analyzeCandles(setup(), options(start + 12 * 60), low).latest?.qualified).toBe(false)
    low.counts['engulfing:CALL:flat'] = { targets: 60, stops: 40, timeouts: 0, ambiguous: 0 }
    expect(analyzeCandles(setup(), options(start + 12 * 60), low).latest?.qualified).toBe(false)
    expect(analyzeCandles(setup(), options(start + 12 * 60), seed()).latest?.qualified).toBe(true)
  })
  it('has prefix-invariant predictions and leaves seed counts immutable', () => {
    const evidence = seed(),
      original = JSON.stringify(evidence)
    const early = analyzeCandles(setup(), options(start + 12 * 60), evidence)
    const later = analyzeCandles(
      [...setup(), bar(12, 101, 105, 100, 104)],
      options(start + 13 * 60),
      evidence
    )
    expect(later.setups.find((x) => x.time === start + 11 * 60)).toEqual(early.latest)
    expect(JSON.stringify(evidence)).toBe(original)
  })
  it('does not attach future seed evidence to replay candles before its cutoff', () => {
    const evidence = { ...seed(), trainedThrough: start + 12 * 60 }
    const study = analyzeCandles([...setup(), bar(12)], options(start + 13 * 60), evidence)
    expect(study.setups.find((x) => x.time === start + 11 * 60)).toBeUndefined()
  })
  it('rejects late Indian-session setups and resets context between sessions', () => {
    const late = setup().map((b) => ({ ...b, time: b.time + 355 * 60 }))
    expect(
      analyzeCandles(late, { ...options(start + 367 * 60), indian: true }).latest?.qualified
    ).not.toBe(true)
    expect(
      analyzeCandles(late, { ...options(start + 367 * 60), indian: true }).outcomes
    ).toHaveLength(0)
    const next = setup()
      .slice(-1)
      .map((b) => ({ ...b, time: start + 86400 }))
    expect(
      analyzeCandles([...setup(), ...next], { ...options(start + 86460), indian: true }).latest
    ).toBeNull()
  })
  it('keeps continuous markets contiguous across midnight', () => {
    const shifted = setup().map((b) => ({
      ...b,
      time: b.time - start + Date.parse('2026-10-28T23:49:00Z') / 1000,
    }))
    const o = { ...options(shifted.at(-1)!.time + 60), symbol: 'BTCUSD', exchange: 'DELTA' }
    expect(analyzeCandles(shifted, o).latest?.pattern).toBe('engulfing')
  })
  it('invalid OHLC and conflicting duplicate candles cannot produce a setup', () => {
    const raw = setup()
    expect(
      analyzeCandles([...raw, { ...raw.at(-1)!, high: 99 }], options(start + 12 * 60)).latest
    ).toBeNull()
    expect(
      analyzeCandles([...raw, { ...raw.at(-1)!, close: 100.9 }], options(start + 12 * 60)).latest
    ).toBeNull()
  })
  it('invalid latest candles stop qualified tracking until the data gap is reviewed', () => {
    const study = analyzeCandles(
      [...setup(), bar(12, 100, 99, 98, 100)],
      options(start + 13 * 60),
      seed()
    )
    expect(study.active).toBeNull()
    expect(study.signalOutcomes.at(-1)?.result).toBe('UNKNOWN')
  })
  it('confirms Indian daily candles at session close and counts ten trading bars across weekends', () => {
    const days: number[] = []
    for (let t = start; days.length < 22; t += 86400) {
      const weekday = new Date((t + 19800) * 1000).getUTCDay()
      if (weekday !== 0 && weekday !== 6) days.push(t)
    }
    const base = setup().map((b, i) => ({ ...b, time: days[i] }))
    const daily = { ...options(days[11] + 22500), seconds: 86400, indian: true }
    expect(analyzeCandles(base, daily).latest?.pattern).toBe('engulfing')
    expect(analyzeCandles(base, { ...daily, asOf: days[11] + 22499 }).latest).toBeNull()
    const all = [
      ...base,
      ...days.slice(12).map((time) => ({ ...bar(0, 100.8, 101, 100, 100.8), time })),
    ]
    const study = analyzeCandles(all, { ...daily, asOf: days[21] + 22500 })
    expect(study.outcomes[0].result).toBe('TIMEOUT')
    expect(study.outcomes[0].time).toBe(days[21])
  })
})

it.each([
  ['NFO', true, { start: 555, end: 940, offset: 19800 }],
  ['MCX', false, { start: 540, end: 1435, offset: 19800 }],
  ['CDS', false, { start: 540, end: 1020, offset: 19800 }],
] as const)('confirms the partial final %s candle only at that contract session close', (exchange, indian, window) => {
  const day = Date.UTC(2026, 9, 30) / 1000,
    close = day - window.offset + window.end * 60,
    last = { ...bar(0), time: close - 1800 },
    scope = { ...options(close), exchange, indian, seconds: 3600, session: window }
  expect(analyzeCandles([last], { ...scope, asOf: close - 1 }).closedTime).toBeNull()
  expect(analyzeCandles([last], scope).closedTime).toBe(last.time)
})

it('uses a tick-aligned outward candlestick stop and exact executable 2R target', () => {
  const study = analyzeCandles(setup(), { ...options(start + 12 * 60), tickSize: 0.05 })
  expect(study.latest?.stop).toBeCloseTo(99.3, 8)
  expect(study.latest?.target).toBeCloseTo(103.8, 8)
  expect(study.latest!.target - study.latest!.entry).toBeCloseTo(
    2 * (study.latest!.entry - study.latest!.stop),
    8
  )
})

it('does not reuse candlestick evidence trained with different market-session rules', () => {
  const study = analyzeCandles(
    setup(),
    { ...options(start + 12 * 60), session: { start: 540, end: 1435, offset: 19800 } },
    seed()
  )
  expect(study.seedUsed).toBe(false)
})

it('keeps configured commodity Daily pattern history across ordinary weekends', () => {
  const stamps: number[] = []
  for (let d = 0; stamps.length < 12; d++) {
    const date = new Date(Date.UTC(2026, 9, 1 + d))
    if (![0, 6].includes(date.getUTCDay())) stamps.push(date.getTime() / 1000)
  }
  const source = setup().map((b, i) => ({ ...b, time: stamps[i] })),
    session = { start: 540, end: 1435, offset: 19800 }
  const r = analyzeCandles(source, {
    ...options(stamps.at(-1)! - session.offset + session.end * 60),
    exchange: 'MCX',
    seconds: 86400,
    session,
    tickSize: 0.05,
  })
  expect(r.latest?.pattern).toBe('engulfing')
  expect(r.support).toBe(99)
})

it('rejects old unrounded probability evidence and accepts a model with identical executable rules', () => {
  const scope = { ...options(start + 12 * 60), tickSize: 0.05 }
  expect(analyzeCandles(setup(), scope, seed()).seedUsed).toBe(false)
  expect(analyzeCandles(setup(), scope, { ...seed(), tickSize: 0.05 }).seedUsed).toBe(true)
})


it('filters chart candle setups by the selected family instead of leaking another pattern', () => {
  expect(detectPattern(setup(), 'rejection')).toBeNull()
  expect(detectPattern(setup(), 'engulfing')?.side).toBe('CALL')
  expect(analyzeCandles(setup(), { ...options(start + 720), pattern: 'rejection' }).latest).toBeNull()
})
it('recognizes a strong marubozu and mirrored bearish candle with strict 2R geometry', () => {
  const source = setup().slice(0, 11)
  source.push(bar(11, 100, 102.05, 99.95, 102))
  for (const bullish of [true, false]) {
    const bars = bullish ? source : source.map(b => ({ ...b, open: 200-b.open, high: 200-b.low, low: 200-b.high, close: 200-b.close }))
    const r = detectPattern(bars, 'marubozu')
    expect(r?.side).toBe(bullish ? 'CALL' : 'PUT')
    expect(r?.pattern).toBe('marubozu')
    expect(Math.abs(r!.target-r!.entry)).toBeCloseTo(2*Math.abs(r!.entry-r!.stop), 8)
  }
})
it('recognizes a three-candle star without consuming future candles', () => {
  const source = [...Array.from({ length: 9 }, (_,i) => bar(i)), bar(9,103,104,99,100), bar(10,99.8,100.1,99.5,99.9), bar(11,100.1,102.2,100.05,102)]
  expect(detectPattern(source, 'star')?.side).toBe('CALL')
  expect(detectPattern(source.slice(0,-1), 'star')).toBeNull()
})
it('does not combine candlestick probabilities trained with a different selected pattern family', () => {
  expect(analyzeCandles(setup(), { ...options(start+720), pattern: 'engulfing' }, seed()).seedUsed).toBe(false)
})
