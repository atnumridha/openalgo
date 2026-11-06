import { expect, it, vi } from 'vitest'
import { VideoStrategyLayer, videoGuideMarkers } from './VideoStrategyLayer'
import { videoStrategyGuide } from './videoStrategyGuide.js'
import fixtures from '/Users/nmandal/Documents/AlgoTrading/openalgo/scripts/tradingview/validation/video-strategy-fixtures.json'
const c = fixtures.cases[0],
  bars = c.bars.map((b, i) => ({ ...b, time: fixtures.start + i * 60, volume: 1 }))
const result = videoStrategyGuide(bars, {
  seconds: 60,
  asOf: fixtures.start + bars.length * 60,
  tickSize: 0.5,
})
it('shows only recent confirmation markers and can restore historical ones', () => {
  const recent = videoGuideMarkers(result, bars, {
    first: bars.at(-1)!.time,
    last: bars.at(-1)!.time,
    showPending: false,
    showAll: false,
  })
  expect(recent.every((m) => m.time === bars.at(-1)!.time)).toBe(true)
  const all = videoGuideMarkers(result, bars, {
    first: bars[0].time,
    last: bars.at(-1)!.time,
    showPending: false,
    showAll: true,
  })
  expect(all.length).toBeGreaterThan(recent.length)
})
it('owns one selected priced plan and clears it on unavailable data or incomplete source', () => {
  const price = {
    attachPrimitive: vi.fn(),
    detachPrimitive: vi.fn(),
    createPriceLine: vi.fn((v) => v),
    removePriceLine: vi.fn(),
  }
  const layer = new VideoStrategyLayer(price as never)
  const context = {
    first: bars[0].time,
    last: bars.at(-1)!.time,
    showPending: false,
    showAll: false,
  }
  layer.update(result, 'fvg', bars, context)
  expect(price.createPriceLine.mock.calls.map(([v]) => v.title)).toEqual([
    'Guide watch',
    'Guide close ref',
    'Guide SL',
    'Guide target',
  ])
  layer.update(result, 'krm', bars, context)
  expect(price.removePriceLine).toHaveBeenCalledTimes(4)
  layer.destroy()
  expect(price.detachPrimitive).toHaveBeenCalled()
})
it('starts a later attached sweep zone when its geometry became known', () => {
  const c = fixtures.cases.find((c) => c.name === 'sweep')!,
    bars = c.bars.map((b, i) => ({ ...b, time: fixtures.start + i * 60, volume: 1 }))
  const result = videoStrategyGuide(bars, {
    seconds: 60,
    asOf: fixtures.start + bars.length * 60,
    tickSize: 0.5,
  })
  const e = result.readings.find((r) => r.id === 'sweep')!.event!,
    primitive: any[] = []
  const price = {
    attachPrimitive: (p: any) => primitive.push(p),
    detachPrimitive: vi.fn(),
    createPriceLine: vi.fn((v) => v),
    removePriceLine: vi.fn(),
  }
  const layer = new VideoStrategyLayer(price as never),
    timeToCoordinate = vi.fn((t) => t)
  primitive[1].attached({
    chart: { timeScale: () => ({ timeToCoordinate }) },
    series: { priceToCoordinate: (p: number) => p },
    requestUpdate: vi.fn(),
  })
  layer.update(result, 'sweep', bars, {
    first: bars[0].time,
    last: bars.at(-1)!.time,
    showPending: false,
    showAll: false,
  })
  const noop = () => {},
    context = {
      save: noop,
      restore: noop,
      beginPath: noop,
      rect: noop,
      clip: noop,
      setLineDash: noop,
      fillRect: noop,
      strokeRect: noop,
    }
  primitive[1]
    .paneViews()[0]
    .renderer()
    .draw({
      useMediaCoordinateSpace: (cb: any) =>
        cb({ context, mediaSize: { width: 1e12, height: 500 } }),
    })
  expect(e.confirmedBar).not.toBe(e.barTime)
  expect(timeToCoordinate.mock.calls[0][0]).toBe(e.confirmedBar)
  layer.destroy()
})
