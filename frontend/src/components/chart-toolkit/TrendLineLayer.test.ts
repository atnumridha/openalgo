import { describe, expect, it } from 'vitest'
import type {
  ISeriesApi,
  ISeriesPrimitive,
  Time,
  SeriesAttachedParameter,
  IPrimitivePaneRenderer,
} from 'lightweight-charts'
import type { Bar } from './model'
import { TrendLineLayer, trendLineSegments, cryptoFormationSegments } from './TrendLineLayer'

const fixture = (): Bar[] =>
  [12, 11, 10, 11, 12, 13, 12, 11, 12, 13, 14, 13, 12, 13, 14].map((close, i) => ({
    time: 1_700_000_000 + i * 60,
    open: close,
    high: close + 1,
    low: close - 1,
    close,
    volume: 100,
  }))

describe('visible trend lines', () => {
  it('draws support between confirmed lows and projects to the latest completed candle', () => {
    const input = fixture()
    const support = trendLineSegments(input, 60).find((line) => line.title === 'Trend support')!
    expect(support.color).toBe('#26a69a')
    expect(support.points).toEqual([
      { time: 1_700_000_420, price: 10 },
      { time: 1_700_000_720, price: 11 },
      { time: 1_700_000_840, price: 11.4 },
    ])
    expect(trendLineSegments(input, 60).some((line) => line.title === 'Trend resistance')).toBe(
      true
    )
  })
  it('preserves pivots across scheduled NSE closures and projects in trading-bar spacing', () => {
    const session = { start: 555, end: 930, offset: 19800 }
    const start = Date.UTC(2026, 9, 23, 3, 45) / 1000
    const input = fixture().map((b, i) => ({
      ...b,
      time: start + (Math.floor(i / 7) ? Math.floor(i / 7) + 2 : 0) * 86400 + (i % 7) * 3600,
    }))
    const support = trendLineSegments(input, 3600, undefined, session).find(
      (line) => line.title === 'Trend support'
    )!
    expect(support.points.at(-1)).toEqual({ time: input[14].time, price: 11.4 })
    expect(
      trendLineSegments(
        input.filter((_, i) => i !== 10),
        3600,
        undefined,
        session
      )
    ).toEqual([])
  })
  it('draws falling resistance and does not invent unconfirmed pivots', () => {
    const input = fixture().map((b) => ({
      ...b,
      open: 30 - b.open,
      close: 30 - b.close,
      high: 30 - b.low,
      low: 30 - b.high,
    }))
    const resistance = trendLineSegments(input, 60).find(
      (line) => line.title === 'Trend resistance'
    )!
    expect(resistance.color).toBe('#ef5350')
    expect(resistance.points.at(-1)).toEqual({ time: 1_700_000_840, price: 18.6 })
    expect(trendLineSegments(fixture().slice(0, 9), 60)).toEqual([])
    expect(
      trendLineSegments(fixture().slice(0, 10), 60).some((line) => line.title === 'Trend support')
    ).toBe(true)
  })
  it('removes a support line when a completed close crosses it', () => {
    const input = fixture()
    input[14] = { ...input[14], open: 8, high: 9, low: 7, close: 8 }
    expect(trendLineSegments(input, 60).some((line) => line.title === 'Trend support')).toBe(false)
  })
  it('resets pivots after missing, unordered, or invalid candles', () => {
    const input = fixture()
    expect(
      trendLineSegments(
        input.map((b, i) => ({ ...b, time: b.time + (i >= 10 ? 60 : 0) })),
        60
      )
    ).toEqual([])
    expect(trendLineSegments([...input, input[0]], 60)).toEqual([])
    expect(trendLineSegments([...input, { ...input.at(-1)!, close: NaN }], 60)).toEqual([])
    expect(trendLineSegments(input, 0)).toEqual([])
  })
  it('shows only supplied boundary points inside the completed contiguous prefix', () => {
    const input = fixture()
    const boundary = [
      { time: input[3].time, price: 20 },
      { time: input[10].time, price: 22 },
      { time: input[14].time + 60, price: 24 },
    ]
    const result = trendLineSegments(input, 60, boundary).find(
      (line) => line.title === 'Breakout boundary'
    )!
    expect(result).toEqual({
      color: '#3988ff',
      title: 'Breakout boundary',
      points: boundary.slice(0, 2),
    })
    expect(boundary).toHaveLength(3)
  })
  it('paints coordinate-based lines, clears them on empty update, and detaches on destroy', () => {
    let primitive: ISeriesPrimitive<Time> | undefined
    let detachCount = 0
    const series = {
      attachPrimitive: (value: ISeriesPrimitive<Time>) => {
        primitive = value
      },
      detachPrimitive: () => {
        detachCount++
      },
      createPriceLine: (options: unknown) => options,
      removePriceLine: () => {},
    } as unknown as ISeriesApi<'Candlestick'>
    const layer = new TrendLineLayer(series)
    layer.update(fixture(), 60)
    primitive!.attached!({
      chart: {
        timeScale: () => ({ timeToCoordinate: (time: number) => (time - 1_700_000_000) / 60 }),
      },
      series: { priceToCoordinate: (price: number) => 100 - price },
      requestUpdate: () => {},
    } as unknown as SeriesAttachedParameter<Time>)
    const paths: number[][] = []
    const context = {
      save() {},
      restore() {},
      beginPath() {},
      rect() {},
      clip() {},
      setLineDash() {},
      moveTo(x: number, y: number) {
        paths.push([x, y])
      },
      lineTo(x: number, y: number) {
        paths.push([x, y])
      },
      stroke() {},
      fillText() {},
    }
    const target = {
      useMediaCoordinateSpace: (draw: (scope: unknown) => void) =>
        draw({ context, mediaSize: { width: 500, height: 300 } }),
    } as unknown as Parameters<IPrimitivePaneRenderer['draw']>[0]
    primitive!.paneViews!()[0].renderer()!.draw(target)
    expect(paths).toEqual([
      [7, 90],
      [12, 89],
      [14, 88.6],
      [5, 86],
      [10, 85],
      [14, 84.2],
    ])
    paths.length = 0
    const boundary = [
      { time: fixture()[3].time, price: 20 },
      { time: fixture()[10].time, price: 20 },
    ]
    layer.update(fixture(), 60, boundary, undefined, false, [
      { points: boundary, color: '#34d399', title: 'Triangle', kind: 'pattern' },
    ])
    primitive!.paneViews!()[0].renderer()!.draw(target)
    expect(paths.filter(([x, y]) => x === 10 && y === 80)).toHaveLength(1)
    paths.length = 0
    layer.update([], 60)
    primitive!.paneViews!()[0].renderer()!.draw(target)
    expect(paths).toEqual([])
    layer.destroy()
    layer.destroy()
    expect(detachCount).toBe(1)
  })
})

