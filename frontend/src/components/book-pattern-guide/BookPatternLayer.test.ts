import type { ISeriesApi } from 'lightweight-charts'
import { expect, it, vi } from 'vitest'
import {
  analyzeBookGuide,
  DEFAULT_BOOK_SETTINGS,
  type BookBar,
  type BookEvent,
  type BookGuideResult,
} from './engine'
import { bar, timed, trendBars, TEST_CONTEXT } from './fixtures'
import { BookPatternLayer, bookDrawingWorklist } from './BookPatternLayer'
const bars = Array.from({ length: 20 }, (_, i) => bar(100, 102, 99, 101, i))
const event = (i: number, extra: Partial<BookEvent> = {}): BookEvent => ({
  id: `e${i}`,
  patternId: 'hammer',
  name: 'Hammer',
  side: 'long',
  sourcePhotos: [44],
  kind: 'candle',
  mode: 'reversal',
  startIndex: i,
  endIndex: i,
  recognitionIndex: i,
  trigger: 102,
  stopAnchor: 99,
  stopMethod: 'Pattern low',
  targetMethod: 'r-fallback',
  scale: 1,
  contacts: 1,
  rank: 3,
  points: [{ time: bars[i].time, price: 99, index: i, role: 'low' }],
  segments: [],
  notes: [],
  formationStart: bars[i].time,
  formationEnd: bars[i].time,
  recognitionTime: bars[i].time,
  status: 'confirmed',
  nextCondition: 'Wait',
  confirmationTime: bars[i].time,
  confirmationIndex: i,
  ...extra,
})
const result = (events: BookEvent[]): BookGuideResult => ({
  ...analyzeBookGuide([], TEST_CONTEXT),
  events,
  visibleEvents: events,
  readiness: 'ready',
})
it('retains only latest ten actual chart candles including forming, with optional history', () => {
  const r = result([event(9), event(10), event(18)])
  expect(bookDrawingWorklist(r, bars, DEFAULT_BOOK_SETTINGS).map((e) => e.id)).toEqual([
    'e10',
    'e18',
  ])
  expect(
    bookDrawingWorklist(r, bars, { ...DEFAULT_BOOK_SETTINGS, fullHistory: true })
  ).toHaveLength(3)
})
it('hides neutral and pending by default and exposes them independently when selected', () => {
  const r = result([event(18, { side: 'neutral', rank: 4 })])
  r.pendingEvents = [event(19, { id: 'pending', status: 'pending', confirmationTime: undefined })]
  expect(bookDrawingWorklist(r, bars, DEFAULT_BOOK_SETTINGS)).toHaveLength(0)
  expect(
    bookDrawingWorklist(r, bars, { ...DEFAULT_BOOK_SETTINGS, showPending: true })
  ).toHaveLength(1)
  expect(
    bookDrawingWorklist(r, bars, { ...DEFAULT_BOOK_SETTINGS, showNeutral: true })
  ).toHaveLength(1)
})
it('drops whole oversized formations and reserves three plan lines within hard budgets', () => {
  const e = event(18)
  const segment = {
    from: e.points[0],
    to: { ...e.points[0], time: bars[19].time },
    role: 'boundary',
  }
  const r = result([event(17), { ...e, segments: Array(121).fill(segment) }])
  r.activePlan = {
    id: 'p',
    eventId: 'old',
    side: 'long',
    name: 'Frozen',
    createdAt: 1,
    createdIndex: 0,
    entry: 100,
    stop: 99,
    target: 103,
    rr: 3,
    targetMethod: 'r-fallback',
    stopMethod: 'low',
    status: 'active',
    notes: [],
  }
  expect(bookDrawingWorklist(r, bars, DEFAULT_BOOK_SETTINGS).map((e) => e.id)).toEqual(['e17'])
  const many = result(
    Array.from({ length: 200 }, (_, i) => event(18, { id: `many${i}`, kind: 'shape' }))
  )
  expect(
    bookDrawingWorklist(many, bars, { ...DEFAULT_BOOK_SETTINGS, maxDrawings: 999 })
  ).toHaveLength(40)
})
it('owns its primitive/lines only, keeps a stable single plan and clears on disable/destroy', () => {
  const foreign = { foreign: true }
  const owned: unknown[] = []
  const price = {
    attachPrimitive: vi.fn((p) => owned.push(p)),
    detachPrimitive: vi.fn(),
    createPriceLine: vi.fn((o) => ({ ...o })),
    removePriceLine: vi.fn(),
  } as unknown as ISeriesApi<'Candlestick'>
  const layer = new BookPatternLayer(price)
  const r = result([event(18)])
  r.activePlan = {
    id: 'p',
    eventId: 'e18',
    side: 'long',
    name: 'Frozen',
    createdAt: 1,
    createdIndex: 0,
    entry: 100,
    stop: 99,
    target: 103,
    rr: 3,
    targetMethod: 'r-fallback',
    stopMethod: 'low',
    status: 'active',
    notes: [],
  }
  layer.update(r, bars, DEFAULT_BOOK_SETTINGS)
  for (let i = 0; i < 100; i++)
    layer.update(
      { ...r, events: r.events.map((e) => ({ ...e })), provisional: { time: 2 + i, price: 101 } },
      bars.map((b) => ({ ...b })),
      DEFAULT_BOOK_SETTINGS
    )
  expect(price.createPriceLine).toHaveBeenCalledTimes(3)
  expect(vi.mocked(price.createPriceLine).mock.calls.map((c) => [c[0].title, c[0].color])).toEqual([
    ['Book Entry', '#ffffff'],
    ['Book SL', '#ef4444'],
    ['Book Target', '#22c55e'],
  ])
  layer.update(null, bars, DEFAULT_BOOK_SETTINGS)
  expect(price.removePriceLine).toHaveBeenCalledTimes(3)
  layer.destroy()
  layer.destroy()
  expect(price.detachPrimitive).toHaveBeenCalledTimes(1)
  expect(price.removePriceLine).not.toHaveBeenCalledWith(foreign)
  expect(owned).toHaveLength(1)
})
it('draws complete geometry and labels on actual time/price coordinates', () => {
  let primitive: any
  const requestUpdate = vi.fn()
  const price = {
    attachPrimitive: (p: unknown) => {
      primitive = p
    },
    detachPrimitive: vi.fn(),
    createPriceLine: vi.fn(),
    removePriceLine: vi.fn(),
  } as unknown as ISeriesApi<'Candlestick'>
  const layer = new BookPatternLayer(price)
  const e = event(18)
  e.segments = [
    {
      from: e.points[0],
      to: { time: bars[19].time, price: 102, index: 19, role: 'rim' },
      role: 'neckline',
    },
  ]
  layer.update(result([e]), bars, DEFAULT_BOOK_SETTINGS)
  const timeToCoordinate = vi.fn((t: number) => t - bars[0].time),
    priceToCoordinate = vi.fn((p: number) => p)
  primitive.attached({
    chart: { timeScale: () => ({ timeToCoordinate }) },
    series: { priceToCoordinate },
    requestUpdate,
  })
  const c: any = {
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    setLineDash: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    fillText: vi.fn(),
    fillRect: vi.fn(),
    measureText: () => ({ width: 80 }),
  }
  primitive
    .paneViews()[0]
    .renderer()
    .draw({
      useMediaCoordinateSpace: (cb: any) =>
        cb({ context: c, mediaSize: { width: 1500, height: 500 } }),
    })
  expect(timeToCoordinate).toHaveBeenCalledWith(bars[18].time)
  expect(priceToCoordinate).toHaveBeenCalledWith(99)
  expect(c.lineTo).toHaveBeenCalled()
  expect(c.fillText).toHaveBeenCalled()
})

