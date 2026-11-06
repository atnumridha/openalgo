import { describe, expect, it } from 'vitest'
import { detectShapes } from './shapes'
import { buildLevels } from './levels'
import { advanceBookCandidate } from './engine'
import { TEST_CONTEXT } from './fixtures'
import type { BookEvent } from './types'
import { DEFAULT_BOOK_SETTINGS as S } from './settings'
import { bar, timed } from './fixtures'
import type { BookPivot } from './types'

function geometry(prices: number[], first: 'high' | 'low' = 'high', spacing = 8) {
  const rows = timed(
    Array.from({ length: prices.length * spacing + 5 }, () => bar(100, 101, 99, 100))
  )
  const pivots: BookPivot[] = prices.map((price, i) => ({
    side: i % 2 === 0 ? first : first === 'high' ? 'low' : 'high',
    index: 4 + i * spacing,
    recognitionIndex: 7 + i * spacing,
    price,
    time: rows[4 + i * spacing]!.time,
    recognitionTime: rows[7 + i * spacing]!.time,
  }))
  // Keep the intervening closes inside both boundaries while respecting a pivot's wick.
  for (let j = 0; j < rows.length; j++) {
    const k = Math.min(prices.length - 2, Math.max(0, Math.floor((j - 4) / spacing)))
    const mid = (prices[k]! + prices[k + 1]!) / 2
    rows[j] = { ...rows[j]!, open: mid, close: mid + 0.01, high: mid + 0.1, low: mid - 0.1 }
  }
  for (const p of pivots) rows[p.index] = { ...rows[p.index]!, [p.side]: p.price }
  return { rows, pivots, i: rows.length - 1 }
}
const fixtures = [
  ['symmetrical-triangle', [110, 90, 106, 94], 'high'],
  ['ascending-triangle', [110, 90, 110, 96], 'high'],
  ['descending-triangle', [110, 90, 104, 90], 'high'],
  ['bull-rectangle', [110, 90, 110, 90], 'high'],
  ['bear-rectangle', [110, 90, 110, 90], 'high'],
  ['falling-wedge', [120, 100, 110, 96], 'high'],
  ['rising-wedge', [100, 80, 104, 90], 'high'],
  ['double-bottom', [90, 100, 90], 'low'],
  ['double-top', [110, 100, 110], 'high'],
  ['triple-bottom', [90, 100, 90, 102, 90], 'low'],
  ['triple-top', [110, 100, 110, 98, 110], 'high'],
  ['inverse-head-shoulders', [95, 105, 90, 106, 95], 'low'],
  ['head-shoulders', [105, 95, 110, 94, 105], 'high'],
] as const

