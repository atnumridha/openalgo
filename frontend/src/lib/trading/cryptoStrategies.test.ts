import { describe, expect, it } from 'vitest'
import {
  analyseCrypto,
  backtestCrypto,
  DEFAULT_CRYPTO_SETTINGS,
  type Candle,
} from './cryptoStrategies'
const bars = (n = 140): Candle[] =>
  Array.from({ length: n }, (_, i) => ({
    time: i * 180,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 10,
  }))
const cfg = DEFAULT_CRYPTO_SETTINGS

describe('source-backed Hummingbot strategy ports', () => {
  it('waits for warmup, valid costs, and continuous candles', () => {
    expect(analyseCrypto('bollinger', bars(20), cfg).side).toBe('WAIT')
    expect(() => analyseCrypto('bollinger', bars(), { ...cfg, quantity: 0 })).toThrow()
    const b = bars()
    b[50].time += 30
    expect(analyseCrypto('bollinger', b, cfg).reason).toMatch(/continuous/)
  })
  it('matches published Bollinger100/2 strict thresholds in both directions', () => {
    const b = bars()
    b[139] = { ...b[139], low: 89, close: 90 }
    expect(analyseCrypto('bollinger', b, cfg).side).toBe('LONG')
    b[139] = { ...b[139], low: 99, high: 111, close: 110 }
    expect(analyseCrypto('bollinger', b, cfg).side).toBe('SHORT')
    expect(analyseCrypto('bollinger', bars(), cfg).side).toBe('WAIT')
  })
  it('builds a tick-rounded plan and exposes app exit assumptions', () => {
    const b = bars()
    b[139] = { ...b[139], low: 89, close: 90 }
    const p = analyseCrypto('bollinger', b, { ...cfg, tick: 0.5 })
    expect(p.stop!).toBeLessThan(p.entry!)
    expect(p.target!).toBeGreaterThan(p.entry!)
    expect(p.stop! / 0.5).toBeCloseTo(Math.round(p.stop! / 0.5))
    expect(p.assumptions).toMatch(/app/i)
  })
  it('MACD BB requires all three source conditions, not just an oversold band', () => {
    const b = bars()
    b[139] = { ...b[139], low: 89, close: 90 }
    expect(analyseCrypto('macd-bb', b, cfg).side).toBe('WAIT')
    const p = analyseCrypto('macd-bb', b, cfg)
    expect(p.evidence).toContain('MACD 21/42/9')
  })
  it('SuperTrend retains its published 20/4/1% distance rules', () => {
    const b = bars()
    const p = analyseCrypto('supertrend', b, cfg)
    expect(p.side).toBe('WAIT')
    expect(p.evidence).toContain('SuperTrend 20 × 4')
  })
  it('future candles cannot change an earlier analysis or earlier closed trade', () => {
    const b = bars(200)
    b[130] = { ...b[130], high: 111, close: 110 }
    b[131] = { ...b[131], open: 110, high: 150, low: 50, close: 100 }
    const a = backtestCrypto('bollinger', b.slice(0, 160), cfg)
    expect(a.trades.length).toBeGreaterThan(0)
    const t = a.trades[0]
    expect(t.entryTime).toBe(b[131].time)
    expect(t.reason).toBe('stop')
    expect(t.net).toBeLessThan(t.gross)
    expect(backtestCrypto('bollinger', b, cfg).trades[0]).toEqual(t)
  })
  it('rejects gaps past the planned stop and reports sample coverage', () => {
    const b = bars(180)
    b[130] = { ...b[130], high: 111, close: 110 }
    b[131] = { ...b[131], open: 140, high: 141, low: 139, close: 140 }
    const r = backtestCrypto('bollinger', b, cfg)
    expect(r.trades.some((x) => x.entryTime === b[131].time)).toBe(false)
    expect(r.bars).toBe(180)
    expect(r.from).toBe(0)
    expect(r.to).toBe(b[179].time)
  })
  it('validates OHLC and never treats missing data as a signal', () => {
    const b = bars()
    b[139].close = NaN
    expect(analyseCrypto('bollinger', b, cfg).side).toBe('WAIT')
    expect(() => backtestCrypto('bollinger', b, cfg)).toThrow()
  })
  it('fees and slippage cannot be negative or silently default to zero', () => {
    expect(() => analyseCrypto('bollinger', bars(), { ...cfg, feePct: -1 })).toThrow()
    expect(() => analyseCrypto('bollinger', bars(), { ...cfg, slippagePct: NaN })).toThrow()
  })
})

import reference from './cryptoStrategyReference.json'
it('matches pinned upstream pandas-ta/TA-Lib reference vectors across regimes', () => {
  for (const sample of reference.cases) {
    const b = sample.closes.map((close, i) => ({
      time: i * 180,
      open: sample.closes[Math.max(0, i - 1)],
      high: Math.max(close, sample.closes[Math.max(0, i - 1)]) + 0.3,
      low: Math.min(close, sample.closes[Math.max(0, i - 1)]) - 0.3,
      close,
    }))
    for (const id of ['bollinger', 'macd-bb', 'supertrend'] as const) {
      const p = analyseCrypto(id, b, cfg),
        e = sample.expected[id]
      expect(p.side, id).toBe(e.side)
      const metrics = (p as unknown as { metrics: Record<string, number> }).metrics
      for (const [name, value] of Object.entries(e))
        if (name !== 'side') expect(metrics[name], `${id} ${name}`).toBeCloseTo(value as number, 7)
    }
  }
})
it('uses the published rolling history window rather than older loaded history', () => {
  const b = bars(200)
  for (let i = 0; i < 80; i++)
    b[i] = { ...b[i], open: 160 + i, high: 161 + i, low: 159 + i, close: 160 + i }
  for (const id of ['bollinger', 'macd-bb', 'supertrend'] as const) {
    const n = id === 'bollinger' ? 100 : id === 'macd-bb' ? 120 : 30
    expect(analyseCrypto(id, b, cfg)).toEqual(analyseCrypto(id, b.slice(-n), cfg))
  }
})