it('keeps all earlier shape anchors when a recent confirmation enters the last-ten window', () => {
  const shape = event(18, {
    kind: 'shape',
    formationStart: bars[0].time,
    points: [
      { time: bars[0].time, price: 99, index: 0, role: 'left rim' },
      { time: bars[18].time, price: 101, index: 18, role: 'right rim' },
    ],
  })
  shape.segments = [{ from: shape.points[0], to: shape.points[1], role: 'neckline' }]
  const selected = bookDrawingWorklist(result([shape]), bars, DEFAULT_BOOK_SETTINGS)
  expect(selected[0].segments[0].from.time).toBe(bars[0].time)
  expect(selected[0].points).toHaveLength(2)
})
it('reserves plan labels and lines, and drops an event rather than drawing a partial label set', () => {
  const e = event(18, {
    kind: 'shape',
    points: Array.from({ length: 160 }, (_, i) => ({
      time: bars[18].time,
      price: 100,
      index: 18,
      role: `contact ${i}`,
    })),
  })
  expect(bookDrawingWorklist(result([e]), bars, DEFAULT_BOOK_SETTINGS)).toHaveLength(0)
  const segment = { from: event(18).points[0], to: event(19).points[0], role: 'boundary' }
  const r = result([event(18, { kind: 'shape', segments: Array(80).fill(segment) })])
  expect(bookDrawingWorklist(r, bars, DEFAULT_BOOK_SETTINGS)).toHaveLength(1)
  expect(bookDrawingWorklist(r, bars, { ...DEFAULT_BOOK_SETTINGS, maxPolylines: 79 })).toHaveLength(
    0
  )
})
it('outlines a confirmed single candle even when the detector has no segments', () => {
  let primitive: any
  const price = {
    attachPrimitive: (p: unknown) => {
      primitive = p
    },
    detachPrimitive: vi.fn(),
    createPriceLine: vi.fn(),
    removePriceLine: vi.fn(),
  } as unknown as ISeriesApi<'Candlestick'>
  new BookPatternLayer(price).update(result([event(18)]), bars, DEFAULT_BOOK_SETTINGS)
  primitive.attached({
    chart: { timeScale: () => ({ timeToCoordinate: () => 100 }) },
    series: { priceToCoordinate: (p: number) => p },
    requestUpdate: vi.fn(),
  })
  const c: any = {
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    setLineDash: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    fillText: vi.fn(),
    fillRect: vi.fn(),
    measureText: () => ({ width: 80 }),
  }
  primitive
    .paneViews()[0]
    .renderer()
    .draw({
      useMediaCoordinateSpace: (cb: any) =>
        cb({ context: c, mediaSize: { width: 500, height: 500 } }),
    })
  expect(c.stroke).toHaveBeenCalledTimes(5) // Four outline strokes and the main caption leader.
  expect(c.fillRect).toHaveBeenCalledWith(98.5, 97.5, 3, 3)
  expect(c.setLineDash).toHaveBeenCalledWith([2, 3])
  expect(c.moveTo).toHaveBeenCalledWith(100, 99)
  expect(c.fillText.mock.calls.every((call: unknown[]) => Number(call[2]) >= 121)).toBe(true)
  expect(c.moveTo).toHaveBeenCalledWith(96, 102)
  expect(c.lineTo).toHaveBeenCalledWith(104, 102)
})

