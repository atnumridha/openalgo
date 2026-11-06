import { resolveIndicatorChart } from './indicatorChartContext'
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
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
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

it('maps a bearish index event to a green BUY PE at the option candle, skipping missing option bars', () => {
  const price = { attachPrimitive: vi.fn(), priceToCoordinate: vi.fn((v: number) => v) }
  const layer = new NineIndicatorLayer(price as never)
  const result: NineResult = {
    states: [],
    lastTime: 200,
    bias: 'PUT',
    events: [
      { key: 'ma', time: 100, side: 'PUT', price: 23000 },
      { key: 'ma', time: 200, side: 'PUT', price: 23020 },
    ],
  }
  const display = {
    chart: resolveIndicatorChart('NIFTY03NOV2623000PE', 'NFO'),
    source: 'underlying' as const,
  }
  layer.update(
    result,
    ['nine-ma'],
    100,
    200,
    null,
    [{ time: 100, open: 50, high: 55, low: 45, close: 52, volume: 100 }],
    display
  )
  const primitive = price.attachPrimitive.mock.calls[0][0]
  primitive.attached({
    chart: { timeScale: () => ({ timeToCoordinate: (v: number) => v }) },
    series: price,
    requestUpdate: vi.fn(),
  })
  const colors: string[] = []
  const context = {
    save: vi.fn(),
    beginPath: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    fillStyle: '',
    fillRect: () => colors.push(context.fillStyle),
    fillText: vi.fn(),
    measureText: () => ({ width: 100 }),
    restore: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
  }
  const target = {
    useMediaCoordinateSpace: (draw: (scope: unknown) => void) =>
      draw({ context, mediaSize: { width: 500, height: 500 } }),
  }
  primitive.paneViews()[0].renderer().draw(target)
  expect(context.fillText.mock.calls.map((c) => c[0])).toEqual(['MA BUY PE'])
  expect(price.priceToCoordinate).toHaveBeenCalledWith(45)
  expect(colors).toEqual(['#075a43'])
  layer.update(
    result,
    ['nine-ma'],
    100,
    200,
    null,
    [{ time: 100, open: 50, high: 55, low: 45, close: 52, volume: 100 }],
    { ...display, source: 'premium' }
  )
  context.fillText.mockClear()
  primitive.paneViews()[0].renderer().draw(target)
  expect(context.fillText.mock.calls.map((c) => c[0])).toEqual(['MA AVOID PE'])
})

it('keeps nearby opposing labels separated and inside the plot',()=>{
 const price={attachPrimitive:vi.fn(),priceToCoordinate:(v:number)=>v}
 const layer=new NineIndicatorLayer(price as never)
 layer.update({states:[],lastTime:110,bias:'CALL',events:[
  {key:'rsi',time:100,side:'CALL',price:100},
  {key:'macd',time:110,side:'PUT',price:136},
 ]},['nine-rsi','nine-macd'],100,110,null,[])
 const primitive=price.attachPrimitive.mock.calls[0][0]
 primitive.attached({chart:{timeScale:()=>({timeToCoordinate:(v:number)=>v})},series:price,requestUpdate:vi.fn()})
 const c={save:vi.fn(),beginPath:vi.fn(),rect:vi.fn(),clip:vi.fn(),fillRect:vi.fn(),fillText:vi.fn(),measureText:()=>({width:100}),restore:vi.fn(),moveTo:vi.fn(),lineTo:vi.fn(),stroke:vi.fn()}
 primitive.paneViews()[0].renderer().draw({useMediaCoordinateSpace:(fn:(scope:unknown)=>void)=>fn({context:c,mediaSize:{width:500,height:500}})})
 const [a,b]=c.fillRect.mock.calls
 expect(a[1]+a[3]<=b[1]||b[1]+b[3]<=a[1]||a[0]+a[2]<=b[0]||b[0]+b[2]<=a[0]).toBe(true)
 expect(c.stroke).toHaveBeenCalled()
})
