import { expect, it, vi } from 'vitest'
import { CandleMarkers, CandleProbabilityLayer } from './CandleProbabilityLayer'
import type { CandleSetup, CandleStudy } from './candleProbabilityTypes'

const setup: CandleSetup = {
  time: 100,
  pattern: 'engulfing',
  name: 'Bullish engulfing',
  side: 'CALL',
  context: 'aligned',
  key: 'engulfing:CALL:aligned',
  entry: 100,
  stop: 99,
  target: 102,
  support: 98,
  resistance: 103,
  estimate: { samples: 58, targets: 48, probability: 49 / 60, lower: 0.71, upper: 0.91 },
  qualified: true,
  reason: 'Evidence qualifies',
}
function fixture() {
  const price = {
    attachPrimitive: vi.fn(),
    priceToCoordinate: (v: number) => v,
    createPriceLine: vi.fn((value) => value),
    removePriceLine: vi.fn(),
  }
  const layer = new CandleProbabilityLayer(price as never)
  const study: CandleStudy = {
    bars: [{ time: 100, open: 100, high: 102, low: 98, close: 101, volume: 0 }],
    setups: [setup, { ...setup, time: 150, qualified: false }],
    outcomes: [],
    signalOutcomes: [{ setup, time: 200, result: 'TARGET', price: 102, r: 2, ambiguous: false }],
    latest: setup,
    lastSetup: setup,
    active: setup,
    lastOutcome: null,
    support: 98,
    resistance: 103,
    closedTime: 100,
    seedUsed: false,
    model: {
      version: 1,
      symbol: 'NIFTY',
      exchange: 'NSE_INDEX',
      seconds: 60,
      indian: true,
      source: 'Loaded candles',
      trainedThrough: 0,
      counts: {},
    },
  }
  const context = {
    save: vi.fn(),
    beginPath: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    setLineDash: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    measureText: () => ({ width: 120 }),
    restore: vi.fn(),
  }
  const draw = () => {
    const primitive = price.attachPrimitive.mock.calls[0]?.[0]
    primitive?.attached({
      chart: { timeScale: () => ({ timeToCoordinate: (v: number) => v }) },
      series: price,
      requestUpdate: vi.fn(),
    })
    primitive
      ?.paneViews()[0]
      .renderer()
      .draw({
        useMediaCoordinateSpace: (fn: (value: unknown) => void) =>
          fn({ context, mediaSize: { width: 500, height: 500 } }),
      })
    return context.fillText.mock.calls.map(([text]) => text)
  }
  return { price, layer, study, context, draw }
}

it('draws qualified setup and exit markers with matching support, stop and 2R prices', () => {
  const { layer, study, draw, price } = fixture()
  layer.update(study, 100, 200, true)
  const labels = draw()
  expect(labels).toEqual(['Candle BUY CALL · 81.7%', 'Candle TARGET · 2R'])
  expect(price.createPriceLine.mock.calls.map(([value]) => [value.title, value.price])).toEqual([
    ['Candle support · prior 10', 98],
    ['Candle resistance · prior 10', 103],
    ['Candle entry', 100],
    ['Candle SL', 99],
    ['Candle 2R target', 102],
  ])
})

it('labels unqualified candidate prices only when previews are enabled', () => {
  const { layer, study, draw, price } = fixture()
  study.active = null
  study.latest = { ...setup, qualified: false }
  layer.update(study, 100, 200, false, false, undefined, false, true, true)
  expect(draw()).toContain('Candle BULL · 81.7%')
  expect(price.createPriceLine.mock.calls.map(([value]) => value.title)).toContain(
    'Candidate entry · unqualified'
  )
})

it('removes markers and levels when disabled and filters history to the visible range', () => {
  const { layer, study, draw, price, context } = fixture()
  layer.update(study, 150, 200, true)
  expect(draw()).toEqual(['Candle TARGET · 2R'])
  layer.update(null, 0, 0, true)
  context.fillText.mockClear()
  expect(draw()).toEqual([])
  expect(price.removePriceLine).toHaveBeenCalledTimes(5)
})

it('does not draw old setup entry prices once the setup is resolved', () => {
  const { layer, study, price } = fixture()
  layer.update({ ...study, active: null, latest: null }, 100, 200, true)
  expect(price.createPriceLine.mock.calls.map(([value]) => value.title)).toEqual([
    'Candle support · prior 10',
    'Candle resistance · prior 10',
  ])
})

