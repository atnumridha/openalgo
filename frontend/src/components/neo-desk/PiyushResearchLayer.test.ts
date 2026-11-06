import { describe, it, expect, vi } from 'vitest'
import { PiyushResearchLayer } from './PiyushResearchLayer'
import * as research from './piyushResearchEngine.js'
vi.mock('lightweight-charts', () => ({
  LineSeries: {},
  createSeriesMarkers: () => ({ setMarkers: vi.fn() }),
}))
describe('Piyush index overlay', () => {
  it('clears every plot when disabled or on a premium chart', () => {
    const series = Array.from({ length: 7 }, () => ({ setData: vi.fn() }))
    let n = 0
    const chart = { addSeries: vi.fn(() => series[n++]) }
    const price = { attachPrimitive: vi.fn() }
    const layer = new PiyushResearchLayer(chart as never, price as never)
    expect(layer.update([], 'off', 3, 'NIFTY', '1m', 0, 0)).toContain('off')
    expect(layer.update([], 'ema_cross_1m', 3, 'NIFTY26CE', '1m', 0, 0)).toContain('1-minute')
    expect(series.every((s) => s.setData.mock.lastCall?.[0].length === 0)).toBe(true)
  })
})

it('maps confirmed minute studies inside the latest 15m candle without adding minute time points', () => {
  const t = 1793332800,
    source = [0, 60, 600].map((offset) => ({
      time: t + offset,
      open: 100,
      high: 102,
      low: 98,
      close: 101,
    }))
  const result = {
    values: {
      fast: [null, 101, 102],
      slow: [null, 100, 100],
      upper: [null, null, null],
      lower: [null, null, null],
      ready: [1, 1, 1],
      direction: [null, null, 1],
      event: [null, null, 1],
    },
    trades: [],
    status: 'ready',
  }
  const compute = vi.spyOn(research, 'compute').mockReturnValue(result as never)
  const series = Array.from({ length: 7 }, () => ({ setData: vi.fn() }))
  let n = 0
  const layer = new PiyushResearchLayer(
    { addSeries: () => series[n++] } as never,
    { attachPrimitive: vi.fn() } as never
  )
  const context = { universal: true, tickSize: 0.05, hostTimes: [t - 900, t], hostSeconds: 900 }
  layer.update(source, 'ema_cross_1m', 2, 'RELIANCE', '1m', t - 900, t, context)
  expect(series[0].setData.mock.lastCall?.[0]).toEqual([{ time: t, value: 102 }])
  layer.update(source, 'ema_cross_1m', 2, 'RELIANCE', '1m', t - 900, t, context)
  expect(compute).toHaveBeenCalledTimes(1)
  compute.mockRestore()
})
