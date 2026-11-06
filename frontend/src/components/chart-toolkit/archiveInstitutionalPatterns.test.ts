import { describe, expect, it } from 'vitest'
import type { Bar } from './model'
import { recognizeInstitutionalPatterns } from './archiveInstitutionalPatterns'

const bars = (prices: number[]): Bar[] =>
  prices.map((p, i) => ({
    time: 1000 + i * 60,
    open: p,
    high: p + 0.4,
    low: p - 0.4,
    close: p,
    volume: 10,
  }))
const qm = (): Bar[] => [
  ...bars([10, 12, 14, 12, 10, 8, 10, 13, 16, 13, 10, 7, 5, 7, 9, 11]),
  { time: 1960, open: 13, high: 14.5, low: 11, close: 12, volume: 10 },
]
const mirror = (history: Bar[]): Bar[] =>
  history.map((b) => ({
    ...b,
    open: 40 - b.open,
    high: 40 - b.low,
    low: 40 - b.high,
    close: 40 - b.close,
  }))
const matches = (history: Bar[], pattern: string) =>
  recognizeInstitutionalPatterns(history).filter((result) => result.pattern === pattern)

// Removing the structural break, confirmed trough, or latest rejection must remove the signal.
describe('archive institutional operational structures', () => {
  it('recognizes a confirmed higher-high / lower-low QM shoulder rejection', () => {
    expect(matches(qm(), 'institutional_qm_retest')).toEqual([
      {
        side: 'PUT',
        pattern: 'institutional_qm_retest',
        name: 'Quasimodo shoulder rejection (operational)',
        extreme: 16.4,
      },
    ])
  })
  it('mirrors QM geometry and direction', () => {
    expect(matches(mirror(qm()), 'institutional_qm_retest')).toEqual([
      {
        side: 'CALL',
        pattern: 'institutional_qm_retest',
        name: 'Quasimodo shoulder rejection (operational)',
        extreme: 23.6,
      },
    ])
  })
  it('requires a closing structural break, not just a wick', () => {
    const h = qm()
    for (const i of [11, 12, 13]) h[i] = { ...h[i], open: 8, close: 8, high: 8.4 }
    expect(matches(h, 'institutional_qm_retest')).toEqual([])
  })
  it('requires the latest candle to touch and reject the shoulder', () => {
    const h = qm()
    h[h.length - 1].high = 14.3
    expect(matches(h, 'institutional_qm_retest')).toEqual([])
  })
  it('does not use an unconfirmed trough or later candles to emit an earlier signal', () => {
    const h = qm()
    const early = [...h.slice(0, 13), { ...h.at(-1)!, time: 1780 }]
    expect(matches(early, 'institutional_qm_retest')).toEqual([])
    for (let end = 1; end < h.length; end++) {
      expect(matches(h.slice(0, end), 'institutional_qm_retest')).toEqual([])
    }
  })
  it('rejects an already retested or invalidated shoulder', () => {
    const h = qm()
    h[15] = { ...h[15], open: 13, high: 14.6, close: 13 }
    expect(matches(h, 'institutional_qm_retest')).toEqual([])
    const invalid = qm()
    invalid.at(-1)!.high = 17
    expect(matches(invalid, 'institutional_qm_retest')).toEqual([])
  })
  it('recognizes an actual confirmed swing support break and first retest', () => {
    const h = [
      ...bars([16, 14, 12, 14, 16, 14, 12, 10, 8, 10, 11]),
      { time: 1660, open: 11.5, high: 12.5, low: 10, close: 11, volume: 10 },
    ]
    expect(matches(h, 'institutional_swing_retest')).toEqual([
      {
        side: 'PUT',
        pattern: 'institutional_swing_retest',
        name: 'Swing support break / resistance retest',
        extreme: 12.5,
      },
    ])
    expect(matches(mirror(h), 'institutional_swing_retest')[0]?.side).toBe('CALL')
    expect(matches(h.slice(0, -1), 'institutional_swing_retest')).toEqual([])
  })
  it('ignores flat, malformed and insufficient histories', () => {
    expect(recognizeInstitutionalPatterns(bars(Array(30).fill(10)))).toEqual([])
    expect(
      recognizeInstitutionalPatterns(qm().map((b, i) => (i === 0 ? { ...b, high: NaN } : b)))
    ).toEqual([])
    expect(recognizeInstitutionalPatterns([])).toEqual([])
  })
})