describe('crypto formation outlines', () => {
  it('draws one latest matching formation and keeps historical and future events out', async () => {
    const { cryptoFormationSegments } = await import('./TrendLineLayer')
    const bars = fixture()
    const event = {
      time: bars[12].time,
      side: 'CALL' as const,
      name: 'Bull Flag',
      pattern: 'bull-flag',
      confirmed: true,
      extreme: 9,
      structure: [
        [
          { time: bars[3].time, price: 12 },
          { time: bars[12].time, price: 11 },
        ],
      ],
    }
    const lines = cryptoFormationSegments(
      [event, { ...event, time: bars[14].time + 60 }],
      bars,
      bars[0].time,
      bars[14].time
    )
    expect(lines).toHaveLength(1)
    expect(lines[0]).toMatchObject({
      title: 'Bull Flag',
      color: '#34d399',
      kind: 'pattern',
      points: event.structure[0],
    })
    expect(cryptoFormationSegments([event], bars, bars[13].time, bars[14].time)).toEqual([])
    expect(
      cryptoFormationSegments([{ ...event, confirmed: false }], bars, bars[0].time, bars[14].time)
    ).toEqual([])
  })
})

describe('clearly labelled support and resistance', () => {
  it('finds the nearest unbroken confirmed swing levels around the completed close', async () => {
    const { supportResistanceLevels } = await import('./TrendLineLayer')
    expect(supportResistanceLevels(fixture(), 60)).toEqual({ support: 11, resistance: 15 })
    const input = fixture()
    input.push({
      time: input.at(-1)!.time + 60,
      open: 14,
      high: 17,
      low: 14,
      close: 16,
      volume: 100,
    })
    expect(supportResistanceLevels(input, 60).resistance).toBeNull()
    expect(supportResistanceLevels(fixture().slice(0, 4), 60)).toEqual({
      support: null,
      resistance: null,
    })
  })
  it('adds full-width named price lines, reuses them and clears only its own levels', () => {
    const created: Record<string, unknown>[] = [],
      removed: unknown[] = []
    const series = {
      attachPrimitive() {},
      detachPrimitive() {},
      createPriceLine: (options: Record<string, unknown>) => {
        created.push(options)
        return options
      },
      removePriceLine: (line: unknown) => removed.push(line),
    } as unknown as ISeriesApi<'Candlestick'>
    const layer = new TrendLineLayer(series)
    layer.update(fixture(), 60)
    expect(created).toEqual([
      expect.objectContaining({
        title: 'SUPPORT',
        price: 11,
        color: '#22c55e',
        axisLabelVisible: true,
        lineVisible: true,
      }),
      expect.objectContaining({
        title: 'RESISTANCE',
        price: 15,
        color: '#ef4444',
        axisLabelVisible: true,
        lineVisible: true,
      }),
    ])
    layer.update(fixture(), 60)
    expect(created).toHaveLength(2)
    layer.update([], 60)
    expect(removed).toHaveLength(2)
    layer.destroy()
    expect(removed).toHaveLength(2)
  })
})

