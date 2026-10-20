import { describe, expect, it } from 'vitest'
import { chartIndicators } from './chartIndicators'
import { chartSessionWindow } from './chartSession'
import { type IndicatorCandle, tradeIndicators } from './tradeIndicatorsModel'

const now = Date.parse('2026-10-15T11:45:30+05:30') / 1000
const bucket = Math.floor((now + 19800) / 300) * 300
const session = chartSessionWindow(
  {
    date: '2026-10-15',
    timings: [{ exchange: 'NFO', start_time: '09:15', end_time: '15:40' }],
  },
  '2026-10-15',
  'NFO'
)
const quote = (ltp: number, time = now, volume?: number) => ({
  ltp,
  time,
  volume,
  observed_time: time,
  source: 'Live feed',
})
const bars = (step = 1): IndicatorCandle[] =>
  Array.from({ length: 40 }, (_, i) => ({
    time: bucket - (40 - i) * 300,
    open: 100 + i * step,
    high: 101 + i * step,
    low: 99 + i * step,
    close: 100 + i * step,
    volume: 650 + i,
  }))
describe('Open-trade indicators', () => {
  it('derives only the current forming bar volume and resets at the next bar', () => {
    const start = Math.floor((now + 19800) / 86400) * 86400 + 9 * 3600 + 15 * 60
    const day = Array.from({ length: (bucket - start) / 300 }, (_, i) => ({
      time: start + i * 300,
      open: 100,
      high: 101,
      low: 99,
      close: 100,
      volume: 100,
    }))
    const previous = day.length * 100
    expect(
      tradeIndicators(day, quote(101, now, previous + 50), '5m', now, session).currentVolume
    ).toBe(50)
    expect(
      tradeIndicators(day, quote(101, now, previous + 80), '5m', now, session).currentVolume
    ).toBe(80)
    const completed = [
      ...day,
      { time: bucket, open: 100, high: 101, low: 99, close: 101, volume: 80 },
    ]
    expect(
      tradeIndicators(completed, quote(102, now + 300, previous + 100), '5m', now + 300, session)
        .currentVolume
    ).toBe(20)
  })
  it('uses Wilder RSI on the forming bar and keeps day volume separate from closed-bar volume', () => {
    const history = bars()
    const q = quote(135, now, 900000)
    const result = tradeIndicators(history, q, '5m', now, session)
    const expected = chartIndicators([
      ...history,
      { time: bucket, open: 135, high: 135, low: 135, close: 135, volume: 0 },
    ]).at(-1)?.rsi14
    expect(result.rsi).toBe(expected)
    expect(result.live).toBe(true)
    expect(result.closedVolume).toBe(689)
    expect(history).toEqual(bars())
  })
  it('does not label a fresh price with old candles as live RSI', () => {
    const result = tradeIndicators(
      bars().map((bar) => ({ ...bar, time: bar.time - 600 })),
      quote(140),
      '5m',
      now,
      session
    )
    expect(result.live).toBe(false)
    expect(result.reason).toBe('Candles delayed')
  })
  it('requires fourteen price changes and never invents a neutral RSI', () => {
    expect(tradeIndicators(bars().slice(-13), quote(140), '5m', now, session).rsi).toBeNull()
    expect(tradeIndicators([], undefined, '5m', now, session).rsi).toBeNull()
    expect(tradeIndicators(bars(-1), undefined, '5m', now, session).rsi).toBe(0)
  })
  it('keeps stale or future quotes from updating the candle', () => {
    for (const time of [now - 6, now + 1]) {
      const result = tradeIndicators(bars(), quote(200, time), '5m', now, session)
      expect(result.live).toBe(false)
      expect(result.barTime).toBe(bucket - 300)
    }
  })
  it('changes bucket size with the selected timeframe', () => {
    const minuteBars = bars().map((bar, i) => ({ ...bar, time: bucket - (40 - i) * 60 }))
    const result = tradeIndicators(minuteBars, quote(140), '1m', now, session)
    expect(result.live).toBe(true)
    expect(result.barTime).toBe(bucket)
    expect(tradeIndicators(bars(), quote(140), 'unknown', now, session).rsi).toBeNull()
  })
  it('keeps historical RSI without extending candles when the session is closed or unverified', () => {
    for (const window of [null, { ...session!, end: now - 1 }]) {
      const result = tradeIndicators(bars(), quote(200), '5m', now, window)
      expect(result.barTime).toBe(bucket - 300)
      expect(result.rsi).toBe(100)
      expect(result.live).toBe(false)
      expect(result.currentVolume).toBeNull()
      expect(result.currentTime).toBeNull()
    }
  })
  it('does not extend a candle from a fresh broker receipt or missing exchange timestamp', () => {
    for (const q of [
      { ...quote(200), source: 'Broker snapshot' },
      { ltp: 200, source: 'Live feed', time: now },
      { ...quote(200), observed_time: now - 60 },
    ]) {
      const result = tradeIndicators(bars(), q, '5m', now, session)
      expect(result.barTime).toBe(bucket - 300)
      expect(result.rsi).toBe(100)
      expect(result.live).toBe(false)
    }
  })
  it('retains actual current-bar volume without using an unverified day counter', () => {
    const history = [...bars(), { ...bars().at(-1)!, time: bucket, volume: 42 }]
    const result = tradeIndicators(
      history,
      { ltp: 200, time: now, source: 'Broker snapshot', volume: 90000 },
      '5m',
      now,
      session
    )
    expect(result.currentVolume).toBe(42)
    expect(result.rsi).toBe(100)
    expect(result.live).toBe(false)
  })
  it('does not move a recent prior-bar tick into the new current bar', () => {
    const boundary = now - 29
    const result = tradeIndicators(bars(), quote(80, boundary - 2), '5m', boundary, session)
    expect(result.barTime).toBe(bucket - 300)
    expect(result.rsi).toBe(100)
    expect(result.live).toBe(false)
    expect(result.currentVolume).toBeNull()
  })
  it('derives current volume from the calendar opening time of a special session', () => {
    const specialNow = Date.parse('2026-11-08T18:10:30+05:30') / 1000
    const special = chartSessionWindow(
      {
        date: '2026-11-08',
        timings: [{ exchange: 'BFO', start_time: '18:00', end_time: '19:15' }],
      },
      '2026-11-08',
      'BFO'
    )
    const history = [
      {
        time: Date.UTC(2026, 10, 8, 18) / 1000,
        open: 100,
        high: 101,
        low: 99,
        close: 100,
        volume: 100,
      },
      {
        time: Date.UTC(2026, 10, 8, 18, 5) / 1000,
        open: 100,
        high: 102,
        low: 99,
        close: 101,
        volume: 200,
      },
    ]
    const result = tradeIndicators(history, quote(102, specialNow, 350), '5m', specialNow, special)
    expect(result.currentVolume).toBe(50)
    expect(result.currentTime).toBe(Date.UTC(2026, 10, 8, 18, 10) / 1000)
  })
})
