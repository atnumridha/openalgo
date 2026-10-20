export interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}
export interface Signal {
  action: 'LONG' | 'SHORT' | 'HOLD'
  bias: 'LONG' | 'SHORT' | 'NEUTRAL'
  reason: string
  asof?: number
  ema20?: number
  ema50?: number
  ema9?: number
  rsi?: number
  atr?: number
}
function ema(values: number[], length: number): number[] {
  const out = Array<number>(values.length).fill(NaN)
  if (values.length < length) return out
  let value = values.slice(0, length).reduce((a, b) => a + b, 0) / length
  out[length - 1] = value
  for (let i = length; i < values.length; i++) {
    value += ((values[i] - value) * 2) / (length + 1)
    out[i] = value
  }
  return out
}
function completed(rows: Candle[], interval: number, now: number): Candle[] {
  const result = rows.filter((r) => r.time + interval <= now).sort((a, b) => a.time - b.time)
  const tail = result.slice(-60)
  if (
    tail.some(
      (r, i) =>
        ![r.time, r.open, r.high, r.low, r.close].every(Number.isFinite) ||
        r.low <= 0 ||
        r.high < Math.max(r.open, r.close, r.low) ||
        r.low > Math.min(r.open, r.close) ||
        (i > 0 && r.time - tail[i - 1].time !== interval)
    )
  )
    return []
  return result
}
export function analyzeSignal(one: Candle[], five: Candle[], now = Date.now() / 1000): Signal {
  const hold: Signal = {
    action: 'HOLD',
    bias: 'NEUTRAL',
    reason: 'Waiting for fresh, consecutive completed 1m and 5m candles.',
  }
  const m = completed(one, 60, now),
    f = completed(five, 300, now)
  if (m.length < 30 || f.length < 53 || now - m.at(-1)!.time > 150 || now - f.at(-1)!.time > 630)
    return hold
  const fast = ema(
      f.map((c) => c.close),
      20
    ),
    slow = ema(
      f.map((c) => c.close),
      50
    ),
    short = ema(
      m.map((c) => c.close),
      9
    )
  const last = m.at(-1)!,
    prev = m.at(-2)!
  const up =
    fast.at(-1)! > slow.at(-1)! && fast.at(-1)! > fast.at(-2)! && fast.at(-2)! > fast.at(-3)!
  const down =
    fast.at(-1)! < slow.at(-1)! && fast.at(-1)! < fast.at(-2)! && fast.at(-2)! < fast.at(-3)!
  let gain = 0,
    loss = 0,
    atr = 0
  for (let i = 1; i < m.length; i++) {
    const delta = m[i].close - m[i - 1].close
    const tr = Math.max(
      m[i].high - m[i].low,
      Math.abs(m[i].high - m[i - 1].close),
      Math.abs(m[i].low - m[i - 1].close)
    )
    if (i <= 14) {
      gain += Math.max(0, delta) / 14
      loss += Math.max(0, -delta) / 14
      atr += tr / 14
    } else {
      gain = (gain * 13 + Math.max(0, delta)) / 14
      loss = (loss * 13 + Math.max(0, -delta)) / 14
      atr = (atr * 13 + tr) / 14
    }
  }
  const rsi = gain === 0 && loss === 0 ? 50 : loss === 0 ? 100 : 100 - 100 / (1 + gain / loss)
  const long =
    up &&
    prev.low <= short.at(-2)! &&
    prev.high >= short.at(-2)! &&
    last.close > prev.high &&
    rsi >= 50
  const sell =
    down &&
    prev.high >= short.at(-2)! &&
    prev.low <= short.at(-2)! &&
    last.close < prev.low &&
    rsi <= 50
  return {
    action: long ? 'LONG' : sell ? 'SHORT' : 'HOLD',
    bias: up ? 'LONG' : down ? 'SHORT' : 'NEUTRAL',
    asof: last.time + 60,
    ema20: fast.at(-1),
    ema50: slow.at(-1),
    ema9: short.at(-1),
    rsi,
    atr,
    reason: long
      ? 'Rising 5m EMA20 above EMA50; 1m EMA9 pullback broke the prior high; RSI supports upward momentum.'
      : sell
        ? 'Falling 5m EMA20 below EMA50; 1m EMA9 pullback broke the prior low; RSI supports downward momentum.'
        : up || down
          ? 'Trend is directional; waiting for a completed EMA9 pullback and breakout candle.'
          : '5m trend indicators disagree or are flat.',
  }
}