it('removes broken swing supports and resets support/resistance across missing candles', async () => {
  const { supportResistanceLevels } = await import('./TrendLineLayer')
  const input = fixture()
  input.push({ time: input.at(-1)!.time + 60, open: 14, high: 14, low: 8, close: 9, volume: 100 })
  expect(supportResistanceLevels(input, 60).support).toBeNull()
  const gap = fixture().map((bar, i) => ({ ...bar, time: bar.time + (i >= 12 ? 600 : 0) }))
  expect(supportResistanceLevels(gap, 60)).toEqual({ support: null, resistance: null })
})

it('combines equal swing/hourly prices while keeping every label and clearing only owned lines', () => {
  const created: Record<string, unknown>[] = []
  const series = {
    attachPrimitive() {},
    detachPrimitive() {},
    removePriceLine() {},
    createPriceLine: (options: Record<string, unknown>) => {
      created.push(options)
      return options
    },
  } as unknown as ISeriesApi<'Candlestick'>
  const layer = new TrendLineLayer(series)
  layer.update(
    fixture(),
    60,
    undefined,
    undefined,
    false,
    [],
    [
      { title: '1H LOW', price: 11, color: '#f59e0b', start: 1, end: 2 },
      { title: '4H LOW', price: 11, color: '#a78bfa', start: 1, end: 2 },
    ]
  )
  expect(created.filter((line) => line.price === 11)).toEqual([
    expect.objectContaining({ title: '1H LOW / 4H LOW / SUPPORT', color: '#22c55e', lineStyle: 0 }),
  ])
})

// The real short-pattern collector and label reducers remain independent consumers.
describe('guide and visible formation selection', () => {
  const source = [
    [110, 115, 105, 110],
    [110, 114, 106, 110],
    [110, 113, 107, 110],
    [110, 111, 109, 110],
    [110, 114, 109.5, 113],
  ].map(([open, high, low, close], i) => ({
    time: 1700000000 + i * 60,
    open,
    high,
    low,
    close,
    volume: 1,
  }))
  it('keeps no-target NR4/inside geometry when a generic confirmed Engulfing wins the candle label', async () => {
    const { recognizeFidelityShortPatterns } = await import('./fidelityShortPatterns')
    const { primaryArchiveLabels, deduplicateArchiveMatches } = await import(
      './archivePatternLabels'
    )
    const { makePatternGuidance } = await import('../neo-desk/livePatternGuidance')
    const shapes = recognizeFidelityShortPatterns(source).map((e) => ({
      ...e,
      time: source.at(-1)!.time,
    }))
    expect(shapes.every((e) => e.target === undefined)).toBe(true)
    const candle = {
      ...shapes[0],
      name: 'Bullish Engulfing confirmed',
      pattern: 'engulfing',
      structure: undefined,
    }
    const events = deduplicateArchiveMatches([...shapes, candle])
    expect(primaryArchiveLabels(events).map((e) => e.name)).toContain(candle.name)
    const guide = makePatternGuidance(events, source, 60, source.at(-1)!.time + 60, null)
    const outlines = cryptoFormationSegments(events, source, source[0].time, source.at(-1)!.time)
    expect(outlines.length).toBeGreaterThan(0)
    expect(outlines.every((line) => line.title === guide.event?.name)).toBe(true)
    expect(outlines.map((line) => line.points)).toEqual(guide.event?.structure)
  })
  it('uses the same deterministic shape preference for every same-time input order', async () => {
    const { recognizeFidelityShortPatterns } = await import('./fidelityShortPatterns')
    const { deduplicateArchiveMatches } = await import('./archivePatternLabels')
    const { makePatternGuidance } = await import('../neo-desk/livePatternGuidance')
    const shapes = recognizeFidelityShortPatterns(source).map((e) => ({
      ...e,
      time: source.at(-1)!.time,
    }))
    expect(shapes.map((e) => e.pattern)).toEqual(['nr4-breakout', 'inside-bar-breakout'])
    for (const input of [shapes, [...shapes].reverse()]) {
      const events = deduplicateArchiveMatches(input)
      const guide = makePatternGuidance(events, source, 60, source.at(-1)!.time + 60, null)
      const outlines = cryptoFormationSegments(events, source, source[0].time, source.at(-1)!.time)
      expect(guide.event?.pattern).toBe('inside-bar-breakout')
      expect(outlines.every((line) => line.title === guide.event?.name)).toBe(true)
      expect(outlines.map((line) => line.points)).toEqual(guide.event?.structure)
    }
  })
})