describe('independent chart structure geometry', () => {
  for (const [id, prices, first] of fixtures)
    it(`${id}: recognizes contacts but rejects missing last contact`, () => {
      const { rows, pivots, i } = geometry([...prices], first)
      expect(detectShapes(rows, i, S, 0.01, 2, pivots).some((f) => f.patternId === id)).toBe(true)
      expect(
        detectShapes(rows, i, S, 0.01, 2, pivots.slice(0, -1)).some((f) => f.patternId === id)
      ).toBe(false)
    })
  it('75% width is parallel rather than converging', () => {
    const { rows, pivots, i } = geometry([110, 90, 106, 90.5])
    expect(
      detectShapes(rows, i, S, 0.01, 1, pivots).some((f) => f.patternId === 'symmetrical-triangle')
    ).toBe(false)
  })
  it('does not accept a pivot recognized on the breakout candle', () => {
    const { rows, pivots, i } = geometry([110, 90, 110, 96])
    pivots.at(-1)!.recognitionIndex = i
    expect(
      detectShapes(rows, i, S, 0.01, 2, pivots).some((f) => f.patternId === 'ascending-triangle')
    ).toBe(false)
  })
  it('builds median horizontal level versions from separated same-side touches', () => {
    const { pivots } = geometry([110, 90, 110.2, 90.2])
    const levels = buildLevels(pivots, 50, 2, 0.01, S)
    expect(levels.find((l) => l.side === 'resistance')?.price).toBe(110.1)
    expect(levels.find((l) => l.side === 'support')?.price).toBe(90.1)
    expect(levels.every((l) => l.contacts.length === 2)).toBe(true)
  })
  it.each([
    'long',
    'short',
  ] as const)('recognizes %s flag with impulse and rejects excessive retracement', (side) => {
    // Four alternating channel contacts, opposing the pole. Last pivot is known before breakout.
    const bull = side === 'long'
    const prices = bull ? [120, 116, 118, 114] : [80, 84, 82, 86]
    const { rows, pivots, i } = geometry(prices, bull ? 'high' : 'low', 4)
    // Explicit pole preceding first channel contact: 20 price units / 2 ATR.
    rows[0] = bar(bull ? 100 : 100, bull ? 101 : 101, bull ? 99 : 99, bull ? 100 : 100)
    const f = detectShapes(rows, i, S, 0.01, 2, pivots)
    expect(f.some((f) => f.patternId === (bull ? 'bull-flag' : 'bear-flag'))).toBe(true)
    const invalid = rows.map((b) => ({ ...b }))
    invalid[0] = {
      ...invalid[0]!,
      close: bull ? 117 : 83,
      open: bull ? 117 : 83,
      high: bull ? 118 : 84,
      low: bull ? 116 : 82,
    }
    expect(
      detectShapes(invalid, i, S, 0.01, 2, pivots).some(
        (f) => f.patternId === (bull ? 'bull-flag' : 'bear-flag')
      )
    ).toBe(false)
  })
  it('recognizes rounded U cup and shallower upper-third handle, rejecting sharp V', () => {
    const rows = timed(
      Array.from({ length: 91 }, (_, i) => {
        const p =
          i <= 70
            ? 110 - 10 * Math.sin((Math.PI * i) / 70)
            : 110 - 2 * Math.sin((Math.PI * (i - 70)) / 20)
        return bar(p - 0.1, p + 0.3, p - 0.3, p)
      })
    )
    const pivots: BookPivot[] = [
      {
        side: 'high',
        index: 0,
        recognitionIndex: 3,
        time: rows[0]!.time,
        recognitionTime: rows[3]!.time,
        price: 110.3,
      },
      {
        side: 'low',
        index: 35,
        recognitionIndex: 38,
        time: rows[35]!.time,
        recognitionTime: rows[38]!.time,
        price: 99.7,
      },
      {
        side: 'high',
        index: 70,
        recognitionIndex: 73,
        time: rows[70]!.time,
        recognitionTime: rows[73]!.time,
        price: 110.3,
      },
      {
        side: 'low',
        index: 80,
        recognitionIndex: 83,
        time: rows[80]!.time,
        recognitionTime: rows[83]!.time,
        price: 107.7,
      },
    ]
    expect(
      detectShapes(rows, 90, S, 0.01, 2, pivots).some((f) => f.patternId === 'cup-handle')
    ).toBe(true)
    const v = rows.map((b, i) => {
      if (i > 70) return b
      const p = 110 - 10 * (1 - Math.abs(i - 35) / 35) ** 10
      return { ...b, open: p - 0.1, high: p + 0.3, low: p - 0.3, close: p }
    })
    expect(detectShapes(v, 90, S, 0.01, 2, pivots).some((f) => f.patternId === 'cup-handle')).toBe(
      false
    )
  })
})

// A geometry observation only becomes a confirmed structure after a known-boundary close.
describe('every shape family executable price trigger', () => {
  for (const [id, prices, first] of fixtures)
    it(`${id}: confirms only after recognized geometry, not on an equal boundary close`, () => {
      const { rows, pivots, i } = geometry([...prices], first)
      const f = detectShapes(rows, i, S, 0.01, 2, pivots).find((f) => f.patternId === id)!
      const e: BookEvent = {
        ...f,
        id: 'shape',
        formationStart: rows[f.startIndex]!.time,
        formationEnd: rows[f.endIndex]!.time,
        recognitionTime: rows[f.recognitionIndex]!.time,
        status: 'pending',
        nextCondition: 'Break boundary',
      }
      const long = f.side === 'long',
        B = f.trigger
      const equal = rows.map((b) => ({ ...b }))
      equal[i] = { ...bar(B + (long ? -0.5 : 0.5), B + 1, B - 1, B), time: rows[i]!.time }
      expect(advanceBookCandidate({ event: e }, equal, i, TEST_CONTEXT, S).state).toBe('waiting')
      const broken = rows.map((b) => ({ ...b }))
      broken[i] = {
        ...bar(B + (long ? -0.5 : 0.5), B + 1, B - 1, B + (long ? 0.5 : -0.5)),
        time: rows[i]!.time,
      }
      const triggered = advanceBookCandidate({ event: e }, broken, i, TEST_CONTEXT, S)
      if (f.confirmationRule === 'next-boundary') {
        expect(triggered.state).toBe('waiting')
        expect(triggered.candidate.armIndex).toBe(i)
        const next = timed([
          ...broken,
          bar(B + (long ? 0.2 : -0.2), B + 1, B - 1, B + (long ? 0.7 : -0.7)),
        ])
        expect(advanceBookCandidate(triggered.candidate, next, i + 1, TEST_CONTEXT, S).state).toBe(
          'confirmed'
        )
      } else expect(triggered.state).toBe('confirmed')
    })
})
