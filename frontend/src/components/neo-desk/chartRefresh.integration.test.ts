import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CandlestickSeries, LineSeries, createChart, type IChartApi, type UTCTimestamp } from 'lightweight-charts'
import { chartBars, computeStudies } from './tradingViewStudies'
import { protectChartHistoryRefresh } from './chartHistoryRefresh'

// Use the real chart dependency: a series mock cannot expose stale renderer indexes.
// This characterizes the refresh regression fixed by TradingView #2110 / #2044.
const charts: IChartApi[] = []

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (this: HTMLCanvasElement) {
    const context = new Proxy({
      canvas: this,
      measureText: (text: string) => ({ width: text.length * 7 }),
      createLinearGradient: () => ({ addColorStop() {} }),
      getTransform: () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }),
      getImageData: () => ({ data: new Uint8ClampedArray(4) }),
    }, { get: (target, key) => target[key as keyof typeof target] ?? (() => {}) })
    return context as unknown as CanvasRenderingContext2D
  })
})

it('tracks whitespace changes made by live and historical updates without clearing ordinary quote hover', () => {
  const chart = createChart(document.createElement('div'), { width: 800, height: 500 })
  charts.push(chart)
  const clearCrosshair = vi.spyOn(chart, 'clearCrosshairPosition')
  protectChartHistoryRefresh(chart)
  const line = chart.addSeries(LineSeries)
  const first = 1793850300 as UTCTimestamp
  const second = (first + 60) as UTCTimestamp
  line.setData([{ time: first, value: 100 }, { time: second }])
  const clears = clearCrosshair.mock.calls.length
  line.update({ time: second, value: 101 })
  expect(clearCrosshair).toHaveBeenCalledTimes(clears)
  line.setData([{ time: first, value: 100 }, { time: second }])
  expect(clearCrosshair).toHaveBeenCalledTimes(clears + 1)
  line.update({ time: first, value: 99 }, true)
  line.setData([{ time: first, value: 100 }, { time: second }])
  expect(clearCrosshair).toHaveBeenCalledTimes(clears + 1)
  line.update({ time: first }, true)
  line.setData([{ time: first, value: 100 }, { time: second }])
  expect(clearCrosshair).toHaveBeenCalledTimes(clears + 2)
  expect(() => chart.takeScreenshot()).not.toThrow()
})

afterEach(() => {
  for (const chart of charts.splice(0)) chart.remove()
  vi.restoreAllMocks()
})

it.each([
  ['1m', false], ['15m', false], ['1m', true], ['15m', true],
] as const)('keeps %s candles renderable when history shrinks (guard: %s)', (interval, guarded) => {
  const seconds = interval === '1m' ? 60 : 900
  const candles = chartBars(Array.from({ length: 40 }, (_, i) => ({
    time: Date.UTC(2026, 10, 5, 9, 15) / 1000 + i * seconds,
    open: 100 + i, high: 103 + i, low: 99 + i, close: 102 + i, volume: 10,
  })))
  const chart = createChart(document.createElement('div'), {
    width: 800, height: 500, autoSize: false,
    timeScale: { fixLeftEdge: true, fixRightEdge: true },
  })
  charts.push(chart)
  const clearCrosshair = vi.spyOn(chart, 'clearCrosshairPosition')
  if (guarded) protectChartHistoryRefresh(chart)
  const price = chart.addSeries(CandlestickSeries)
  const average = chart.addSeries(LineSeries)
  price.setData(candles.map(bar => ({ ...bar, time: bar.time as UTCTimestamp })))
  average.setData(computeStudies(candles, interval).ema)
  chart.timeScale().fitContent()
  chart.takeScreenshot()
  chart.setCrosshairPosition(candles[20].close, candles[20].time as UTCTimestamp, price)
  chart.takeScreenshot()

  const shorter = candles.slice(10)
  expect(() => {
    price.setData(shorter.map(bar => ({ ...bar, time: bar.time as UTCTimestamp })))
    // Like study visibility/options updates between the host's series refreshes.
    price.applyOptions({})
    average.setData(computeStudies(shorter, interval).ema)
    chart.takeScreenshot()
    const clears = clearCrosshair.mock.calls.length
    // Quote-driven study redraws may replace values at the same timestamps.
    // They must preserve hover, as must the direct incremental quote path.
    price.setData(shorter.map(bar => ({ ...bar, time: bar.time as UTCTimestamp, close: bar.close + 0.5 })))
    chart.takeScreenshot()
    price.update({ ...shorter.at(-1)!, time: shorter.at(-1)!.time as UTCTimestamp, close: 140 })
    chart.takeScreenshot()
    expect(clearCrosshair).toHaveBeenCalledTimes(clears)
  }).not.toThrow()
  expect(price.data()).toHaveLength(30)
  expect(price.data().at(-1)).toMatchObject({ time: candles[39].time, close: 140 })
  if (guarded) {
    const appended = { ...shorter.at(-1)!, time: (candles[39].time + seconds) as UTCTimestamp }
    const clears = clearCrosshair.mock.calls.length
    price.update(appended)
    expect(clearCrosshair).toHaveBeenCalledTimes(clears)
    chart.setCrosshairPosition(appended.close, appended.time, price)
    price.setData(shorter.map(bar => ({ ...bar, time: bar.time as UTCTimestamp })))
    expect(clearCrosshair).toHaveBeenCalledTimes(clears + 1)
    expect(() => chart.takeScreenshot()).not.toThrow()
  }
})
