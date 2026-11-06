import type { Bar } from './model'
import type { ChartShapeMatch } from './chartShapePatterns'
export type ArchiveChartMatch = ChartShapeMatch
export interface SARPoint {
  time: number
  value: number
  side: 'CALL' | 'PUT'
  flip: boolean
}
const valid = (bs: Bar[]) =>
  bs.every(
    (b, i) =>
      [b.time, b.open, b.high, b.low, b.close, b.volume].every(Number.isFinite) &&
      Math.min(b.open, b.high, b.low, b.close) > 0 &&
      b.high >= Math.max(b.open, b.close) &&
      b.low <= Math.min(b.open, b.close) &&
      b.high > b.low &&
      b.volume >= 0 &&
      (!i || b.time > bs[i - 1].time)
  )
/** Wilder SAR (.02 step, .2 maximum), clamped to preceding two ranges.
 * Initial direction follows first two closes; initialization is explicit, not
 * bitwise TA-Lib parity. https://ta-lib.org/functions/sar.html */
export function parabolicSAR(bs: Bar[]): SARPoint[] {
  if (bs.length < 2 || !valid(bs)) return []
  let bull = bs[1].close >= bs[0].close,
    af = 0.02,
    sar = bull ? bs[0].low : bs[0].high,
    ep = bull ? Math.max(bs[0].high, bs[1].high) : Math.min(bs[0].low, bs[1].low)
  const out: SARPoint[] = [
    { time: bs[1].time, value: sar, side: bull ? 'CALL' : 'PUT', flip: false },
  ]
  for (let i = 2; i < bs.length; i++) {
    let next = sar + af * (ep - sar)
    next = bull
      ? Math.min(next, bs[i - 1].low, bs[i - 2].low)
      : Math.max(next, bs[i - 1].high, bs[i - 2].high)
    const flip = bull ? bs[i].low < next : bs[i].high > next
    if (flip) {
      bull = !bull
      next = ep
      ep = bull ? bs[i].high : bs[i].low
      af = 0.02
    } else if (bull ? bs[i].high > ep : bs[i].low < ep) {
      ep = bull ? bs[i].high : bs[i].low
      af = Math.min(0.2, af + 0.02)
    }
    sar = next
    out.push({ time: bs[i].time, value: sar, side: bull ? 'CALL' : 'PUT', flip })
  }
  return out
}
/** Local operational geometry: V reclaims a left shoulder after >=4 bars each
 * side with >=75% directional closes. Broadening needs three independently
 * confirmed widening touches per boundary. Slingshot: rising swing lows, a
 * sweep of the latest support and a close beyond the preceding candle high.
 * Every bearish geometry is a price-reflected counterpart. */