it.each([
  'CE',
  'PE',
] as const)('uses BUY/AVOID for %s premiums without plotting short-premium risk levels', (side) => {
  const { layer, study, draw, price, context } = fixture()
  const printedColors: string[] = []
  context.fillText.mockImplementation(() => {
    printedColors.push((context as unknown as { fillStyle: string }).fillStyle)
  })
  const bearish = { ...setup, side: 'PUT' as const, stop: 101, target: 98 }
  layer.update(
    { ...study, setups: [bearish], latest: bearish, active: bearish, signalOutcomes: [] },
    100,
    200,
    false,
    false,
    side
  )
  expect(draw()).toEqual([`Candle AVOID ${side} · 81.7%`])
  expect(price.createPriceLine.mock.calls.map(([value]) => value.title)).toEqual([
    'Candle support · prior 10',
    'Candle resistance · prior 10',
  ])
})
it('prints the pattern name in green for BULL and red for BEAR without trade lines', () => {
  const { layer, study, draw, price, context } = fixture()
  const printedColors: string[] = []
  context.fillText.mockImplementation(() => {
    printedColors.push((context as unknown as { fillStyle: string }).fillStyle)
  })
  const bearish = {
    ...setup,
    time: 150,
    side: 'PUT' as const,
    name: 'Bearish engulfing',
    qualified: false,
  }
  layer.update({ ...study, setups: [setup, bearish] }, 100, 200, false, false, 'CE', true, false)
  expect(draw()).toEqual(['Engulfing · 81.7%', 'Engulfing · 81.7%'])
  expect(printedColors).toEqual(['#34d399', '#f87171'])
  expect(price.createPriceLine).not.toHaveBeenCalled()
})
it('does not display a confident percentage when matching pattern evidence is sparse', () => {
  const { layer, study, draw, context } = fixture()
  layer.update(
    {
      ...study,
      setups: [
        {
          ...setup,
          estimate: { samples: 3, targets: 2, probability: 0.6, lower: 0.2, upper: 0.9 },
        },
      ],
    },
    100,
    200,
    false,
    false,
    undefined,
    true,
    false
  )
  expect(draw()).toEqual(['Engulfing'])
  context.fillText.mockClear()
  layer.update(null, 100, 200, false, false, undefined, true, false)
  expect(draw()).toEqual([])
})

it('connects moved and edge-clamped labels to their own candle anchors', () => {
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
    setLineDash: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
  }
  const markers = new CandleMarkers()
  markers.attached({
    chart: { timeScale: () => ({ timeToCoordinate: (time: number) => time }) },
    series: { priceToCoordinate: (price: number) => price },
    requestUpdate: vi.fn(),
  } as never)
  markers.set([
    { time: 10, price: 100, text: 'Hammer', above: false, color: '#34d399', pointer: true },
    { time: 30, price: 100, text: 'Engulfing', above: false, color: '#34d399', pointer: true },
  ])
  markers
    .paneViews()[0]
    .renderer()
    .draw({
      useMediaCoordinateSpace: (fn: (value: unknown) => void) =>
        fn({ context, mediaSize: { width: 500, height: 500 } }),
    } as never)
  expect(context.lineTo.mock.calls.filter(([, y]) => y === 100)).toEqual([
    [10, 100],
    [10, 100],
    [30, 100],
    [30, 100],
  ])
  expect(context.arc.mock.calls).toEqual([
    [10, 100, 2.5, 0, Math.PI * 2],
    [30, 100, 2.5, 0, Math.PI * 2],
  ])
  const positions = context.fillText.mock.calls
  expect(positions[0][1]).toBeGreaterThan(10)
  expect(positions[1][2]).toBeGreaterThan(positions[0][2])
  expect(context.moveTo.mock.calls.filter((_, i) => i % 2 === 0)).toEqual(
    positions.map(([, x, y]) => [x, Number(y) - 8])
  )
})

it('hides unqualified reference guides by default while retaining support and resistance', () => {
  const { layer, study, price } = fixture()
  study.active = null
  study.latest = { ...setup, qualified: false }
  layer.update(study, 100, 200, false)
  expect(price.createPriceLine.mock.calls.map(([value]) => value.title)).toEqual([
    'Candle support · prior 10', 'Candle resistance · prior 10',
  ])
})
