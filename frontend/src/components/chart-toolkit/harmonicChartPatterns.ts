import type { Bar } from './model'
import type { ChartShapeMatch } from './chartShapePatterns'
interface Pivot {
  i: number
  p: number
  high: boolean
}
/** Price ratios, not screen angles. Gartley: TradingView XABCD + Carney XA/AB=CD.
 * Cypher: TradingView Cypher tool (C/XA=1.13..1.414, D retraces XC, not XA).
 * Fixed-ratio tolerance is 0.03 ratio units; AB/CD equivalence tolerance 10%.
 * D needs two CLOSED right bars BEFORE the current reversal-confirmation candle.
 * The fixed break level is their high/low; no projected or future pivot labels. */
export function recognizeHarmonicPatterns(history: Bar[]): ChartShapeMatch[] {
  if (
    history.length < 20 ||
    history.some(
      (b, i) =>
        ![b.time, b.open, b.high, b.low, b.close, b.volume].every(Number.isFinite) ||
        Math.min(b.time, b.open, b.high, b.low, b.close) <= 0 ||
        b.volume < 0 ||
        b.high < Math.max(b.open, b.close, b.low) ||
        b.low > Math.min(b.open, b.close) ||
        (i > 0 && b.time <= history[i - 1].time)
    )
  )
    return []
  const source = history.slice(-180),
    out: ChartShapeMatch[] = []
  for (const bull of [true, false]) {
    const sign = bull ? 1 : -1
    const bs = source.map((b) => ({
      high: bull ? b.high : -b.low,
      low: bull ? b.low : -b.high,
      close: sign * b.close,
    }))
    const n = bs.length - 1,
      turns: Pivot[] = []
    for (let i = 2; i + 2 < n; i++) {
      const neighbors = [bs[i - 2], bs[i - 1], bs[i + 1], bs[i + 2]]
      const high = neighbors.every((b) => bs[i].high > b.high),
        low = neighbors.every((b) => bs[i].low < b.low)
      if (high === low) continue
      const p = { i, p: high ? bs[i].high : bs[i].low, high },
        last = turns.at(-1)
      if (last && last.high === high) {
        if (high ? p.p > last.p : p.p < last.p) turns[turns.length - 1] = p
      } else if (!last || i - last.i >= 3) turns.push(p)
    }
    const p = turns.slice(-5)
    if (p.length !== 5 || p[0].high || !p[1].high || p[2].high || !p[3].high || p[4].high) continue
    const [x, a, b, c, d] = p,
      xa = a.p - x.p,
      ab = a.p - b.p,
      bc = c.p - b.p,
      cd = c.p - d.p
    if (
      xa <= Math.abs(bs[n].close) * 0.003 ||
      Math.min(ab, bc, cd) <= 0 ||
      d.i - x.i < 12 ||
      n - d.i < 3 ||
      n - d.i > 12 ||
      !(x.p < d.p && d.p < b.p && b.p < a.p) ||
      bs.slice(d.i + 1).some((bar) => bar.low < d.p)
    )
      continue
    const near = (v: number, target: number) => Math.abs(v - target) <= 0.03
    const gartley =
      c.p < a.p &&
      near(ab / xa, 0.618) &&
      near((a.p - d.p) / xa, 0.786) &&
      bc / ab >= 0.618 &&
      bc / ab <= 0.786 &&
      cd / bc >= 1.27 &&
      cd / bc <= 1.618 &&
      Math.abs(cd / ab - 1) <= 0.1
    const xc = c.p - x.p
    const cypher =
      c.p > a.p &&
      ab / xa >= 0.382 &&
      ab / xa <= 0.618 &&
      xc / xa >= 1.13 &&
      xc / xa <= 1.414 &&
      near(cd / xc, 0.786)
    if (!gartley && !cypher) continue
    const level = Math.max(...bs.slice(d.i, d.i + 3).map((bar) => bar.high))
    if (
      bs[n - 1].close > level ||
      bs[n].close <= level ||
      bs.slice(d.i + 3, n).some((bar) => bar.close > level)
    )
      continue
    const target = sign * (d.p + 0.618 * cd),
      entry = source[n].close,
      extreme = sign * x.p
    if (target <= 0 || sign * (target - entry) <= 0 || sign * (entry - extreme) <= 0) continue
    const point = (v: Pivot) => ({ time: source[v.i].time, price: sign * v.p })
    const pattern = gartley ? 'gartley' : 'cypher'
    out.push({
      pattern,
      name: gartley ? 'Gartley' : 'Cypher',
      side: bull ? 'CALL' : 'PUT',
      entry,
      target,
      extreme,
      startTime: source[x.i].time,
      boundary: [
        { time: source[d.i + 2].time, price: sign * level },
        { time: source[n].time, price: sign * level },
      ],
      structure: [p.map(point), [x, b, d].map(point), [a, c].map(point)],
    })
  }
  return out
}
