import { describe, expect, it } from 'vitest'
import type { Bar } from './model'
import { analyzeTrend, combineTrend, higherTrendInterval, trendSummaryLabel } from './trendAnalysis'

const bars = (count: number, slope = 0, start = 100): Bar[] =>
  Array.from({ length: count }, (_, i) => {
    const close = start + slope * i + (slope ? 3 * Math.sin((i * Math.PI) / 5) : 0)
    return {
      time: 1_700_000_000 + i * 60,
      open: close,
      high: close + 1,
      low: close - 1,
      close,
      volume: 100,
    }
  })

describe('trend analysis', () => {
  it('selects a supported higher interval and stops at daily', () => {
    expect(
      ['1m', '3m', '5m', '15m', '30m', '1h', '1d', 'unknown', 'toString'].map(higherTrendInterval)
    ).toEqual(['5m', '15m', '15m', '1h', '1d', '1d', null, null, null])
  })
  it('keeps NSE hourly history across scheduled overnight and weekend closures', () => {
    const session = { start: 555, end: 930, offset: 19800 }
    const start = Date.UTC(2026, 9, 23, 3, 45) / 1000
    const input = bars(70, 0.3).map((b, i) => {
      const tradingDay = Math.floor(i / 7)
      const calendarDay = tradingDay === 0 ? 0 : tradingDay + 2
      return { ...b, time: start + calendarDay * 86400 + (i % 7) * 3600 }
    })
    expect(analyzeTrend(input, { seconds: 3600, session }).direction).toBe('up')
    expect(analyzeTrend(input, { seconds: 3600, indian: true }).direction).toBe('up')
    const missing = input.filter((_, i) => i !== 60)
    expect(analyzeTrend(missing, { seconds: 3600, session }).direction).toBe('unavailable')
  })
  it('keeps daily history across weekends but resets absent intraday crypto candles', () => {
    const start = Date.UTC(2026, 7, 3) / 1000
    const daily = bars(70, 0.3).map((b, i) => ({
      ...b,
      time: start + (i + 2 * Math.floor(i / 5)) * 86400,
    }))
    expect(analyzeTrend(daily, { seconds: 86400, indian: true }).direction).toBe('up')
    expect(analyzeTrend(daily, { seconds: 86400 }).direction).toBe('unavailable')
    const missing = bars(70, 0.3).map((b, i) => ({ ...b, time: b.time + (i >= 60 ? 60 : 0) }))
    expect(analyzeTrend(missing, { seconds: 60 }).direction).toBe('unavailable')
  })
  it('requires a complete EMA50 and slope window', () => {
    expect(analyzeTrend([])).toMatchObject({
      direction: 'unavailable',
      time: null,
      emaFast: null,
      emaSlow: null,
    })
    expect(analyzeTrend(bars(54, 0.3)).direction).toBe('unavailable')
  })
  it('recognizes rising and falling confirmed swings with matching EMAs', () => {
    expect(analyzeTrend(bars(100, 0.3))).toMatchObject({
      direction: 'up',
      label: 'Uptrend',
      time: 1_700_005_940,
    })
    expect(analyzeTrend(bars(100, -0.3))).toMatchObject({ direction: 'down', label: 'Downtrend' })
  })
  it('keeps flat prices sideways and labels smooth rising prices without swing confirmation', () => {
    expect(analyzeTrend(bars(100)).direction).toBe('sideways')
    const straight = bars(100).map((b, i) => ({
      ...b,
      open: 100 + i,
      close: 100 + i,
      high: 101 + i,
      low: 99 + i,
    }))
    expect(analyzeTrend(straight).direction).toBe('up')
    expect(analyzeTrend(straight).reason).toMatch(/pending/i)
    expect(analyzeTrend(bars(100)).emaSlow).toBe(100)
  })
  it('waits during a reversal then recognizes the new falling structure', () => {
    const rising = bars(100, 0.3)
    const falling = bars(100, -0.4, rising.at(-1)!.close).map((b, i) => ({
      ...b,
      time: rising.at(-1)!.time + (i + 1) * 60,
    }))
    expect(analyzeTrend([...rising, ...falling.slice(0, 8)]).direction).toBe('sideways')
    expect(analyzeTrend([...rising, ...falling]).direction).toBe('down')
  })
  it('never confirms a turning point using bars beyond the supplied prefix', () => {
    const input = bars(100, 0.3)
    const prefix = input.slice(0, 65)
    const saved = analyzeTrend(prefix)
    const changedFuture = [
      ...prefix,
      ...input.slice(65).map((b) => ({ ...b, open: 5, close: 5, high: 6, low: 4 })),
    ]
    analyzeTrend(changedFuture)
    expect(analyzeTrend(prefix)).toEqual(saved)
    expect(prefix).toEqual(input.slice(0, 65))
  })
  it('requires two right candles before a new swing can resolve conflicting structure', () => {
    const input = bars(101).map((b, i) => ({
      ...b,
      open: 100 + i,
      close: 100 + i,
      high: 101 + i,
      low: 99 + i,
    }))
    input[70].high = 400
    input[90].high = 300
    input[98].high = 500
    input[75].low = 5
    input[95].low = 10
    expect(analyzeTrend(input.slice(0, 100)).direction).toBe('sideways')
    expect(analyzeTrend(input).direction).toBe('up')
  })
  it('does not override two contradicting confirmed highs while low swings are pending', () => {
    const input = bars(100).map((b, i) => ({
      ...b,
      open: 100 + i,
      close: 100 + i,
      high: 101 + i,
      low: 99 + i,
    }))
    input[70].high = 400
    input[90].high = 300
    expect(analyzeTrend(input).direction).toBe('sideways')
  })
  it('ignores tiny directional movement relative to candle ranges', () => {
    const input = bars(100).map((b, i) => ({
      ...b,
      open: 100 + i * 0.0001,
      close: 100 + i * 0.0001,
    }))
    expect(analyzeTrend(input).direction).toBe('sideways')
  })
  it('rejects an invalid latest candle and resets after corrupt or unordered history', () => {
    const input = bars(100, 0.3)
    expect(
      analyzeTrend([...input, { ...input.at(-1)!, time: input.at(-1)!.time + 60, close: NaN }])
        .direction
    ).toBe('unavailable')
    const corrupt = input.map((b, i) => (i === 80 ? { ...b, high: b.low - 1 } : b))
    expect(analyzeTrend(corrupt).direction).toBe('unavailable')
    expect(analyzeTrend([...input, input[0]]).direction).toBe('unavailable')
  })
  it('resets EMA and swing evidence after a large time gap', () => {
    const input = bars(100, 0.3).map((b, i) => ({ ...b, time: b.time + (i >= 80 ? 86400 : 0) }))
    expect(analyzeTrend(input).direction).toBe('unavailable')
  })
  it('requires matching directional higher context and waits for conflicts', () => {
    const up = analyzeTrend(bars(100, 0.3)),
      down = analyzeTrend(bars(100, -0.3)),
      flat = analyzeTrend(bars(100))
    expect(combineTrend(up, up)).toMatchObject({ direction: 'up', aligned: true })
    expect(combineTrend(down, down)).toMatchObject({ direction: 'down', aligned: true })
    expect(combineTrend(up, down)).toMatchObject({ direction: 'sideways', aligned: false })
    expect(combineTrend(up, down).reason).toMatch(/wait/i)
    expect(combineTrend(up, flat)).toMatchObject({ direction: 'sideways', aligned: false })
    expect(combineTrend(up, null)).toMatchObject({ direction: 'unavailable', aligned: false })
    expect(combineTrend(analyzeTrend([]), up).direction).toBe('unavailable')
  })
})
it('distinguishes unconfirmed reversal pressure from genuinely sideways prices', () => {
  const rising = bars(100, 0.3)
  const falling = bars(100, -0.4, rising.at(-1)!.close).map((b, i) => ({
    ...b,
    time: rising.at(-1)!.time + (i + 1) * 60,
  }))
  const turning = analyzeTrend([...rising, ...falling.slice(0, 8)])
  expect(turning.direction).toBe('sideways')
  expect(turning.label).not.toBe('Sideways')
  expect(turning.reason).toMatch(/not confirmed|disagree/i)
  expect(analyzeTrend(bars(100)).label).toBe('Sideways')
})

