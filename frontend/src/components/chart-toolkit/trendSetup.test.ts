import { describe, expect, it, vi } from 'vitest'
import type { ISeriesApi, IPriceLine } from 'lightweight-charts'
import { TrendSetupLayer } from './TrendSetupLayer'
import { selectTrendSetup, type TrendSetupEvent } from './trendSetup'
import type { Bar } from './model'

const event: TrendSetupEvent = {
  time: 60, side: 'CALL', name: 'Double Bottom', confirmed: true,
  entry: 100, extreme: 90, target: 120, startTime: 0,
}
const bar = (time: number, values: Partial<Bar> = {}): Bar => ({
  time, open: 100, high: 105, low: 95, close: 102, volume: 1, ...values,
})
const initial = [bar(0), bar(60, { low: 85, high: 125 })]

describe('selectTrendSetup', () => {
  it('ignores the confirmation candle range and derives reward/risk from geometry', () => {
    expect(selectTrendSetup([event], initial, 1)).toMatchObject({
      time: 60, name: 'Double Bottom', side: 'CALL', entry: 100, stop: 90,
      target: 120, rewardRisk: 2, status: 'active',
    })
  })
  it('requires explicit confirmation, directional geometry and a completed anchor bar', () => {
    for (const invalid of [
      { ...event, confirmed: undefined }, { ...event, confirmed: false },
      { ...event, entry: undefined }, { ...event, target: undefined },
      { ...event, side: 'NEUTRAL' as const }, { ...event, extreme: 101 },
      { ...event, target: 99 }, { ...event, target: Number.NaN },
      { ...event, time: 61 }, { ...event, time: 120 },
    ]) expect(selectTrendSetup([invalid], initial, 1)).toBeNull()
  })
  it('rejects invalid ticks and collapsed rounded geometry', () => {
    for (const tick of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(selectTrendSetup([event], initial, tick)).toBeNull()
    }
    expect(selectTrendSetup([{ ...event, entry: 100.1, target: 100.2 }], initial, 1)).toBeNull()
  })
  it('rounds entry and protective levels conservatively for CALL', () => {
    expect(selectTrendSetup([{ ...event, entry: 100.01, extreme: 90.04, target: 120.04 }], initial, 0.05))
      .toMatchObject({ entry: 100.05, stop: 90, target: 120 })
  })
  it('rounds entry and protective levels conservatively for PUT', () => {
    expect(selectTrendSetup([{ ...event, side: 'PUT', entry: 100.04, extreme: 110.01, target: 80.01 }], initial, 0.05))
      .toMatchObject({ entry: 100, stop: 110.05, target: 80.05, status: 'active' })
  })
  it('does not move values already on a tick due to floating point noise', () => {
    expect(selectTrendSetup([{ ...event, entry: 100.1, extreme: 90.1, target: 120.1 }], initial, 0.05))
      .toMatchObject({ entry: 100.1, stop: 90.1, target: 120.1 })
  })
  it.each([
    ['CALL', { low: 89 }, 'stopped'], ['CALL', { high: 121 }, 'target-hit'],
    ['CALL', { low: 89, high: 121 }, 'ambiguous'],
    ['PUT', { high: 111 }, 'stopped'], ['PUT', { low: 79 }, 'target-hit'],
    ['PUT', { low: 79, high: 111 }, 'ambiguous'],
  ] as const)('evaluates %s subsequent OHLC %j as %s', (side, values, status) => {
    const candidate = side === 'CALL' ? event : { ...event, side, extreme: 110, target: 80 }
    const result = selectTrendSetup([candidate], [...initial, bar(120, values)], 1)
    expect(result?.status).toBe(status)
    expect(result?.reason).toBeTruthy()
  })
  it('uses a known gap exit before the later range can create ambiguity', () => {
    expect(selectTrendSetup([event], [...initial, bar(120, { open: 85, low: 80, high: 125 })], 1)?.status).toBe('stopped')
    expect(selectTrendSetup([event], [...initial, bar(120, { open: 125, low: 80, high: 130 })], 1)?.status).toBe('target-hit')
  })
  it('keeps the first terminal result when price later recovers or hits the other level', () => {
    expect(selectTrendSetup([event], [...initial, bar(120, { low: 89 }), bar(180, { high: 125 })], 1)?.status).toBe('stopped')
  })
  it('selects the latest valid geometry and does not fall back after it exits', () => {
    const newer = { ...event, time: 120, name: 'New setup' }
    expect(selectTrendSetup([newer, event], [...initial, bar(120), bar(180, { low: 89 })], 1))
      .toMatchObject({ name: 'New setup', status: 'stopped' })
  })
  it('ignores newer candle events without geometry', () => {
    expect(selectTrendSetup([event, { time: 120, side: 'PUT', confirmed: true, name: 'Hammer', extreme: 110 }], [...initial, bar(120)], 1)?.time).toBe(60)
  })
  it('suppresses opposing setups confirmed simultaneously', () => {
    expect(selectTrendSetup([event, { ...event, side: 'PUT', extreme: 110, target: 80 }], initial, 1)).toBeNull()
  })
  it('replays bars chronologically without mutating input arrays', () => {
    const bars = [...initial, bar(180, { high: 125 }), bar(120, { low: 89 })]
    const before = bars.map((b) => b.time)
    expect(selectTrendSetup([event], bars, 1)?.status).toBe('stopped')
    expect(bars.map((b) => b.time)).toEqual(before)
  })
})


