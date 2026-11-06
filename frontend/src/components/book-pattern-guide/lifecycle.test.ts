import { describe, it, expect } from 'vitest'
import { advanceBookPlan, chooseBookPlan, qualifyBookEvent } from './engine'
import { DEFAULT_BOOK_SETTINGS as S } from './settings'
import { TEST_CONTEXT, bar } from './fixtures'
import type { BookEvent, BookPlan } from './types'
const event = (side: 'long' | 'short', rank = 3): BookEvent => ({
  id: `${side}-${rank}`,
  patternId: `test-${rank}`,
  name: 'Fixture',
  side,
  sourcePhotos: [49],
  kind: 'candle',
  mode: 'neutral',
  formationStart: 100,
  formationEnd: 160,
  recognitionTime: 160,
  recognitionIndex: 1,
  startIndex: 0,
  endIndex: 1,
  status: 'confirmed',
  confirmationTime: 220,
  confirmationIndex: 2,
  trigger: side === 'long' ? 100 : 110,
  stopAnchor: side === 'long' ? 98 : 112,
  stopMethod: 'source anchor',
  targetMethod: 'r-multiple',
  scale: 2,
  contacts: 2,
  rank,
  points: [],
  segments: [],
  nextCondition: 'Later close',
  notes: [],
})
const plan = (side: 'long' | 'short' = 'long'): BookPlan => ({
  id: 'p',
  eventId: 'e',
  side,
  name: 'Fixture',
  createdAt: 100,
  createdIndex: 1,
  entry: 100,
  stop: side === 'long' ? 98 : 102,
  target: side === 'long' ? 106 : 94,
  rr: 3,
  status: 'active',
  targetMethod: 'r-multiple',
  stopMethod: 'source anchor',
  notes: [],
})
describe('one frozen reference plan', () => {
  it('waits on opposing qualified sides independent of iteration order', () => {
    expect(chooseBookPlan([plan(), { ...plan('short'), id: 's' }], []).reason).toContain(
      'Conflicting'
    )
    expect(chooseBookPlan([{ ...plan('short'), id: 's' }, plan()], []).plan).toBeUndefined()
  })
  it('uses fixed source rank, contact count, formation recency then lexical ID', () => {
    const a = { ...plan(), id: 'a', eventId: 'a' },
      b = { ...plan(), id: 'b', eventId: 'b' }
    expect(
      chooseBookPlan(
        [a, b],
        [
          { ...event('long', 3), id: 'a' },
          { ...event('long', 0), id: 'b' },
        ]
      ).plan?.id
    ).toBe('b')
  })
  it.each([
    'long',
    'short',
  ] as const)('uses inclusive %s stop/target touches and ambiguous result', (side) => {
    const p = plan(side)
    expect(advanceBookPlan(p, bar(100, 106, 98, 100), 2, S)?.status).toBe(
      side === 'long' ? 'ambiguous' : 'stop-touched'
    )
    expect(advanceBookPlan(p, bar(100, 106, 94, 100), 2, S)?.status).toBe('ambiguous')
  })
  it('expires exactly after fifty later closed candles', () => {
    expect(advanceBookPlan(plan(), bar(100, 101, 99, 100), 50, S)?.status).toBe('active')
    expect(advanceBookPlan(plan(), bar(100, 101, 99, 100), 51, S)?.status).toBe('expired')
  })
  it('buffers source stops outward and never stretches a measured target for RR', () => {
    const e = {
      ...event('long'),
      targetMethod: 'measured' as const,
      measuredBoundary: 100,
      measuredHeight: 3,
    }
    const q = qualifyBookEvent(e, bar(100, 102, 99, 101), 2, TEST_CONTEXT, S, [], {
      trend: 'bull',
      maFast: 99,
      rsi: 60,
      macd: 1,
      macdSignal: 0,
      volumeMean: 100,
    })
    expect(q.plan).toBeUndefined()
    expect(q.reason).toContain('reward/risk')
    const local = qualifyBookEvent(event('long'), bar(100, 102, 99, 101), 2, TEST_CONTEXT, S, [], {
      trend: 'bull',
      maFast: 99,
      rsi: 60,
      macd: 1,
      macdSignal: 0,
      volumeMean: 100,
    })
    expect(local.plan?.stop).toBe(97.9)
    expect(local.plan?.target).toBe(110.3)
  })
  it('withholds confirmation-bar stop breaches and enabled missing-volume filters', () => {
    expect(
      qualifyBookEvent(event('long'), bar(100, 102, 97, 101), 2, TEST_CONTEXT, S, [], {
        trend: 'bull',
        maFast: 99,
      }).reason
    ).toContain('stop')
    expect(
      qualifyBookEvent(
        event('long'),
        { ...bar(100, 102, 99, 101), volume: 0 },
        2,
        TEST_CONTEXT,
        { ...S, volumeFilter: true },
        [],
        { trend: 'bull', maFast: 99 }
      ).reason
    ).toContain('volume')
  })
})
