import { expect, it } from 'vitest'
import { videoStrategyGuide, chooseVideoSetup, VIDEO_STRATEGIES } from './videoStrategyGuide.js'
import fixtures from '/Users/nmandal/Documents/AlgoTrading/openalgo/scripts/tradingview/validation/video-strategy-fixtures.json'
const stamp = (bars: any[]) =>
  bars.map((b, i) => ({ ...b, time: fixtures.start + i * 60, volume: 1 }))
const read = (bars: any[], more = {}) =>
  videoStrategyGuide(stamp(bars), {
    seconds: 60,
    asOf: fixtures.start + bars.length * 60,
    tickSize: 0.5,
    ...more,
  })
const mirror = (bars: any[]) =>
  bars.map((b) => ({
    open: 300 - b.open,
    high: 300 - b.low,
    low: 300 - b.high,
    close: 300 - b.close,
  }))
it('lists fifteen methods with fourteen supported recipes and KRM visibly unavailable', () => {
  const result = read([])
  expect(VIDEO_STRATEGIES).toHaveLength(15)
  expect(VIDEO_STRATEGIES.filter((s) => s.supported)).toHaveLength(14)
  expect(result.readings.find((r) => r.id === 'krm')).toMatchObject({
    status: 'incomplete',
    event: null,
  })
})
for (const c of fixtures.cases) {
  it(`derives the ${c.name} plan from actual completed OHLC`, () => {
    const result = read(c.bars)
    const event = result.readings.find((r: any) => r.id === c.want.strategy)?.event
    expect(event).toMatchObject(c.want)
    if (c.want.entry) expect(event.status).toBe('entry')
  })
  it(`mirrors ${c.name} prices and direction without reusing a Long rule`, () => {
    const event = read(mirror(c.bars)).readings.find((r: any) => r.id === c.want.strategy)?.event
    expect(event).toBeTruthy()
    for (const key of ['watch', 'entry', 'stop', 'target'] as const) {
      if ((c.want as any)[key] != null)
        expect(event[key]).toBeCloseTo(300 - (c.want as any)[key], 8)
    }
  })
}
it('never enters on the FVG creation bar, and keeps a frozen OTE leg', () => {
  const bars = fixtures.cases[0].bars.slice(0, -1)
  const r = read(bars)
  const fvg = r.readings.find((r: any) => r.id === 'fvg')!.event!
  expect(fvg.status).toBe('waiting')
  expect(fvg.entry).toBeNull()
  const ote = r.readings.find((r: any) => r.id === 'ote')!.event!
  expect(ote).toMatchObject({ watch: 101, stop: 92.5, target: 120 })
  expect(ote.status).toBe('invalidated') // following bar has already reached its frozen target
})
it('requires the watched midpoint, not just any overlap with the FVG', () => {
  const bars = fixtures.cases[0].bars.slice(0, -1)
  bars.push({ open: 117, high: 119, low: 114, close: 116 })
  expect(read(bars).readings.find((r: any) => r.id === 'fvg')?.event?.status).toBe('waiting')
})
it('does not confirm a structure break on an equal close or a wick-only excursion', () => {
  const bars = fixtures.cases[0].bars.slice(0, -3)
  const r = read([...bars, { open: 110, high: 120, low: 109, close: 115 }])
  expect(r.events.filter((e: any) => ['bos', 'choch'].includes(e.strategy))).toEqual([])
})
it('never makes forming or future bars confirmed by a timer alone', () => {
  const c = fixtures.cases[0].bars
  const result = read(c, { asOf: fixtures.start + (c.length - 1) * 60 })
  expect(result.readings.find((r: any) => r.id === 'fvg')?.event?.entry).toBeNull()
  expect(result.closedTime).toBe(fixtures.start + (c.length - 1) * 60)
})
it('freezes historical knowledge: appending future bars preserves earlier transition records', () => {
  const bars = fixtures.cases[0].bars
  const prefix = read(bars.slice(0, -1))
  const full = read(bars)
  expect(full.history.filter((h: any) => h.at <= prefix.closedTime)).toEqual(prefix.history)
})
it('cancels pending plans across missing intervals and rejects malformed prices', () => {
  const c = fixtures.cases[0].bars
  const input = stamp(c)
  input[input.length - 1].time += 60
  const r = videoStrategyGuide(input, { seconds: 60, asOf: input.at(-1)!.time + 60, tickSize: 0.5 })
  expect(r.readings.find((r: any) => r.id === 'fvg')?.event?.status).toBe('expired')
  const malformed = c.map((b, i) => (i === c.length - 1 ? { ...b, high: 1 } : b))
  expect(read(malformed).available).toBe(false)
})
it('does not manufacture a priced plan without tick metadata or stale verification', () => {
  const result = read(fixtures.cases[0].bars, { tickSize: 0 })
  expect(result.available).toBe(false)
  expect(chooseVideoSetup(result).action).toBe('Unavailable')
})
it('does not revive a stopped plan or imply a retroactive fill on a two-sided bar', () => {
  const c = fixtures.cases[0].bars.slice(0, -1)
  const r = read([...c, { open: 116, high: 152, low: 103, close: 115 }])
  const e = r.readings.find((r: any) => r.id === 'fvg')?.event
  expect(e.status).toBe('ambiguous')
  expect(e.entry).toBeNull()
  expect(chooseVideoSetup(r, 'fvg').action).not.toMatch(/^Review/)
})

