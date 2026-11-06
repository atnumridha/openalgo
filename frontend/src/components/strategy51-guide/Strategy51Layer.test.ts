import { expect, it, vi } from 'vitest'
import { toStrategy51Drawing, Strategy51Layer } from './Strategy51Layer'
import { DEFAULT_STRATEGY51_SETTINGS } from './settings'
import type { Strategy51Result, StrategyEvent } from './types'
import { bookDrawingWorklist } from '../book-pattern-guide/BookPatternLayer'
import { DEFAULT_BOOK_SETTINGS } from '../book-pattern-guide/settings'
const bars = Array.from({ length: 20 }, (_, i) => ({
  time: 1700000000 + i * 300,
  open: 100,
  high: 102,
  low: 98,
  close: 101,
  volume: 100,
}))
const event = (i: number): StrategyEvent => ({
  id: `s${i}`,
  strategyId: '7.4',
  name: '7.4 Pullback',
  side: 'long',
  signalIndex: i - 1,
  index: i,
  entry: 103,
  stop: 98,
  target: 118,
  targetMethod: 'Source3R',
  stopMethod: 'Retest low',
  expected: 'Bullish',
  next: 'Monitor',
  exitRule: 'Stop or3R',
  notes: [],
  points: [
    { index: i - 1, price: 98, role: 'signal' },
    { index: i, price: 103, role: 'confirmation' },
  ],
  time: bars[i].time + 300,
  signalTime: bars[i - 1].time,
})
const result = (e: StrategyEvent[]): Strategy51Result => ({
  rows: [],
  events: e,
  readiness: 'ready',
  reason: 'Verified',
  next: 'Monitor',
  expected: 'Bullish',
  trend: 'bull',
  scope: 'NSE:TEST:300',
  processed: 20,
  trendLines: [],
  frames: bars.map((bar, index) => ({ bar, index })) as Strategy51Result['frames'],
})
it('links strategy labels to the actual source candle, while display retention uses confirmation candles', () => {
  const r = toStrategy51Drawing(result([event(9), event(10), event(18)]), {
    ...DEFAULT_STRATEGY51_SETTINGS,
    showOtherSetups: true,
  })
  expect(r.events[2].points[0]).toMatchObject({ time: bars[17].time, price: 98, role: 'low' })
  expect(r.events[2].formationEnd).toBe(bars[17].time)
  expect(r.events[2].confirmationTime).toBe(bars[18].time)
  expect(bookDrawingWorklist(r, bars, DEFAULT_BOOK_SETTINGS).map((e) => e.id)).toEqual([
    's10',
    's18',
  ])
})
it('owns only its own lines/primitives, allows a conditional exit without a fake Target, and fully clears on disable', () => {
  const price = {
    attachPrimitive: vi.fn(),
    detachPrimitive: vi.fn(),
    createPriceLine: vi.fn((x) => x),
    removePriceLine: vi.fn(),
  }
  const r = result([event(18)])
  r.plan = {
    ...event(18),
    stop: 98,
    target: undefined,
    createdAt: bars[18].time + 300,
    createdIndex: 18,
    status: 'active',
  }
  const layer = new Strategy51Layer(price as never)
  layer.update(r, bars, DEFAULT_STRATEGY51_SETTINGS)
  expect(price.createPriceLine.mock.calls.map((c) => c[0].title)).toEqual(['51 Entry', '51 SL'])
  layer.update(null, [], DEFAULT_STRATEGY51_SETTINGS)
  expect(price.removePriceLine).toHaveBeenCalledTimes(2)
  layer.destroy()
  expect(price.detachPrimitive).toHaveBeenCalledTimes(1)
})
it('does not attach a drawing primitive while the new study is disabled', () => {
  const price = {
    attachPrimitive: vi.fn(),
    detachPrimitive: vi.fn(),
    createPriceLine: vi.fn(),
    removePriceLine: vi.fn(),
  }
  const layer = new Strategy51Layer(price as never)
  expect(price.attachPrimitive).not.toHaveBeenCalled()
  layer.update(null, [], DEFAULT_STRATEGY51_SETTINGS)
  expect(price.attachPrimitive).not.toHaveBeenCalled()
  layer.update(result([event(18)]), bars, DEFAULT_STRATEGY51_SETTINGS)
  expect(price.attachPrimitive).toHaveBeenCalledTimes(1)
  layer.update(null, [], DEFAULT_STRATEGY51_SETTINGS)
  expect(price.detachPrimitive).toHaveBeenCalledTimes(1)
  layer.destroy()
  expect(price.detachPrimitive).toHaveBeenCalledTimes(1)
})
it('uses short recognizable chart names while retaining the strategy ID', () => {
  const r = toStrategy51Drawing(
    result([
      {
        ...event(18),
        strategyId: '3.4',
        name: '3.4 · Mastering Fractal-Based Trading: A Personal Approach',
      },
    ]),
    { ...DEFAULT_STRATEGY51_SETTINGS, showOtherSetups: true }
  )
  expect(r.events[0].name).toBe('3.4 · Fractal breakout')
})

it('draws only the selected plan by default and makes other confirmed setups opt-in', () => {
  const r = result([event(11), event(15), event(18)])
  r.plan = {
    ...event(15),
    stop: 98,
    createdAt: bars[15].time + 300,
    createdIndex: 15,
    status: 'active',
  }
  expect(toStrategy51Drawing(r).events.map((e) => e.id)).toEqual(['s15'])
  expect(
    toStrategy51Drawing(r, { ...DEFAULT_STRATEGY51_SETTINGS, showOtherSetups: true }).events
  ).toHaveLength(3)
  expect(toStrategy51Drawing({ ...r, plan: undefined }).events).toEqual([])
})
