import { expect, it, vi } from 'vitest'
import { NineIndicatorLayer } from './NineIndicatorLayer'
import type { NineResult } from './nineIndicators'

it('draws only selected independent studies with explicit BUY CALL / BUY PUT text and clears on disable', () => {
  const price = { attachPrimitive: vi.fn(), priceToCoordinate: (v: number) => v }
  const chart = { timeScale: () => ({ timeToCoordinate: (v: number) => v }) }
  const layer = new NineIndicatorLayer(price as never)
  const result: NineResult = {
    states: [],
    lastTime: 200,
    bias: 'CALL',
    events: [
      { key: 'rsi', time: 100, side: 'CALL', price: 90 },
      { key: 'macd', time: 100, side: 'PUT', price: 110 },
      { key: 'bb', time: 200, side: 'CALL', price: 95 },
    ],
  }
  layer.update(result, ['nine-rsi', 'nine-macd'], 100, 200, null, [])
  const primitive = price.attachPrimitive.mock.calls[0][0]
  primitive.attached({ chart, series: price, requestUpdate: vi.fn() })
  const context = {
    save: vi.fn(),
    beginPath: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    measureText: () => ({ width: 100 }),
    restore: vi.fn(),
  }
  const target = {
    useMediaCoordinateSpace: (draw: (scope: unknown) => void) =>
      draw({ context, mediaSize: { width: 500, height: 500 } }),
  }
  primitive.paneViews()[0].renderer().draw(target)
  expect(context.fillText.mock.calls.map((c) => c[0])).toEqual(['RSI BUY CALL', 'MACD BUY PUT'])
  layer.update(null, [], 100, 200, null, [])
  context.fillText.mockClear()
  primitive.paneViews()[0].renderer().draw(target)
  expect(context.fillText).not.toHaveBeenCalled()
})