it('keeps a red midpoint retest of a bullish FVG as waiting', () => {
  const bars = fixtures.cases[0].bars.map((b) => ({ ...b }))
  bars[bars.length - 1].open = 117
  expect(read(bars).readings.find((r: any) => r.id === 'fvg')?.event?.entry).toBeNull()
})
it('a prior entry condition cannot become a fresh review on a later candle', () => {
  const bars = [...fixtures.cases[0].bars, { open: 116, high: 118, low: 115, close: 117 }]
  const selection = chooseVideoSetup(read(bars), 'fvg')
  expect(selection.action).toBe('Wait')
  expect(selection.reason).toMatch(/earlier candle|history/i)
})

it('only pending plans expire at twenty bars; an already observed entry stays historical until invalidated', () => {
  const c = fixtures.cases[0].bars
  const r = read([
    ...c,
    ...Array.from({ length: 22 }, () => ({ open: 117, high: 118, low: 116, close: 117 })),
  ])
  expect(r.readings.find((r: any) => r.id === 'fvg')?.event?.status).toBe('entry')
  expect(chooseVideoSetup(r, 'fvg').action).toBe('Wait')
})
it('dates full sweep/CHoCH setup confirmation when the later required zone becomes knowable', () => {
  const bars = fixtures.cases[0].bars.slice(0, -1)
  const r = read(bars),
    e = r.readings.find((x) => x.id === 'choch')!.event!
  expect(e.status).toBe('waiting')
  expect(e.confirmedAt).toBe(r.closedTime)
  expect(e.confirmedBar).toBe(r.lastBarTime)
})
it('Auto prefers a priced confirmed observation over newer or tied unconfirmed geometry', () => {
  const result = read(fixtures.cases[0].bars.slice(0, 36))
  expect(chooseVideoSetup(result).event).toMatchObject({
    strategy: 'ob',
    status: 'waiting',
    priced: true,
  })
  expect(chooseVideoSetup(result, 'fvg').event?.status).toBe('watching')
})
it('reports daily and higher video sources as unsupported instead of silently discarding each session', () => {
  const bars = fixtures.cases[0].bars.map((b, i) => ({ ...b, time: fixtures.start + i * 86400 }))
  const result = videoStrategyGuide(bars, {
    seconds: 86400,
    asOf: fixtures.start + bars.length * 86400,
    tickSize: 0.5,
    indian: true,
  })
  expect(result.available).toBe(false)
  expect(result.reason).toMatch(/intraday/i)
  expect(chooseVideoSetup(result).action).toBe('Unavailable')
})
