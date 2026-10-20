/** Source rule ports, not an upstream execution engine.
 * Hummingbot Foundation, Apache-2.0. Revision and notices: docs/research/crypto-strategy-sources.md.
 * Changes: TypeScript causal closed-bar evaluation, conservative simulation, explicit app exits.
 */
export type Candle = {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}
export type CryptoStrategy = 'bollinger' | 'macd-bb' | 'supertrend'
export type CryptoSettings = {
  quantity: number
  contractValue: number
  tick: number
  feePct: number
  slippagePct: number
  stopPct: number
  reward: number
  maxBars: number
}
export const DEFAULT_CRYPTO_SETTINGS: CryptoSettings = {
  quantity: 1,
  contractValue: 0.001,
  tick: 0.5,
  feePct: 0.059,
  slippagePct: 0.01,
  stopPct: 1,
  reward: 2,
  maxBars: 12,
}
const REV = '9af100d6822da7d2d0291a906c730ef172284ee2'
const source = (file: string) =>
  `https://github.com/hummingbot/hummingbot/blob/${REV}/controllers/directional_trading/${file}.py`
export const CRYPTO_STRATEGIES = {
  bollinger: {
    name: 'Bollinger V1 · mean reversion',
    source: source('bollinger_v1'),
    rules:
      'BB100, 2σ: long when %B < 0; short when %B > 1. Strict comparisons, no extra RSI or reclaim filter.',
    warmup: 100,
  },
  'macd-bb': {
    name: 'MACD + Bollinger V1',
    source: source('macd_bb_v1'),
    rules:
      'Long: %B < 0, MACD < 0 and histogram > 0. Short: %B > 1, MACD > 0 and histogram < 0. BB100/2; MACD21/42/9.',
    warmup: 120,
  },
  supertrend: {
    name: 'SuperTrend V1 · trend following',
    source: source('supertrend_v1'),
    rules:
      'SuperTrend20 × 4: follow direction only when distance from trend line / close is strictly below 1%.',
    warmup: 30,
  },
} as const
export type CryptoAnalysis = {
  side: 'LONG' | 'SHORT' | 'WAIT'
  reason: string
  evidence: string[]
  entry?: number
  stop?: number
  target?: number
  assumptions: string
  metrics?: Record<string, number>
}
const assumptions =
  'App exit template: price stop %, fixed reward multiple and maximum holding bars. These are not claimed as the upstream exit defaults. No orders are submitted.'