const wolfe = (): Bar[] => [
  ...bars([12, 11, 10, 12, 15, 18, 16, 13, 8, 10, 12, 14, 11, 8, 4, 4.5]),
  { time: 1960, open: 4.5, high: 6.4, low: 4.3, close: 6, volume: 10 },
]
describe('Wolfe five-pivot operational confirmation', () => {
  it('requires five alternating confirmed pivots, convergence and an overshoot/reclaim', () => {
    expect(matches(wolfe(), 'institutional_wolfe_wave')).toEqual([
      {
        side: 'CALL',
        pattern: 'institutional_wolfe_wave',
        name: 'Wolfe Wave five-pivot reclaim (operational)',
        extreme: 3.6,
      },
    ])
    expect(matches(mirror(wolfe()), 'institutional_wolfe_wave')[0]?.side).toBe('PUT')
    expect(matches(wolfe().slice(0, -1), 'institutional_wolfe_wave')).toEqual([])
  })
  it('rejects a fifth point that did not overshoot the projected 1–3 boundary', () => {
    const h = wolfe()
    h[14] = { ...h[14], open: 6.5, high: 6.9, low: 6.1, close: 6.5 }
    h[15] = { ...h[15], open: 7, high: 7.4, low: 6.6, close: 7 }
    expect(matches(h, 'institutional_wolfe_wave')).toEqual([])
  })
})

describe('QM operational timing labels', () => {
  it('distinguishes quick and late first retests using the documented six-bar cutoff', () => {
    expect(matches(qm(), 'institutional_qm_quick_retest')).toHaveLength(1)
    const h = qm()
    const late = [
      ...h.slice(0, -1),
      ...bars([11, 11.2, 11.4]).map((b, i) => ({ ...b, time: 1960 + i * 60 })),
      { ...h.at(-1)!, time: 2140 },
    ]
    expect(matches(late, 'institutional_qm_late_retest')).toHaveLength(1)
    expect(matches(late, 'institutional_qm_quick_retest')).toEqual([])
  })
  it('labels a second distinct rejected shoulder visit only as operational re-entry', () => {
    const h = qm()
    const again = [
      ...h,
      ...bars([10, 9, 10]).map((b, i) => ({ ...b, time: 2020 + i * 60 })),
      { ...h.at(-1)!, time: 2200 },
    ]
    expect(matches(again, 'institutional_qm_reentry')).toHaveLength(1)
    expect(matches(again, 'institutional_qm_quick_retest')).toEqual([])
  })
})

describe('QM operational context filters', () => {
  it('requires three nested ranges with rising lows for the squeeze qualifier', () => {
    const h = qm()
    h[13] = { ...h[13], open: 9, high: 13, low: 6, close: 10 }
    h[14] = { ...h[14], open: 10, high: 12.8, low: 8, close: 11 }
    h[15] = { ...h[15], open: 11, high: 12.6, low: 10, close: 12 }
    expect(matches(h, 'institutional_qm_squeeze')).toHaveLength(1)
    expect(matches(mirror(h), 'institutional_qm_squeeze')[0]?.side).toBe('CALL')
    expect(matches(qm(), 'institutional_qm_squeeze')).toEqual([])
  })
  it('requires a pre-existing lower-high/lower-low trend for continuation', () => {
    const prefix = bars([26, 28, 30, 27, 24, 20, 23, 25, 28, 24, 18, 12, 13])
    const h = [...prefix, ...qm()].map((b, i) => ({ ...b, time: 1000 + i * 60 }))
    expect(matches(h, 'institutional_qm_continuation')).toHaveLength(1)
    expect(matches(mirror(h), 'institutional_qm_continuation')[0]?.side).toBe('CALL')
    expect(matches(qm(), 'institutional_qm_continuation')).toEqual([])
  })
})

describe('structural negative cases', () => {
  it('does not emit a swing retest before a closing break or without a level touch', () => {
    const h = [
      ...bars([16, 14, 12, 14, 16, 14, 12, 10, 8, 10, 11]),
      { time: 1660, open: 11.5, high: 12.5, low: 10, close: 11, volume: 10 },
    ]
    const untouched = h.map((b) => ({ ...b }))
    untouched.at(-1)!.high = 11.5
    expect(matches(untouched, 'institutional_swing_retest')).toEqual([])
    const unbroken = [
      ...bars([16, 14, 12, 14, 16, 14, 13, 12.8, 12.6, 13, 13.4]),
      { time: 1660, open: 13.4, high: 14, low: 12, close: 13, volume: 10 },
    ]
    expect(matches(unbroken, 'institutional_swing_retest')).toEqual([])
  })
  it('requires Wolfe boundaries to converge and the latest reclaim to be the first', () => {
    const diverging = wolfe()
    diverging[11] = { ...diverging[11], open: 17, high: 17.4, low: 16.6, close: 17 }
    expect(matches(diverging, 'institutional_wolfe_wave')).toEqual([])
    const alreadyReclaimed = wolfe()
    alreadyReclaimed[14] = { ...alreadyReclaimed[14], open: 4, high: 6.2, close: 6 }
    expect(matches(alreadyReclaimed, 'institutional_wolfe_wave')).toEqual([])
  })
})