describe('TrendSetupLayer', () => {
  it('owns only three active plan lines and clears them on terminal, null and disposal', () => {
    const unrelated = {} as IPriceLine
    const lines = new Set<IPriceLine>([unrelated])
    const createPriceLine = vi.fn(() => {
      const line = {} as IPriceLine
      lines.add(line)
      return line
    })
    const removePriceLine = vi.fn((line: IPriceLine) => { lines.delete(line) })
    const series = { createPriceLine, removePriceLine } as unknown as ISeriesApi<'Candlestick'>
    const layer = new TrendSetupLayer(series)
    const setup = selectTrendSetup([event], initial, 1)!
    layer.update(setup)
    expect(lines.size).toBe(4)
    expect(createPriceLine.mock.calls.map((call) => (call as unknown as [{ price: number }])[0].price)).toEqual([100, 90, 120])
    layer.update(setup)
    expect(createPriceLine).toHaveBeenCalledTimes(3)
    layer.update({ ...setup, status: 'stopped' })
    expect([...lines]).toEqual([unrelated])
    layer.update(setup)
    layer.update(null)
    expect([...lines]).toEqual([unrelated])
    layer.update({ ...setup, entry: 101 })
    layer.destroy()
    layer.destroy()
    expect([...lines]).toEqual([unrelated])
  })
})

it('rejects zero and negative shape geometry', () => {
  for (const invalid of [{ ...event, extreme: 0 }, { ...event, extreme: -1 }, { ...event, entry: 0 }, { ...event, target: -1 }]) {
    expect(selectTrendSetup([invalid], initial, 1)).toBeNull()
  }
})

it('marks an active setup ambiguous when completed candle history has a gap', () => {
  const result = selectTrendSetup([event], [...initial, bar(180)], 1)
  expect(result?.status).toBe('ambiguous')
  expect(result?.reason).toMatch(/gap|missing/i)
})

it('does not bridge invalid OHLC after confirmation', () => {
  for (const invalid of [{ high: Number.NaN }, { open: 0 }, { low: 110 }, { high: 99 }]) {
    const result = selectTrendSetup([event], [...initial, bar(120, invalid), bar(180)], 1)
    expect(result?.status).toBe('ambiguous')
    expect(result?.reason).toMatch(/invalid|incomplete/i)
  }
})

it('does not let missing history replace an already known terminal exit', () => {
  expect(selectTrendSetup([event], [...initial, bar(120, { low: 89 }), bar(300)], 1)?.status).toBe('stopped')
})

const epoch = (iso: string) => Date.parse(iso) / 1000
const nseClose = epoch('2026-10-29T09:55:00Z')
const nseOpen = epoch('2026-10-30T03:45:00Z')

it('keeps a setup active across a normal NSE overnight closure', () => {
  const result = selectTrendSetup([{ ...event, time: nseClose }], [
    bar(nseClose - 300), bar(nseClose), bar(nseOpen),
  ], 1, { seconds: 300, indian: true })
  expect(result?.status).toBe('active')
})

it.each([
  [{ open: 85, high: 105, low: 80 }, 'stopped'],
  [{ open: 125, high: 130, low: 95 }, 'target-hit'],
] as const)('evaluates the first NSE opening candle %j as %s after a closure', (values, status) => {
  expect(selectTrendSetup([{ ...event, time: nseClose }], [
    bar(nseClose - 300), bar(nseClose), bar(nseOpen, values),
  ], 1, { seconds: 300, indian: true })?.status).toBe(status)
})

it('preserves ambiguity for missing NSE candles during market hours', () => {
  const result = selectTrendSetup([{ ...event, time: nseOpen }], [
    bar(nseOpen), bar(nseOpen + 600),
  ], 1, { seconds: 300, indian: true })
  expect(result?.status).toBe('ambiguous')
})

it('does not treat a crypto overnight gap as a scheduled NSE closure', () => {
  expect(selectTrendSetup([{ ...event, time: nseClose }], [
    bar(nseClose), bar(nseOpen),
  ], 1, { seconds: 300, indian: false })?.status).toBe('ambiguous')
})