export function recognizeArchiveChartPatterns(history: Bar[]): ArchiveChartMatch[] {
  if (history.length < 12 || !valid(history)) return []
  const source = history.slice(-160),
    out: ArchiveChartMatch[] = []
  for (const bull of [true, false]) {
    const bs = bull
      ? source
      : source.map((b) => ({ ...b, open: -b.open, close: -b.close, high: -b.low, low: -b.high }))
    const n = bs.length - 1,
      c = bs[n],
      p = bs[n - 1]
    const add = (pattern: string, name: string, start: number) =>
      out.push({
        pattern,
        name,
        side: bull ? 'CALL' : 'PUT',
        extreme: (bull ? 1 : -1) * Math.min(...bs.slice(start).map((b) => b.low)),
      })
    for (let start = Math.max(0, n - 48); start <= n - 9; start++) {
      if (start > 0 && bs[start - 1].high >= bs[start].high) continue
      if (start > 1 && bs[start - 2].high >= bs[start].high) continue
      const bottom = Math.min(...bs.slice(start, n).map((b) => b.low)),
        k = bs.findIndex((b, i) => i >= start && i < n && b.low === bottom)
      if (k - start < 4 || n - k < 4 || n - k > 2.5 * (k - start) || k - start > 2.5 * (n - k))
        continue
      const shoulder = bs[start].high,
        depth = shoulder - bottom
      if (depth < Math.abs(c.close) * 0.006 || p.close > shoulder || c.close <= shoulder) continue
      if (bs.slice(k + 1, n).some((b) => b.close > shoulder)) continue
      const left = bs.slice(start + 1, k + 1),
        right = bs.slice(k + 1, n)
      if (
        left.filter((b, j) => b.close < bs[start + j].close).length < left.length * 0.75 ||
        right.filter((b, j) => b.close > bs[k + j].close).length < right.length * 0.75
      )
        continue
      add(bull ? 'v-bottom' : 'v-top', bull ? 'V Bottom' : 'V Top', start)
      break
    }
    const turns: { i: number; p: number; high: boolean }[] = []
    for (let i = 2; i < n - 2; i++) {
      const ns = [bs[i - 2], bs[i - 1], bs[i + 1], bs[i + 2]],
        high = ns.every((b) => bs[i].high > b.high),
        low = ns.every((b) => bs[i].low < b.low)
      if (high === low) continue
      const t = { i, p: high ? bs[i].high : bs[i].low, high },
        prev = turns.at(-1)
      if (prev && prev.high === high) {
        if (high ? t.p > prev.p : t.p < prev.p) turns[turns.length - 1] = t
      } else if (!prev || i - prev.i >= 3) turns.push(t)
    }
    const six = turns.slice(-6),
      hs = six.filter((t) => t.high),
      ls = six.filter((t) => !t.high)
    if (hs.length === 3 && ls.length === 3 && six.at(-1)!.i - six[0].i >= 16) {
      const upper = (i: number) =>
          hs[0].p + ((hs[2].p - hs[0].p) * (i - hs[0].i)) / (hs[2].i - hs[0].i),
        lower = (i: number) => ls[0].p + ((ls[2].p - ls[0].p) * (i - ls[0].i)) / (ls[2].i - ls[0].i)
      const width = upper(six[0].i) - lower(six[0].i),
        last = six.at(-1)!.i
      const upperSlope = (hs[2].p - hs[0].p) / (hs[2].i - hs[0].i),
        lowerSlope = (ls[2].p - ls[0].p) / (ls[2].i - ls[0].i)
      const megaphone =
        hs[0].p < hs[1].p && hs[1].p < hs[2].p && ls[0].p > ls[1].p && ls[1].p > ls[2].p
      // Operational interpretation of the sketch: a sloping widening range.
      // This describes geometry, not proof of institutional accumulation.
      const cylinder = upperSlope * lowerSlope > 0 && upperSlope > lowerSlope
      if (
        (megaphone || cylinder) &&
        n - last <= 16 &&
        width > 0 &&
        upper(n) - lower(n) > width * 1.3 &&
        Math.abs(hs[1].p - upper(hs[1].i)) < width * 0.1 &&
        Math.abs(ls[1].p - lower(ls[1].i)) < width * 0.1 &&
        bs
          .slice(six[0].i, n)
          .every(
            (bar, j) =>
              bar.close <= upper(six[0].i + j) + width * 0.03 &&
              bar.close >= lower(six[0].i + j) - width * 0.03
          ) &&
        p.close <= upper(n - 1) &&
        c.close > upper(n) &&
        bs.slice(last + 1, n).every((bar, j) => bar.close <= upper(last + j + 1))
      ) {
        const sign = bull ? 1 : -1,
          entry = source[n].close,
          target = sign * (upper(n) + upper(n) - lower(n))
        if (target > 0 && sign * (target - entry) > 0)
          out.push({
            pattern: cylinder ? 'livermore-cylinder' : 'broadening-wedge',
            name: cylinder ? 'Livermore Cylinder (expanding range)' : 'Megaphone',
            side: bull ? 'CALL' : 'PUT',
            entry,
            target,
            extreme: sign * Math.min(...bs.slice(six[0].i, n).map((bar) => bar.low)),
            startTime: source[six[0].i].time,
            boundary: [six[0].i, n].map((i) => ({ time: source[i].time, price: sign * upper(i) })),
            structure: [upper, lower].map((line) =>
              [six[0].i, n].map((i) => ({ time: source[i].time, price: sign * line(i) }))
            ),
          })
      }
    }
    const lows = turns.filter((t) => !t.high),
      support = lows.at(-1),
      earlier = lows.at(-2)
    if (
      support &&
      earlier &&
      support.p > earlier.p &&
      n - support.i <= 12 &&
      c.low < support.p &&
      c.close > p.high &&
      p.close >= support.p &&
      c.close > c.open
    )
      add('slingshot', 'Slingshot', support.i)
  }
  return out
}