// Three bars per leg keeps each turning point independently two-sided confirmed.
const turns = (points: number[]): Bar[] => {
  const rising = points[1] < points[0]
  const prices = [points[0] + (rising ? -2 : 2), points[0] + (rising ? -1 : 1), points[0]]
  for (let i = 1; i < points.length; i++) {
    const p = points[i - 1],
      q = points[i]
    prices.push(p + (q - p) / 3, p + (2 * (q - p)) / 3, q)
  }
  const last = points.at(-1)!,
    direction = points.at(-2)! > last ? 1 : -1
  return bars([...prices, last + direction * 0.5, last + direction])
}
const finish = (h: Bar[], close: number, high = h.at(-1)!.close + 0.4): Bar[] => [
  ...h,
  {
    time: h.at(-1)!.time + 60,
    open: h.at(-1)!.close,
    high: Math.max(high, close),
    low: Math.min(close - 0.4, h.at(-1)!.close - 0.4),
    close,
    volume: 10,
  },
]
const genericFixtures: [string, string, () => Bar[]][] = [
  [
    'institutional_liquidity_sweep',
    'Resistance sweep rejection',
    () => finish(turns([20, 10, 20]), 18, 21),
  ],
  [
    'institutional_compression_breakout',
    'Compression breakout',
    () => finish(turns([20, 10, 19, 11, 18, 12]), 10),
  ],
  [
    'institutional_repeated_level_breakout',
    'Repeated support break',
    () => finish(turns([20, 10, 19, 10.1, 18, 10]), 9),
  ],
  [
    'institutional_three_drive',
    'Three-drive reversal break',
    () => finish(turns([20, 10, 23, 14, 25]), 13),
  ],
  [
    'institutional_compressed_range_breakout',
    'Compressed range breakout',
    () => finish(turns([20, 10, 20, 12, 20, 14]), 9),
  ],
  [
    'institutional_diamond_breakout',
    'Expanding-contracting range breakout',
    () => finish(turns([18, 12, 22, 8, 20, 10, 19, 11]), 9),
  ],
  [
    'institutional_flag_limit_retest',
    'Flag supply retest after structure break',
    () => {
      const h = turns([30, 10, 20, 12, 22, 14, 18, 11])
      const result = finish(h, 19, 21)
      result.at(-1)!.open = 20
      return result
    },
  ],
]
describe('archive generic visual families', () => {
  for (const [pattern, name, fixture] of genericFixtures) {
    it(`${name}: confirms the latest completed candle and mirrors direction`, () => {
      const h = fixture()
      expect(matches(h, pattern)).toHaveLength(1)
      expect(matches(h, pattern)[0]).toMatchObject({ side: 'PUT', name })
      expect(matches(mirror(h), pattern)[0]?.side).toBe('CALL')
      expect(matches(h.slice(0, -1), pattern)).toEqual([])
      const noConfirm = h.map((b) => ({ ...b }))
      noConfirm.at(-1)!.close = noConfirm.at(-1)!.open
      expect(matches(noConfirm, pattern)).toEqual([])
    })
  }
  it('exposes the generic S/R flip only after a break and first rejected retest', () => {
    const h = [
      ...bars([16, 14, 12, 14, 16, 14, 12, 10, 8, 10, 11]),
      { time: 1660, open: 11.5, high: 12.5, low: 10, close: 11, volume: 10 },
    ]
    expect(matches(h, 'institutional_sr_flip')).toHaveLength(1)
    expect(matches(h.slice(0, -1), 'institutional_sr_flip')).toEqual([])
  })
})

describe('generic family geometry guards', () => {
  const invalid: [string, () => Bar[]][] = [
    ['institutional_liquidity_sweep', () => finish(turns([20, 10, 20]), 18, 20.4)],
    ['institutional_compression_breakout', () => finish(turns([20, 10, 21, 11, 22, 12]), 10)],
    ['institutional_repeated_level_breakout', () => finish(turns([20, 10, 19, 12, 18, 14]), 9)],
    ['institutional_three_drive', () => finish(turns([20, 10, 23, 14, 27]), 13)],
    ['institutional_compressed_range_breakout', () => finish(turns([18, 10, 20, 12, 22, 14]), 9)],
    ['institutional_diamond_breakout', () => finish(turns([22, 8, 21, 9, 20, 10, 19, 11]), 9)],
    [
      'institutional_flag_limit_retest',
      () => {
        const h = finish(turns([19, 10, 20, 12, 22, 14, 18, 11]), 19, 21)
        h.at(-1)!.open = 20
        return h
      },
    ],
  ]
  for (const [pattern, fixture] of invalid) {
    it(`${pattern} requires its actual defining geometry`, () => {
      expect(matches(fixture(), pattern)).toEqual([])
      expect(matches(mirror(fixture()), pattern)).toEqual([])
    })
  }
  it('uses no future bar for any generic archive family', () => {
    for (const [pattern, , fixture] of genericFixtures) {
      const h = fixture()
      for (let end = 0; end < h.length; end++) expect(matches(h.slice(0, end), pattern)).toEqual([])
    }
  })
})

it('invalidates a flag supply retest when an intervening candle already exceeded supply', () => {
  const fixture = genericFixtures.find(
    ([pattern]) => pattern === 'institutional_flag_limit_retest'
  )![2]
  const h = fixture()
  h[h.length - 2].high = 23
  expect(matches(h, 'institutional_flag_limit_retest')).toEqual([])
})