it('counts dotted label leaders in the whole-formation line budget', () => {
  const r = result([event(18)])
  // Four candle strokes plus one caption and one source-point leader.
  expect(bookDrawingWorklist(r, bars, { ...DEFAULT_BOOK_SETTINGS, maxLines: 5 })).toHaveLength(0)
  expect(bookDrawingWorklist(r, bars, { ...DEFAULT_BOOK_SETTINGS, maxLines: 6 })).toHaveLength(1)
})

function renderCaption(sourceBars: BookBar[], patternId: string) {
  const analysis = analyzeBookGuide(sourceBars, TEST_CONTEXT)
  const detected = analysis.events.find((e) => e.patternId === patternId)
  expect(detected?.status).toBe('confirmed')
  const e = detected!
  expect(e.confirmationTime).toBeGreaterThan(e.formationEnd)
  let primitive: any
  const price = {
    attachPrimitive: (p: unknown) => {
      primitive = p
    },
    createPriceLine: vi.fn(),
    removePriceLine: vi.fn(),
  } as unknown as ISeriesApi<'Candlestick'>
  new BookPatternLayer(price).update(
    { ...analysis, events: [e], pendingEvents: [], trendLines: [] },
    sourceBars,
    DEFAULT_BOOK_SETTINGS
  )
  const x = (t: number) => 100 + (t - e.formationStart) / 3
  const y = (p: number) => 2500 - 20 * p
  primitive.attached({
    chart: { timeScale: () => ({ timeToCoordinate: x }) },
    series: { priceToCoordinate: y },
    requestUpdate: vi.fn(),
  })
  let start: number[] = [],
    end: number[] = [],
    dash: number[] = []
  const strokes: { start: number[]; end: number[]; dash: number[] }[] = []
  const c: any = {
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    setLineDash: (d: number[]) => {
      dash = d
    },
    moveTo: (...p: number[]) => {
      start = p
    },
    lineTo: (...p: number[]) => {
      end = p
    },
    stroke: () => strokes.push({ start, end, dash }),
    fillText: vi.fn(),
    fillRect: vi.fn(),
    measureText: () => ({ width: 150 }),
  }
  primitive
    .paneViews()[0]
    .renderer()
    .draw({
      useMediaCoordinateSpace: (cb: any) =>
        cb({ context: c, mediaSize: { width: 1000, height: 1000 } }),
    })
  expect(c.fillText.mock.calls[0][0]).toBe(`${e.name} · confirmed`)
  return {
    e,
    x,
    y,
    leader: strokes.find((s) => s.dash.join() === '2,3')!,
    caption: c.fillRect.mock.calls[0] as number[],
  }
}

