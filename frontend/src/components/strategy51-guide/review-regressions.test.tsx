import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { deriveOptionEvidence } from './useStrategy51Data'
import { Strategy51Engine } from './engine'
import { Strategy51Layer } from './Strategy51Layer'
import { Strategy51Guide } from './Strategy51Guide'
import { DEFAULT_STRATEGY51_SETTINGS as defaults } from './settings'
import { buildFrames } from './indicators'
import { assessStrategy } from './rules'
import { STRATEGIES_51 } from './catalog'
import type { EvaluationInput, StrategyBar, StrategyContext } from './types'
const start = Date.UTC(2026, 10, 2, 3, 45) / 1000
const bar = (time: number, open = 100, high = 101, low = 99, close = 100): StrategyBar => ({
  time,
  open,
  high,
  low,
  close,
  volume: 100,
})
const context = (
  bars: StrategyBar[],
  seconds = 60,
  symbol = 'TEST09NOV26100CE'
): StrategyContext => ({
  symbol,
  exchange: 'NFO',
  intervalSeconds: seconds,
  now: bars.at(-1)!.time + seconds,
  observedAt: bars.at(-1)!.time + seconds,
  sourceReady: true,
  connected: true,
  marketOpen: false,
  chartType: 'standard',
  tickSize: 0.05,
})
const chain = (expiry = '09NOV26') => ({
  status: 'success',
  underlying: 'TEST',
  expiry_date: expiry,
  fo_exchange: 'NFO',
  atm_strike: 100,
  chain: [90, 100, 110].map((strike) => ({
    strike,
    ce: { symbol: `TEST${expiry}${strike}CE`, label: '', exists: true },
    pe: { symbol: `TEST${expiry}${strike}PE`, label: '', exists: true },
  })),
})
const btst = (expiry = '09NOV26') => {
  const base = start + 105 * 60,
    symbol = `TEST${expiry}100CE`,
    exitAt = start + 86400 + 15 * 60,
    bars = [bar(base - 120), bar(base - 60), bar(base), bar(base + 60, 100, 122, 99, 121)]
  const supplied = [
    {
      strategyId: '6.10',
      kind: 'risk' as const,
      symbol,
      exchange: 'NFO',
      intervalSeconds: 60,
      asOf: base,
      side: 'long' as const,
      description: 'Chosen call and next trading session verified',
      nextSessionExitAt: exitAt,
    },
  ]
  return { base, symbol, exitAt, bars, supplied }
}
it('retains derived BTST eligibility through a new-day forming candle and the next session exit', () => {
  const f = btst(),
    engine = new Strategy51Engine(),
    settings = { ...defaults, selected: '6.10', localTargets: false }
  const run = (observedAt?: number) =>
    engine.reconcile(
      f.bars,
      { ...context(f.bars, 60, f.symbol), ...(observedAt ? { observedAt } : {}) },
      settings,
      { option: deriveOptionEvidence(f.symbol, 'NFO', f.bars, [], chain(), f.supplied, 60) }
    )
  expect(run().plan).toMatchObject({ strategyId: '6.10', entry: 121 })
  f.bars.push(bar(f.exitAt - 900, 122, 123, 121, 122))
  expect(run(f.bars.at(-1)!.time + 5).plan).toMatchObject({ strategyId: '6.10', entry: 121 })
  expect(run().plan?.entry).toBe(121)
  f.bars.push(bar(f.exitAt - 60, 122, 123, 121, 122))
  expect(run().lastPlan?.status).toBe('time-exit')
})
it.each([
  '02NOV26',
  '03NOV26',
])('blocks BTST if expiry %s precedes the explicitly verified next-session exit', (expiry) => {
  const f = btst(expiry)
  if (expiry === '03NOV26') f.supplied[0].nextSessionExitAt += 86400
  const result = new Strategy51Engine().reconcile(
    f.bars,
    context(f.bars, 60, f.symbol),
    { ...defaults, selected: '6.10' },
    { option: deriveOptionEvidence(f.symbol, 'NFO', f.bars, [], chain(expiry), f.supplied, 60) }
  )
  expect(result.plan).toBeUndefined()
  expect(result.rows.find((r) => r.definition.id === '6.10')?.state).toMatch(/needs-/)
})
it('requires next-session calendar context before promoting an overnight call plan', () => {
  const f = btst(),
    supplied = f.supplied.map(({ nextSessionExitAt: _, ...s }) => s)
  const result = new Strategy51Engine().reconcile(
    f.bars,
    context(f.bars, 60, f.symbol),
    { ...defaults, selected: '6.10' },
    { option: deriveOptionEvidence(f.symbol, 'NFO', f.bars, [], chain(), supplied, 60) }
  )
  expect(result.plan).toBeUndefined()
  expect(result.rows.find((r) => r.definition.id === '6.10')?.next).toMatch(/session|calendar/i)
})
const hourlyInput = (opening = false): EvaluationInput => {
  const previous = Array.from({ length: 75 }, (_, i) => bar(start + i * 300)),
    today = Array.from({ length: opening ? 2 : 26 }, (_, i) => bar(start + 86400 + i * 300)),
    frames = buildFrames([...previous, ...today], 300),
    i = frames.length - 1
  frames[i - 1].rsi = 20
  frames[i - 1].bar = bar(frames[i - 1].bar.time, 99, 102, 98, 101)
  frames[i].bar = bar(frames[i].bar.time, 101, 104, 100, 103)
  const ctx = {
    ...context(
      frames.map((f) => f.bar),
      300,
      'TEST'
    ),
    exchange: 'NSE_INDEX',
  }
  const h = Array.from({ length: 15 }, (_, i) => bar(start - (15 - i) * 3600))
  h.at(-1)!.time = start + 6 * 3600
  h.at(-1)!.closeTime = start + 22500
  return {
    frames,
    index: i,
    context: ctx,
    settings: defaults,
    extras: {
      higher: Object.assign(
        {
          symbol: 'TEST',
          exchange: 'NSE_INDEX',
          intervalSeconds: 3600,
          observedAt: ctx.observedAt,
          bars: h,
        },
        { rsi: Array(15).fill(60) }
      ),
    },
  }
}
it('rejects stale hourly bars even when the hourly request timestamp is fresh', () => {
  const a = hourlyInput(),
    r = assessStrategy(STRATEGIES_51.find((d) => d.id === '2.6')!, a)
  expect(r.state).toBe('needs-data')
  expect(r.candidate).toBeUndefined()
})
it('accepts the prior completed session hour before the first current-session hour has closed', () => {
  expect(
    assessStrategy(STRATEGIES_51.find((d) => d.id === '2.6')!, hourlyInput(true)).candidate?.side
  ).toBe('long')
})
const localPlan = () => {
  const base = start + 900,
    bars = [bar(base - 120), bar(base - 60), bar(base)],
    c = context(bars),
    option = {
      symbol: c.symbol,
      exchange: 'NFO',
      underlying: 'TEST',
      expiry: '09NOV26',
      strike: 100,
      optionType: 'CE' as const,
      selection: {
        time: base,
        kind: 'atm' as const,
        source: 'verified-history' as const,
        description: 'Exact09:30 ATM',
      },
    }
  return {
    bars,
    result: new Strategy51Engine().reconcile(bars, c, { ...defaults, selected: '6.9' }, { option }),
  }
}
it('identifies local fallback targets in the default compact guide without expanding Details', () => {
  const { result } = localPlan()
  expect(result.plan?.targetOrigin).toBe('local')
  render(
    <Strategy51Guide
      result={result}
      settings={defaults}
      onChange={() => {}}
      symbol="TEST09NOV26100CE"
      exchange="NFO"
      seconds={60}
    />
  )
  expect(screen.getByLabelText('51 strategy price references')).toHaveTextContent('Local target')
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
})
it('labels local versus source targets on the chart price lines', () => {
  const { bars, result } = localPlan(),
    price = {
      attachPrimitive: vi.fn(),
      detachPrimitive: vi.fn(),
      createPriceLine: vi.fn((x) => x),
      removePriceLine: vi.fn(),
    },
    layer = new Strategy51Layer(price as never)
  layer.update(result, bars, defaults)
  expect(price.createPriceLine.mock.calls.some((c) => c[0].title === '51 Local target')).toBe(true)
  layer.update({ ...result, plan: { ...result.plan!, targetOrigin: 'source' } }, bars, defaults)
  expect(price.createPriceLine.mock.calls.at(-1)?.[0].title).toBe('51 Target')
  layer.destroy()
})
