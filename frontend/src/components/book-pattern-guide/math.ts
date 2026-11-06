import type { BookBar, BookIndicatorSnapshot, BookPivot, BookSettings } from './types'
export const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)
export function validBar(b: BookBar): boolean {
  return (
    (b.closeTime === undefined || (finite(b.closeTime) && b.closeTime > b.time)) &&
    !b.repaired &&
    [b.time, b.open, b.high, b.low, b.close].every(finite) &&
    b.time > 0 &&
    Math.min(b.open, b.high, b.low, b.close) > 0 &&
    b.high > b.low &&
    b.high >= Math.max(b.open, b.close) &&
    b.low <= Math.min(b.open, b.close)
  )
}
export const body = (b: BookBar) => Math.abs(b.close - b.open)
export const bodyTop = (b: BookBar) => Math.max(b.open, b.close)
export const bodyBottom = (b: BookBar) => Math.min(b.open, b.close)
export const upperWick = (b: BookBar) => b.high - bodyTop(b)
export const lowerWick = (b: BookBar) => bodyBottom(b) - b.low
export const direction = (b: BookBar) =>
  b.close > b.open ? 'long' : b.close < b.open ? 'short' : 'neutral'
export const mean = (n: number[]) => n.reduce((a, b) => a + b, 0) / n.length
export const median = (n: number[]) => {
  const a = [...n].sort((a, b) => a - b)
  return (a[Math.floor((a.length - 1) / 2)]! + a[Math.floor(a.length / 2)]!) / 2
}
export function tickRound(price: number, tick: number, up: boolean): number {
  return Number(
    ((up ? Math.ceil(price / tick - 1e-9) : Math.floor(price / tick + 1e-9)) * tick).toPrecision(14)
  )
}
export const project = (a: BookPivot, b: BookPivot, index: number) =>
  a.price + ((b.price - a.price) * (index - a.index)) / (b.index - a.index)
export function confirmedPivots(
  bars: BookBar[],
  left: number,
  right: number,
  spacing = 3
): BookPivot[] {
  const out: BookPivot[] = []
  for (let i = left; i + right < bars.length; i++) {
    const b = bars[i]!
    const window = bars.slice(i - left, i + right + 1)
    if (!window.every(validBar)) continue
    const high = window.every((w, j) => j === left || w.high < b.high),
      low = window.every((w, j) => j === left || w.low > b.low)
    if (high === low) continue // Outside bar is not an unambiguous alternating swing.
    const p: BookPivot = {
      index: i,
      time: b.time,
      price: high ? b.high : b.low,
      side: high ? 'high' : 'low',
      recognitionIndex: i + right,
      recognitionTime: bars[i + right]!.time,
    }
    const last = out.at(-1)
    if (last?.side === p.side) {
      if (p.side === 'high' ? p.price > last.price : p.price < last.price) out[out.length - 1] = p
    } else if (!last || p.index - last.index >= spacing) out.push(p)
  }
  return out
}
/** SMA seeded EMA and Wilder averages; an invalid bar resets rather than bridges missing evidence. */
export function indicators(bars: BookBar[], s: BookSettings): BookIndicatorSnapshot[] {
  const out: BookIndicatorSnapshot[] = []
  let run: BookBar[] = []
  let fast: number | undefined,
    slow: number | undefined,
    mf: number | undefined,
    ms: number | undefined,
    sig: number | undefined,
    atr: number | undefined,
    gain: number | undefined,
    loss: number | undefined
  let macds: number[] = []
  let fasts: (number | undefined)[] = []
  let trs: number[] = []
  let gains: number[] = [],
    losses: number[] = []
  const ma = (prev: number | undefined, values: number[], p: number) =>
    values.length < p
      ? undefined
      : s.maType === 'sma'
        ? mean(values.slice(-p))
        : prev === undefined
          ? mean(values.slice(-p))
          : prev + ((values.at(-1)! - prev) * 2) / (p + 1)
  const ema = (prev: number | undefined, values: number[], p: number) =>
    values.length < p
      ? undefined
      : prev === undefined
        ? mean(values.slice(-p))
        : prev + ((values.at(-1)! - prev) * 2) / (p + 1)
  for (const b of bars) {
    if (!validBar(b)) {
      out.push({ trend: 'unavailable' })
      run = []
      fast = slow = mf = ms = sig = atr = gain = loss = undefined
      macds = []
      fasts = []
      trs = []
      gains = []
      losses = []
      continue
    }
    const prev = run.at(-1)
    run.push(b)
    const closes = run.map((b) => b.close)
    fast = ma(fast, closes, s.maFast)
    slow = ma(slow, closes, s.maSlow)
    fasts.push(fast)
    mf = ema(mf, closes, s.macdFast)
    ms = ema(ms, closes, s.macdSlow)
    let macd: number | undefined
    if (mf !== undefined && ms !== undefined) {
      macd = mf - ms
      macds.push(macd)
      sig = ema(sig, macds, s.macdSignal)
    }
    const tr = prev
      ? Math.max(b.high - b.low, Math.abs(b.high - prev.close), Math.abs(b.low - prev.close))
      : b.high - b.low
    trs.push(tr)
    if (trs.length >= s.atrPeriod)
      atr =
        atr === undefined
          ? mean(trs.slice(-s.atrPeriod))
          : (atr * (s.atrPeriod - 1) + tr) / s.atrPeriod
    if (prev) {
      gains.push(Math.max(0, b.close - prev.close))
      losses.push(Math.max(0, prev.close - b.close))
      if (gains.length >= s.rsiPeriod) {
        gain =
          gain === undefined
            ? mean(gains.slice(-s.rsiPeriod))
            : (gain * (s.rsiPeriod - 1) + gains.at(-1)!) / s.rsiPeriod
        loss =
          loss === undefined
            ? mean(losses.slice(-s.rsiPeriod))
            : (loss * (s.rsiPeriod - 1) + losses.at(-1)!) / s.rsiPeriod
      }
    }
    const rsi =
      gain === undefined || loss === undefined
        ? undefined
        : gain === 0 && loss === 0
          ? 50
          : loss === 0
            ? 100
            : 100 - 100 / (1 + gain / loss)
    const priorFast = fasts[fasts.length - 1 - s.maSlopeBars]
    const trend =
      run.length < Math.max(s.trendWarmup, s.maSlow + s.maSlopeBars) ||
      fast === undefined ||
      slow === undefined ||
      priorFast === undefined
        ? 'unavailable'
        : fast > slow && fast > priorFast
          ? 'bull'
          : fast < slow && fast < priorFast
            ? 'bear'
            : 'neutral'
    const volumes = run.slice(-s.volumePeriod - 1, -1).map((b) => b.volume)
    out.push({
      trend,
      maFast: fast,
      maSlow: slow,
      rsi,
      macd,
      macdSignal: sig,
      atr,
      volumeMean:
        volumes.length === s.volumePeriod && volumes.every((v) => finite(v) && v > 0)
          ? mean(volumes)
          : undefined,
    })
  }
  return out
}