it('links a confirmed inverted-hammer caption to its source low outside its full candle', () => {
  const sourceBars = timed([
    ...trendBars('short'),
    bar(100, 110, 99.9, 102),
    bar(102.5, 105, 102.3, 104),
  ])
  const { e, x, y, leader, caption } = renderCaption(sourceBars, 'inverted-hammer')
  expect(e.formationStart).toBe(1700004200)
  expect(e.confirmationTime).toBe(1700004260)
  expect(leader.start).toEqual([x(e.formationEnd), y(99.9)])
  expect(caption[1]).toBeGreaterThan(y(99.9))
})

it('uses the last formation high as caption source and the entire multi-candle envelope as display edge', () => {
  const sourceBars = timed([
    ...trendBars('long'),
    bar(100, 112, 95, 106),
    bar(106, 110, 98, 99),
    bar(98.9, 99, 96, 97),
  ])
  const { e, x, y, leader, caption } = renderCaption(sourceBars, 'bear-engulfing')
  expect(e.formationEnd).toBe(e.formationStart + 60)
  expect(leader.start).toEqual([x(e.formationEnd), y(110)])
  // The first candle extends above the source candle; confirmation is a third candle.
  expect(caption[1] + caption[3]).toBeLessThan(y(112))
})

it.each([
  'long',
  'short',
] as const)('packs dense %s captions at the viewport edge without hiding names or source points', (side) => {
  let primitive: any
  const price = {
    attachPrimitive: (p: unknown) => {
      primitive = p
    },
    createPriceLine: vi.fn(),
    removePriceLine: vi.fn(),
  } as unknown as ISeriesApi<'Candlestick'>
  const events = Array.from({ length: 12 }, (_, i) =>
    event(18, {
      id: `dense-${i}`,
      name: i % 2 ? `Pattern ${i}` : `Wide formation pattern ${i}`,
      side,
      points: [
        { time: bars[18].time, price: 102, index: 18, role: 'high' },
        { time: bars[18].time, price: 99, index: 18, role: 'low' },
        { time: bars[19].time, price: 101, index: 19, role: 'confirmation' },
      ],
    })
  )
  const r = result(events)
  r.trendLines = [
    { from: events[0].points[0], to: events[0].points[1], role: 'Support trend' },
    { from: events[0].points[1], to: events[0].points[0], role: 'Resistance trend' },
  ]
  new BookPatternLayer(price).update(r, bars, DEFAULT_BOOK_SETTINGS)
  const y = (p: number) => (side === 'long' ? 350 : 140) + (100 - p) * 5
  primitive.attached({
    chart: { timeScale: () => ({ timeToCoordinate: () => (side === 'long' ? 795 : 5) }) },
    series: { priceToCoordinate: y },
    requestUpdate: vi.fn(),
  })
  const c: any = {
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    setLineDash: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    fillText: vi.fn(),
    fillRect: vi.fn(),
    measureText: (text: string) => ({ width: text.length * 6 }),
  }
  primitive
    .paneViews()[0]
    .renderer()
    .draw({
      useMediaCoordinateSpace: (cb: any) =>
        cb({ context: c, mediaSize: { width: 800, height: 500 } }),
    })
  const texts = c.fillText.mock.calls.map((call: unknown[]) => call[0])
  for (const e of events) expect(texts).toContain(`${e.name} · confirmed`)
  expect(texts).toContain('Support trend · context')
  expect(texts).toContain('Resistance trend · context')
  const rectangles = c.fillRect.mock.calls.filter((rect: number[]) => rect[3] >= 14)
  for (const [i, a] of rectangles.entries()) {
    expect(a[0]).toBeGreaterThanOrEqual(0)
    expect(a[1]).toBeGreaterThanOrEqual(0)
    expect(a[0] + a[2]).toBeLessThanOrEqual(800)
    expect(a[1] + a[3]).toBeLessThanOrEqual(500)
    for (const b of rectangles.slice(i + 1))
      expect(
        a[0] < b[0] + b[2] && a[0] + a[2] > b[0] && a[1] < b[1] + b[3] && a[1] + a[3] > b[1]
      ).toBe(false)
  }
  expect(texts).not.toContain('high')
  expect(texts).not.toContain('low')
  expect(texts).not.toContain('confirmation')
  expect(rectangles).toHaveLength(14)
  // Main names get first choice of lanes, all on their correct formation side.
  for (const rect of rectangles.slice(0, 12))
    if (side === 'long') expect(rect[1]).toBeGreaterThan(y(99))
    else expect(rect[1] + rect[3]).toBeLessThan(y(102))
  const markers = c.fillRect.mock.calls.filter((rect: number[]) => rect[2] === 3 && rect[3] === 3)
  expect(markers).toHaveLength(36)
  expect(c.moveTo).toHaveBeenCalledWith(side === 'long' ? 795 : 5, y(side === 'long' ? 99 : 102))
  expect(c.setLineDash).toHaveBeenCalledWith([2, 3])
  expect(
    c.setLineDash.mock.calls.filter((call: number[][]) => call[0].join() === '2,3')
  ).toHaveLength(12)
  for (const e of events)
    for (const p of e.points)
      expect(markers).toContainEqual([(side === 'long' ? 795 : 5) - 1.5, y(p.price) - 1.5, 3, 3])
  expect(Math.min(...c.fillText.mock.invocationCallOrder)).toBeGreaterThan(
    Math.max(...c.stroke.mock.invocationCallOrder)
  )
  const firstLayout = c.fillRect.mock.calls.map((rect: number[]) => [...rect])
  c.fillRect.mockClear()
  primitive
    .paneViews()[0]
    .renderer()
    .draw({
      useMediaCoordinateSpace: (cb: any) =>
        cb({ context: c, mediaSize: { width: 800, height: 500 } }),
    })
  expect(c.fillRect.mock.calls).toEqual(firstLayout)
})

