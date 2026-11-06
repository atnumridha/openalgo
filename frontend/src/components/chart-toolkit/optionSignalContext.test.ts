import { expect, it } from 'vitest'
import {
  optionContextStates,
  volumePCR,
  ivComparison,
  normalizeFeedExpiry,
  type OptionSignalSnapshot,
} from './optionSignalContext'
import { optionPrice } from './model'

const now = 1800000000
it('normalizes the futures master expiry formats before selecting a current contract', () => {
  expect(normalizeFeedExpiry('24-NOV-26')).toBe('24NOV26')
  expect(normalizeFeedExpiry('24-Nov-2026')).toBe('24NOV26')
  expect(normalizeFeedExpiry('24NOV26')).toBe('24NOV26')
  expect(normalizeFeedExpiry('2026-11-24')).toBe('24NOV26')
  expect(normalizeFeedExpiry('unknown')).toBe('')
})
const current: OptionSignalSnapshot = {
  identity: 'NIFTY:NFO:27OCT27',
  observedAt: now,
  expiry: now + 86400,
  pcr: 0.8,
  ceIV: { value: 18, previous: 20, time: now - 60 },
  peIV: { value: 21, previous: 19, time: now - 60 },
  future: { symbol: 'NIFTY_FUT', price: 102, oi: 1100 },
}
const previous = {
  ...current,
  observedAt: now - 30,
  future: { symbol: 'NIFTY_FUT', price: 100, oi: 1000 },
}
it('does not signal from CE and PE IV changes covering different completed minutes', () => {
  const snapshot = { ...current, peIV: { value: 21, previous: 20, time: now - 30 } }
  expect(
    optionContextStates(snapshot, previous, current.identity, now).find(
      (state) => state.key === 'iv'
    )?.side
  ).toBe('WAIT')
})
const evaluate = (
  c: OptionSignalSnapshot | undefined = current,
  p: OptionSignalSnapshot | undefined = previous,
  expected = current.identity,
  asOf = now
) => optionContextStates(c, p, expected, asOf)

it('standalone IV chooses CALL only when CE IV falls and PUT only when PE IV falls', () => {
  const call = evaluate().find((s) => s.key === 'iv')!
  expect(call).toMatchObject({ side: 'CALL', value: 18, time: now - 60 })
  expect(call.reason).toMatch(/CE IV/i)
  expect(call.reason).toMatch(/PE IV/i)
  expect(call.reason).toMatch(/standalone/i)
  expect(call.reason).toMatch(/app-defined/i)
  expect(call.reason).toMatch(/pricing comparison/i)
  const put = evaluate({
    ...current,
    ceIV: { value: 21, previous: 20, time: now - 60 },
    peIV: { value: 17, previous: 19, time: now - 60 },
  }).find((s) => s.key === 'iv')!
  expect(put).toMatchObject({ side: 'PUT', value: 17, time: now - 60 })
  expect(put.reason).not.toMatch(/EMA|SMA|confirmation/i)
})

it.each([
  { ce: 18, pe: 17, label: 'both falling' },
  { ce: 22, pe: 23, label: 'neither falling' },
  { ce: 20, pe: 19, label: 'unchanged' },
])('keeps standalone IV ambiguous when $label', ({ ce, pe }) => {
  const iv = evaluate({
    ...current,
    ceIV: { value: ce, previous: 20, time: now - 60 },
    peIV: { value: pe, previous: 19, time: now - 60 },
  }).find((s) => s.key === 'iv')!
  expect(iv).toMatchObject({ side: 'WAIT', value: ce, time: now - 60 })
  expect(iv.reason).toMatch(/CE IV/i)
  expect(iv.reason).toMatch(/PE IV/i)
  expect(iv.reason).toMatch(/standalone/i)
})

