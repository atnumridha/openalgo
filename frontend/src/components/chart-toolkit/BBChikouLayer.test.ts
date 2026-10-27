import { expect, it, vi } from 'vitest'
import { BBChikouLayer } from './BBChikouLayer'
import type { BBChikouResult } from './bbChikou'

it('creates series only when enabled, clips shifted history, and clears all drawings on disable', () => {
  const series: Array<{
    setData: ReturnType<typeof vi.fn>
    applyOptions: ReturnType<typeof vi.fn>
  }> = []
  const chart = {
    addSeries: vi.fn(() => {
      const line = { setData: vi.fn(), applyOptions: vi.fn() }
      series.push(line)
      return line
    }),
  }
  const price = { attachPrimitive: vi.fn() }
  const layer = new BBChikouLayer(chart as never, price as never)
  layer.update(null, 100, 200)
  expect(chart.addSeries).not.toHaveBeenCalled()
  const result: BBChikouResult = {
    points: [
      { time: 100, upper: 102, middle: 100, lower: 98 },
      { time: 200, upper: 103, middle: 101, lower: 99 },
    ],
    chikou: [
      { time: 40, value: 99 },
      { time: 100, value: 105 },
    ],
    signals: [],
    latest: null,
  }
  layer.update(result, 100, 200)
  expect(chart.addSeries).toHaveBeenCalledTimes(4)
  expect(price.attachPrimitive).toHaveBeenCalledOnce()
  expect(series[1].setData).toHaveBeenLastCalledWith([
    { time: 100, value: 100 },
    { time: 200, value: 101 },
  ])
  expect(series[3].setData).toHaveBeenLastCalledWith([{ time: 100, value: 105 }])
  layer.update(null, 100, 200)
  for (const line of series) {
    expect(line.setData).toHaveBeenLastCalledWith([])
    expect(line.applyOptions).toHaveBeenLastCalledWith({ visible: false })
  }
  layer.update(result, 100, 200)
  expect(chart.addSeries).toHaveBeenCalledTimes(4)
})

it('keeps earlier historical signals available when more than forty are loaded', () => {
  const chart = {
    addSeries: () => ({ setData: vi.fn(), applyOptions: vi.fn() }),
    timeScale: () => ({ timeToCoordinate: (time: number) => time }),
  }
  const price = { attachPrimitive: vi.fn(), priceToCoordinate: () => 100 }
  const layer = new BBChikouLayer(chart as never, price as never)
  layer.update({ points: [], chikou: [], latest: null,
    signals: Array.from({ length: 45 }, (_, i) => ({ time: i + 1, side: 'BULL', entry: 100, stop: 99, target: 101, price: 100 })),
  }, 1, 45)
  const primitive = price.attachPrimitive.mock.calls[0][0]
  primitive.attached({ chart, series: price, requestUpdate: vi.fn() })
  const context = { save: vi.fn(), beginPath: vi.fn(), rect: vi.fn(), clip: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), closePath: vi.fn(), fill: vi.fn(), fillRect: vi.fn(), fillText: vi.fn(), restore: vi.fn() }
  primitive.paneViews()[0].renderer().draw({
    useMediaCoordinateSpace: (draw: (scope: unknown) => void) => draw({ context, mediaSize: { width: 500, height: 500 } }),
  })
  expect(context.fillText).toHaveBeenCalledTimes(45)
  expect(context.fillText).toHaveBeenCalledWith('BULL', 1, 116)
})