function settings(c: CryptoSettings) {
  if (
    !Object.values(c).every(Number.isFinite) ||
    c.quantity < 1 ||
    !Number.isInteger(c.quantity) ||
    c.quantity > 100000 ||
    c.contractValue <= 0 ||
    c.tick <= 0 ||
    c.feePct < 0 ||
    c.feePct > 5 ||
    c.slippagePct < 0 ||
    c.slippagePct > 5 ||
    c.stopPct <= 0 ||
    c.stopPct >= 50 ||
    c.reward < 1 ||
    c.reward > 10 ||
    !Number.isInteger(c.maxBars) ||
    c.maxBars < 1 ||
    c.maxBars > 1000
  )
    throw new Error('Enter valid quantity, contract size, tick, costs and risk settings.')
}
function valid(b: readonly Candle[]) {
  const step = b.length > 1 ? b[1].time - b[0].time : 0
  return b.every(
    (x, i) =>
      [x.time, x.open, x.high, x.low, x.close].every(Number.isFinite) &&
      x.low > 0 &&
      x.low <= Math.min(x.open, x.close) &&
      x.high >= Math.max(x.open, x.close) &&
      (!i || (step > 0 && x.time - b[i - 1].time === step))
  )
}
const mean = (x: readonly number[]) => x.reduce((a, b) => a + b, 0) / x.length
function ema(x: readonly number[], length: number): number[] {
  const out = Array<number>(x.length).fill(NaN)
  if (x.length < length) return out
  out[length - 1] = mean(x.slice(0, length))
  const k = 2 / (length + 1)
  for (let i = length; i < x.length; i++) out[i] = out[i - 1] + k * (x[i] - out[i - 1])
  return out
}
/** pandas-ta SuperTrend recurrence with Wilder ATR; prices remain native USD. */
function supertrend(b: readonly Candle[]) {
  const n = 20,
    tr = b.map((x, i) =>
      i
        ? Math.max(
            x.high - x.low,
            Math.abs(x.high - b[i - 1].close),
            Math.abs(x.low - b[i - 1].close)
          )
        : NaN
    )
  let atr = mean(tr.slice(1, n + 1)),
    direction = 1,
    upper = NaN,
    lower = NaN,
    line = NaN
  for (let i = n; i < b.length; i++) {
    if (i > n) atr = (atr * (n - 1) + tr[i]) / n
    const mid = (b[i].high + b[i].low) / 2
    let u = mid + 4 * atr,
      l = mid - 4 * atr
    if (i > n) {
      if (b[i].close > upper) direction = 1
      else if (b[i].close < lower) direction = -1
      else if (direction > 0 && l < lower) l = lower
      else if (direction < 0 && u > upper) u = upper
    }
    upper = u
    lower = l
    line = direction > 0 ? l : u
  }
  return { direction, line }
}
export function analyseCrypto(
  id: CryptoStrategy,
  b: readonly Candle[],
  c: CryptoSettings
): CryptoAnalysis {
  settings(c)
  const metrics: Record<string, number> = {}
  const wait = (reason: string, evidence: string[] = []): CryptoAnalysis => ({
    side: 'WAIT',
    reason,
    evidence,
    assumptions,
    metrics,
  })
  if (!valid(b))
    return wait('Waiting for valid continuous candles; missing bars cannot confirm a setup.')
  if (b.length < CRYPTO_STRATEGIES[id].warmup)
    return wait(`Warm-up: ${b.length}/${CRYPTO_STRATEGIES[id].warmup} completed candles.`)
  b = b.slice(-CRYPTO_STRATEGIES[id].warmup)
  const closes = b.map((x) => x.close),
    last = closes.at(-1)!,
    w = closes.slice(-100),
    avg = mean(w),
    sd = Math.sqrt(mean(w.map((x) => (x - avg) ** 2)))
  let side: CryptoAnalysis['side'] = 'WAIT',
    evidence: string[] = []
  if (id === 'supertrend') {
    const s = supertrend(b),
      distance = Math.abs(last - s.line) / last
    Object.assign(metrics, { line: s.line, distance })
    evidence = ['SuperTrend 20 × 4', `Distance ${(distance * 100).toFixed(3)}% (must be < 1%)`]
    if (distance < 0.01) side = s.direction > 0 ? 'LONG' : 'SHORT'
  } else {
    const percentB = sd > 0 ? (last - (avg - 2 * sd)) / (4 * sd) : 0.5
    metrics.percentB = percentB
    evidence = [`Bollinger 100 / 2σ · %B ${percentB.toFixed(3)}`]
    if (id === 'bollinger') side = percentB < 0 ? 'LONG' : percentB > 1 ? 'SHORT' : 'WAIT'
    else {
      const fast = ema(closes.slice(21), 21),
        slow = ema(closes, 42),
        macds = slow.slice(41).map((x, i) => fast[i + 20] - x),
        m = macds.at(-1)!,
        signal = ema(macds, 9).at(-1)!,
        hist = m - signal
      Object.assign(metrics, { macd: m, hist })
      evidence.push('MACD 21/42/9', `MACD ${m.toFixed(4)} · histogram ${hist.toFixed(4)}`)
      side =
        percentB < 0 && hist > 0 && m < 0
          ? 'LONG'
          : percentB > 1 && hist < 0 && m > 0
            ? 'SHORT'
            : 'WAIT'
    }
  }
  if (side === 'WAIT') return wait('Published entry conditions are not all met.', evidence)
  const d = side === 'LONG' ? 1 : -1,
    distance = Math.max(c.tick, (last * c.stopPct) / 100)
  const snap = (x: number, up: boolean) =>
    Number(((up ? Math.ceil(x / c.tick) : Math.floor(x / c.tick)) * c.tick).toFixed(10))
  const stop = snap(last - d * distance, d > 0),
    target = snap(last + d * distance * c.reward, d > 0)
  if (stop <= 0 || target <= 0 || d * (last - stop) <= 0 || d * (target - last) <= 0)
    return wait('Price and tick size cannot fit this risk template.', evidence)
  return {
    side,
    reason: `${side} conditions met on the last completed candle. Indicative plan; await executable quote.`,
    evidence,
    entry: last,
    stop,
    target,
    assumptions,
    metrics,
  }
}
export type SimulatedTrade = {
  side: 'LONG' | 'SHORT'
  entryTime: number
  exitTime: number
  entry: number
  exit: number
  gross: number
  fees: number
  net: number
  reason: 'stop' | 'target' | 'time' | 'end'
}
export type CryptoBacktest = {
  trades: SimulatedTrade[]
  bars: number
  from: number | null
  to: number | null
  net: number
  fees: number
  winRate: number
  profitFactor: number | null
  expectancy: number
  drawdown: number
}
export function backtestCrypto(
  id: CryptoStrategy,
  bars: readonly Candle[],
  c: CryptoSettings
): CryptoBacktest {
  settings(c)
  if (!valid(bars)) throw new Error('Backtest requires valid continuous candles.')
  // Bounded synchronous research, never a broker simulation or live fill claim.
  if (bars.length > 2000) throw new Error('Use at most 2,000 completed candles per review.')
  const trades: SimulatedTrade[] = []
  let pos: {
    side: 'LONG' | 'SHORT'
    entry: number
    entryTime: number
    stop: number
    target: number
    index: number
  } | null = null
  for (let i = CRYPTO_STRATEGIES[id].warmup; i < bars.length; i++) {
    const b = bars[i]
    if (!pos) {
      const p = analyseCrypto(id, bars.slice(0, i), c)
      if (p.side === 'WAIT') continue
      const d = p.side === 'LONG' ? 1 : -1,
        entry = b.open * (1 + (d * c.slippagePct) / 100)
      if (d * (entry - p.stop!) <= 0 || d * (p.target! - entry) <= 0) continue
      pos = { side: p.side, entry, entryTime: b.time, stop: p.stop!, target: p.target!, index: i }
    }
    const d = pos.side === 'LONG' ? 1 : -1,
      stop = d > 0 ? b.low <= pos.stop : b.high >= pos.stop,
      target = d > 0 ? b.high >= pos.target : b.low <= pos.target
    let exit: number | undefined,
      reason: SimulatedTrade['reason'] = 'time'
    if (stop) {
      exit = d > 0 ? Math.min(b.open, pos.stop) : Math.max(b.open, pos.stop)
      reason = 'stop'
    } else if (target) {
      exit = pos.target
      reason = 'target'
    } else if (i - pos.index + 1 >= c.maxBars) exit = b.close
    else if (i === bars.length - 1) {
      exit = b.close
      reason = 'end'
    }
    if (exit !== undefined) {
      exit *= 1 - (d * c.slippagePct) / 100
      const units = c.quantity * c.contractValue,
        gross = d * (exit - pos.entry) * units,
        fees = ((exit + pos.entry) * units * c.feePct) / 100
      trades.push({
        side: pos.side,
        entryTime: pos.entryTime,
        exitTime: b.time,
        entry: pos.entry,
        exit,
        gross,
        fees,
        net: gross - fees,
        reason,
      })
      pos = null
    }
  }
  let net = 0,
    peak = 0,
    drawdown = 0,
    gain = 0,
    loss = 0
  for (const t of trades) {
    net += t.net
    peak = Math.max(peak, net)
    drawdown = Math.max(drawdown, peak - net)
    gain += Math.max(0, t.net)
    loss += Math.max(0, -t.net)
  }
  return {
    trades,
    bars: bars.length,
    from: bars[0]?.time ?? null,
    to: bars.at(-1)?.time ?? null,
    net,
    fees: trades.reduce((a, x) => a + x.fees, 0),
    winRate: trades.length ? trades.filter((t) => t.net > 0).length / trades.length : 0,
    profitFactor: loss ? gain / loss : null,
    expectancy: trades.length ? net / trades.length : 0,
    drawdown,
  }
}