it.each([
  { ceIV: null },
  { peIV: null },
  { ceIV: { value: 0, previous: 20, time: now - 60 } },
  { peIV: { value: 21, previous: Number.NaN, time: now - 60 } },
  { ceIV: { value: Number.POSITIVE_INFINITY, previous: 20, time: now - 60 } },
  { peIV: { value: 21, previous: -1, time: now - 60 } },
  { ceIV: { value: 18, previous: 20, time: now - 91 } },
  { peIV: { value: 21, previous: 19, time: now - 91 } },
  { ceIV: { value: 18, previous: 20, time: now + 1 } },
  { peIV: { value: 21, previous: 19, time: Number.NaN } },
])('requires fresh valid comparisons for both IV legs: %o', (invalid) => {
  expect(evaluate({ ...current, ...invalid }).find((s) => s.key === 'iv')).toMatchObject({
    side: 'WAIT',
    value: null,
    time: null,
  })
})

it.each([
  { ratio: 0.8, side: 'CALL' },
  { ratio: 1.3, side: 'PUT' },
  { ratio: 1, side: 'WAIT' },
])('PCR independently maps volume ratio $ratio to $side', ({ ratio, side }) => {
  const pcr = evaluate({ ...current, pcr: ratio, ceIV: null, peIV: null, future: null }).find(
    (s) => s.key === 'pcr'
  )!
  expect(pcr).toMatchObject({ value: ratio, side, time: now })
  expect(pcr.reason).not.toMatch(/EMA|SMA|confirmation/i)
})

it.each([
  null,
  0,
  -1,
  Number.NaN,
  Number.POSITIVE_INFINITY,
])('does not assign PCR direction to missing or invalid ratio %s', (pcr) => {
  expect(evaluate({ ...current, pcr }).find((s) => s.key === 'pcr')).toMatchObject({
    value: null,
    side: 'WAIT',
    time: null,
  })
})

it.each([
  now - 91,
  now + 1,
  Number.NaN,
])('rejects a stale or invalid PCR source time %s inside a fresh bundled snapshot', (pcrObservedAt) => {
  const result = evaluate({ ...current, pcrObservedAt })
  expect(result.find((s) => s.key === 'pcr')).toMatchObject({
    value: null,
    side: 'WAIT',
    time: null,
  })
  expect(result.find((s) => s.key === 'iv')?.side).toBe('CALL')
  expect(result.find((s) => s.key === 'oi')?.side).toBe('CALL')
})

it('dates standalone PCR with its own fresh source time', () => {
  expect(
    evaluate({ ...current, pcrObservedAt: now - 90 }).find((s) => s.key === 'pcr')
  ).toMatchObject({
    value: 0.8,
    side: 'CALL',
    time: now - 90,
  })
})

it.each([
  now - 1,
  now,
  undefined,
  Number.NaN,
  Number.POSITIVE_INFINITY,
])('invalid option expiry %s blocks option context without blocking futures OI', (expiry) => {
  const result = evaluate({ ...current, expiry })
  expect(result.find((s) => s.key === 'iv')?.side).toBe('WAIT')
  expect(result.find((s) => s.key === 'pcr')?.side).toBe('WAIT')
  expect(result.find((s) => s.key === 'oi')).toMatchObject({
    side: 'CALL',
    value: 1100,
    time: now,
  })
})

it('OI direction does not depend on the option observations', () => {
  expect(
    evaluate({ ...current, pcr: null, ceIV: null, peIV: null }).find((s) => s.key === 'oi')?.side
  ).toBe('CALL')
})
it.each([
  now - 91,
  now + 1,
  Number.NaN,
])('rejects stale or invalid futures source time %s inside a fresh bundled snapshot', (futureObservedAt) => {
  const result = evaluate({ ...current, futureObservedAt })
  expect(result.find((s) => s.key === 'oi')).toMatchObject({
    value: null,
    side: 'WAIT',
    time: null,
  })
  expect(result.find((s) => s.key === 'iv')?.side).toBe('CALL')
  expect(result.find((s) => s.key === 'pcr')?.side).toBe('CALL')
})

it('dates and compares OI using its own source timestamps instead of bundle arrival times', () => {
  const result = evaluate(
    { ...current, futureObservedAt: now - 10 },
    { ...previous, observedAt: now, futureObservedAt: now - 20 }
  )
  expect(result.find((s) => s.key === 'oi')).toMatchObject({
    value: 1100,
    side: 'CALL',
    time: now - 10,
  })
})