it('keeps all main names forty pixels beyond the mixed selected candle envelope with exact individual leaders', () => {
  const sourceBars = bars.map((b) => ({ ...b }))
  const rows = [
    { side: 'long' as const, high: 110, low: 90 },
    { side: 'long' as const, high: 108, low: 95 },
    { side: 'short' as const, high: 120, low: 92 },
    { side: 'short' as const, high: 105, low: 96 },
  ]
  const events = rows.map((row, n) => {
    const i = n + 14
    sourceBars[i] = { ...sourceBars[i], high: row.high, low: row.low }
    return event(i, {
      id: `band-${i}`,
      name: `Mixed formation ${i}`,
      side: row.side,
      confirmationIndex: 19,
      confirmationTime: bars[19].time,
      points: [
        { time: bars[i].time, index: i, price: row.high, role: 'high' },
        { time: bars[i].time, index: i, price: row.low, role: 'low' },
        { time: bars[19].time, index: 19, price: 130, role: 'confirmation' },
      ],
    })
  })
  for (const side of ['long', 'short'] as const)
    events.push(
      event(18, {
        id: `shape-${side}`,
        name: `Mixed shape ${side}`,
        kind: 'shape',
        side,
        confirmationIndex: 19,
        confirmationTime: bars[19].time,
        points: [
          { time: bars[18].time, index: 18, price: side === 'long' ? 98 : 110, role: 'right rim' },
        ],
      })
    )
  const r = result(events)
  expect(bookDrawingWorklist(r, sourceBars, DEFAULT_BOOK_SETTINGS)).toHaveLength(6)
  expect(
    bookDrawingWorklist(r, sourceBars, { ...DEFAULT_BOOK_SETTINGS, maxDrawings: 2 })
  ).toHaveLength(2)
  let primitive: any
  const price = {
    attachPrimitive: (p: unknown) => {
      primitive = p
    },
    createPriceLine: vi.fn(),
    removePriceLine: vi.fn(),
  } as unknown as ISeriesApi<'Candlestick'>
  new BookPatternLayer(price).update(r, sourceBars, DEFAULT_BOOK_SETTINGS)
  const x = (t: number) => 300 + (t - bars[14].time) / 6
  const y = (p: number) => 700 - p * 5
  primitive.attached({
    chart: { timeScale: () => ({ timeToCoordinate: x }) },
    series: { priceToCoordinate: y },
    requestUpdate: vi.fn(),
  })
  let start: number[] = [],
    dash: number[] = []
  const leaders: number[][] = []
  const c: any = {
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    setLineDash: (value: number[]) => {
      dash = value
    },
    moveTo: (...value: number[]) => {
      start = value
    },
    lineTo: vi.fn(),
    stroke: () => {
      if (dash.join() === '2,3') leaders.push(start)
    },
    fillText: vi.fn(),
    fillRect: vi.fn(),
    measureText: (text: string) => ({ width: text.length * 6 }),
  }
  primitive
    .paneViews()[0]
    .renderer()
    .draw({
      useMediaCoordinateSpace: (cb: any) =>
        cb({ context: c, mediaSize: { width: 1000, height: 500 } }),
    })
  const names = c.fillText.mock.calls.map((call: unknown[]) => call[0])
  const rectangles = c.fillRect.mock.calls.filter((rect: number[]) => rect[3] >= 14)
  // The later confirmation at 130 must not expand the selected source envelope.
  const firstShort = rectangles[names.indexOf('Mixed formation 16 · confirmed')]
  expect(firstShort[1] + firstShort[3]).toBe(y(120) - 40)
  expect(rectangles[names.indexOf('Mixed formation 14 · confirmed')][1]).toBe(y(90) + 40)

  for (const e of events) {
    const at = names.indexOf(`${e.name} · confirmed`)
    expect(at).toBeGreaterThanOrEqual(0)
    const rectangle = rectangles[at]
    if (e.side === 'long') expect(rectangle[1]).toBeGreaterThanOrEqual(y(90) + 40)
    else expect(rectangle[1] + rectangle[3]).toBeLessThanOrEqual(y(120) - 40)
    const point = e.kind === 'candle' ? e.points[e.side === 'long' ? 1 : 0] : e.points[0]
    expect(leaders[at]).toEqual([x(point.time), y(point.price)])
  }
  for (const [i, a] of rectangles.entries())
    for (const b of rectangles.slice(i + 1))
      expect(
        a[0] < b[0] + b[2] && a[0] + a[2] > b[0] && a[1] < b[1] + b[3] && a[1] + a[3] > b[1]
      ).toBe(false)
  expect(
    c.fillRect.mock.calls.filter((rect: number[]) => rect[2] === 3 && rect[3] === 3)
  ).toHaveLength(14)
})
