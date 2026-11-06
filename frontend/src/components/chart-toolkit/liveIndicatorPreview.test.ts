import { describe, expect, it } from 'vitest'
import type { SymbolData } from '@/lib/MarketDataManager'
import type { Bar } from './model'
import { LiveIndicatorPreview } from './liveIndicatorPreview'

const time = Date.parse('2026-10-29T13:15:00+05:30') / 1000
const now = (time + 20) * 1000
const bars: Bar[] = Array.from({ length: 80 }, (_, i) => ({
  time: time - (79 - i) * 900,
  open: 100,
  high: 101,
  low: 99,
  close: 100,
  volume: 0,
}))
const options = {
  symbol: 'NIFTY',
  exchange: 'NSE_INDEX',
  interval: '15m',
  seconds: 900,
  now,
  isAuthenticated: true,
  connectionEpoch: 7,
}
const quote = (price = 110, at = now): SymbolData => ({
  symbol: 'NIFTY',
  exchange: 'NSE_INDEX',
  lastUpdate: at,
  updateSource: 'websocket',
  connectionEpoch: 7,
  data: { ltp: price, timestamp: new Date(at).toISOString() },
})
describe('live indicator numeric preview', () => {
  it('reprices a forming candle immediately without mutating history or manufacturing volume', () => {
    const engine = new LiveIndicatorPreview()
    const original = structuredClone(bars)
    const first = engine.update(bars, time + 10, quote(), options)
    // 49 closes at100, live close110: SMA50=100.2, distance=9.780439%.
    expect(first?.values.ma).toBeCloseTo(9.780439, 5)
    expect(first?.time).toBe(now / 1000)
    const second = engine.update(bars, time + 10, quote(120, now + 1), { ...options, now: now + 1 })
    expect(second?.values.ma).toBeCloseTo(19.521912, 5)
    expect(second?.values).not.toHaveProperty('mfi')
    expect(second).not.toHaveProperty('side')
    expect(bars).toEqual(original)
  })
  it.each([
    { updateSource: 'rest' as const },
    { connectionEpoch: 6 },
    { symbol: 'SENSEX' },
    { exchange: 'BSE_INDEX' },
    { lastUpdate: now - 16000 },
    { lastUpdate: now + 1000 },
    { data: { ltp: 0, timestamp: new Date(now).toISOString() } },
    { data: { ltp: 110, timestamp: new Date(now - 16000).toISOString() } },
    { data: { ltp: 110 } },
  ])('rejects invalid/stale/wrong-session quote %j', (patch) => {
    expect(
      new LiveIndicatorPreview().update(bars, time + 1, { ...quote(), ...patch }, options)
    ).toBeNull()
  })
  it('rejects a disconnected stream and a tick older than the history observation', () => {
    const engine = new LiveIndicatorPreview()
    expect(
      engine.update(bars, time + 10, quote(), { ...options, isAuthenticated: false })
    ).toBeNull()
    expect(engine.update(bars, time + 21, quote(), options)).toBeNull()
  })
  it('waits for the broker forming candle when an interval was missed', () => {
    const engine = new LiveIndicatorPreview()
    expect(engine.update(bars.slice(0, -1), time + 10, quote(), options)).toBeNull()
    const later = now + 900000
    expect(engine.update(bars, time + 10, quote(120, later), { ...options, now: later })).toBeNull()
  })
  it('does not roll back an already observed value on an out-of-order tick', () => {
    const engine = new LiveIndicatorPreview()
    engine.update(bars, time + 10, quote(120), options)
    expect(engine.update(bars, time + 10, quote(110, now - 1), options)).toBeNull()
  })
})