it.each([
  now - 91,
  now - 10,
  now - 5,
  now + 1,
  Number.NaN,
])('rejects stale, repeated, or out-of-order prior futures source time %s', (futureObservedAt) => {
  const result = evaluate(
    { ...current, futureObservedAt: now - 10 },
    { ...previous, futureObservedAt }
  )
  expect(result.find((s) => s.key === 'oi')?.side).toBe('WAIT')
})

it('futures OI requires rising OI and a matching futures price move', () => {
  expect(evaluate().find((s) => s.key === 'oi')?.side).toBe('CALL')
  expect(
    evaluate({ ...current, future: { ...current.future!, price: 98 } }).find((s) => s.key === 'oi')
      ?.side
  ).toBe('PUT')
  expect(
    evaluate({ ...current, future: { ...current.future!, oi: 900 } }).find((s) => s.key === 'oi')
      ?.side
  ).toBe('WAIT')
})
it('stale, future-dated, invalid-time, and wrong-scope snapshots cannot signal', () => {
  for (const c of [
    { ...current, observedAt: now - 100 },
    { ...current, observedAt: now + 1 },
    { ...current, observedAt: Number.NaN },
  ]) {
    expect(evaluate(c).every((s) => s.side === 'WAIT')).toBe(true)
  }
  expect(evaluate(current, previous, 'SENSEX:BFO:27OCT27').every((s) => s.side === 'WAIT')).toBe(
    true
  )
})
it('missing, zero, repeated, and different-future OI observations cannot signal', () => {
  for (const c of [
    { ...current, future: null },
    { ...current, future: { ...current.future!, oi: 0 } },
  ]) {
    expect(evaluate(c).find((s) => s.key === 'oi')?.side).toBe('WAIT')
  }
  expect(evaluate(current, current).find((s) => s.key === 'oi')?.side).toBe('WAIT')
  expect(
    evaluate(current, { ...previous, future: { ...previous.future!, symbol: 'OTHER' } }).find(
      (s) => s.key === 'oi'
    )?.side
  ).toBe('WAIT')
})

it.each([
  { observedAt: now - 100 },
  { identity: 'SENSEX:BFO:27OCT27' },
  { future: { ...previous.future!, oi: Number.POSITIVE_INFINITY } },
  { future: { ...previous.future!, price: Number.POSITIVE_INFINITY } },
])('rejects stale or invalid prior futures OI context %o', (invalid) => {
  expect(evaluate(current, { ...previous, ...invalid }).find((s) => s.key === 'oi')?.side).toBe(
    'WAIT'
  )
})
it('PCR uses quoted volume and rejects missing/empty volume instead of inventing zero ratios', () => {
  expect(volumePCR([{ ce: { volume: 200 }, pe: { volume: 100 } }])).toBe(0.5)
  expect(volumePCR([{ ce: { volume: 0 }, pe: { volume: 0 } }])).toBeNull()
  expect(volumePCR([{ ce: { volume: 200 }, pe: {} }])).toBeNull()
})
it('computes falling IV from two matched completed candles and rejects stale values', () => {
  const expiry = now + 30 * 86400
  const times = [now - 180, now - 120]
  const spot = times.map((time) => ({
    time,
    open: 100,
    high: 100,
    low: 100,
    close: 100,
    volume: 0,
  }))
  const option = times.map((time, i) => {
    const close = optionPrice(100, 100, (expiry - time - 60) / 31536000, 0, 0, i ? 0.18 : 0.2, true)
    return { time, open: close, high: close, low: close, close, volume: 100 }
  })
  const result = ivComparison(option, spot, expiry, 100, true, now)
  expect(result?.value).toBeCloseTo(18, 3)
  expect(result?.previous).toBeCloseTo(20, 3)
  expect(ivComparison(option, spot, expiry, 100, true, now + 600)).toBeNull()
})
