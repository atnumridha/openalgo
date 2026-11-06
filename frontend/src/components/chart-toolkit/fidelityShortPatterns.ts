import type { Bar } from './model'
import type { ArchiveMatch } from './archiveConfirmations'
/** Fidelity short-term families; range/context tolerances below are local operational choices.
 * https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/learning-center/Idenitfying-Chart-Patterns.pdf
 * Completed bars only. The collector owns session/gap continuity. */
export function recognizeFidelityShortPatterns(bars: Bar[]): ArchiveMatch[] {
  if (
    bars.length < 5 ||
    bars.some(
      (b, i) =>
        ![b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) ||
        b.time <= 0 ||
        b.low <= 0 ||
        b.high <= b.low ||
        b.high < Math.max(b.open, b.close) ||
        b.low > Math.min(b.open, b.close) ||
        (i > 0 && b.time <= bars[i - 1].time)
    )
  )
    return []
  const c = bars.at(-1)!,
    p = bars.at(-2)!,
    a = bars.at(-3)!,
    out: ArchiveMatch[] = []
  const side = c.close > p.high ? 'CALL' : c.close < p.low ? 'PUT' : null
  const add = (
    pattern: string,
    name: string,
    first: Bar,
    boundary: number,
    extreme: number,
    target?: number
  ) => {
    if (!side || (target != null && (side === 'CALL' ? target <= c.close : target >= c.close)))
      return
    const low = Math.min(first.low, p.low),
      high = Math.max(first.high, p.high)
    out.push({
      pattern,
      name,
      side,
      confirmed: true,
      entry: c.close,
      extreme,
      target,
      startTime: first.time,
      boundary: [
        { time: first.time, price: boundary },
        { time: c.time, price: boundary },
      ],
      structure: [
        [
          { time: first.time, price: low },
          { time: c.time, price: low },
        ],
        [
          { time: first.time, price: high },
          { time: c.time, price: high },
        ],
      ],
    })
  }
  if (side) {
    const range = p.high - p.low,
      boundary = side === 'CALL' ? p.high : p.low,
      extreme = side === 'CALL' ? p.low : p.high
    if (bars.slice(-5, -2).every((b) => b.high - b.low > range))
      add('nr4-breakout', 'NR4 Breakout', p, boundary, extreme)
    if (p.high < a.high && p.low > a.low)
      add('inside-bar-breakout', 'Inside Bar Breakout', p, boundary, extreme)
  }
  if (bars.length >= 8) {
    const pre = bars.slice(-8, -3),
      maxRange = Math.max(...pre.slice(-3).map((b) => b.high - b.low)),
      ar = a.high - a.low,
      pr = p.high - p.low
    for (const bull of [true, false]) {
      const trend = bull ? pre[0].close > pre.at(-1)!.close : pre[0].close < pre.at(-1)!.close
      const first = bull
        ? a.close < a.open && (a.close - a.low) / ar <= 0.25
        : a.close > a.open && (a.high - a.close) / ar <= 0.25
      const second = bull
        ? p.close > p.open && (p.close - p.low) / pr >= 0.5
        : p.close < p.open && (p.high - p.close) / pr >= 0.5
      const equal = bull ? Math.abs(a.low - p.low) : Math.abs(a.high - p.high)
      if (
        trend &&
        first &&
        second &&
        ar > maxRange &&
        pr > maxRange &&
        equal <= Math.max(ar, pr) * 0.15 &&
        (bull ? side === 'CALL' : side === 'PUT')
      ) {
        const low = Math.min(a.low, p.low),
          high = Math.max(a.high, p.high),
          height = high - low
        add(
          bull ? 'pipe-bottom' : 'pipe-top',
          bull ? 'Pipe Bottom' : 'Pipe Top',
          a,
          bull ? p.high : p.low,
          bull ? low : high,
          bull ? high + height : low - height
        )
      }
    }
  }
  return out
}