it('shows mixed confirmation separately from a sideways range without changing eligibility', () => {
  const up = analyzeTrend(bars(100, 0.3)),
    down = analyzeTrend(bars(100, -0.3)),
    flat = analyzeTrend(bars(100))
  expect(trendSummaryLabel(up, down)).toBe('Not confirmed')
  expect(trendSummaryLabel(flat, flat)).toBe('Sideways')
  expect(trendSummaryLabel(up, up)).toBe('Uptrend')
  expect(trendSummaryLabel(down, down)).toBe('Downtrend')
  expect(combineTrend(up, down)).toMatchObject({ direction: 'sideways', aligned: false })
})

it('explains unbroken swing resistance blocking an otherwise rising EMA trend', () => {
  const input = bars(250).map((b, i) => ({
    ...b,
    open: 100 + i,
    close: 100 + i,
    high: 101 + i,
    low: 99 + i,
  }))
  input[70].high = 400
  input[90].high = 300
  const result = analyzeTrend(input)
  expect(result.label).toBe('Rising · unconfirmed')
  expect(result.reason).toMatch(/higher swing high/)
  expect(result.reason).toContain('300')
  expect(result.reason).toContain('400')
})

it('recognizes a completed breakout after obsolete lower highs instead of waiting forever for a pullback', () => {
  const input = bars(500).map((b, i) => ({
    ...b,
    open: 100 + i,
    close: 100 + i,
    high: 101 + i,
    low: 99 + i,
  }))
  input[70].high = 400
  input[90].high = 300
  const result = analyzeTrend(input)
  expect(result).toMatchObject({ direction: 'up', label: 'Uptrend' })
  expect(result.reason).toMatch(/closed above.*400/i)
})
it('mirrors confirmed structural breaks for a falling trend despite obsolete higher lows', () => {
  const rising = bars(500).map((b, i) => ({
    ...b,
    open: 100 + i,
    close: 100 + i,
    high: 101 + i,
    low: 99 + i,
  }))
  rising[70].high = 400
  rising[90].high = 300
  const falling = rising.map((b) => ({
    ...b,
    open: 1000 - b.open,
    close: 1000 - b.close,
    high: 1000 - b.low,
    low: 1000 - b.high,
  }))
  const result = analyzeTrend(falling)
  expect(result).toMatchObject({ direction: 'down', label: 'Downtrend' })
  expect(result.reason).toMatch(/closed below.*600/i)
})
it('requires a close through both confirmed levels and does not treat a wick or level touch as a breakout', () => {
  for (const close of [350, 400]) {
    const input = bars(close - 99).map((b, i) => ({
      ...b,
      open: 100 + i,
      close: 100 + i,
      high: 101 + i,
      low: 99 + i,
    }))
    input[70].high = 400
    input[90].high = 300
    input[input.length - 1].high = 500
    expect(analyzeTrend(input).direction).toBe('sideways')
  }
})
