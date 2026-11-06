import type { Bar } from './model'
export interface ArchiveMatch {
  side: 'CALL' | 'PUT' | 'NEUTRAL'
  name: string
  pattern: string
  extreme: number
  confirmed?: boolean
  entry?: number
  target?: number
  startTime?: number
  boundary?: Array<{ time: number; price: number }>
  structure?: Array<Array<{ time: number; price: number }>>
}
export interface TimedArchiveMatch extends ArchiveMatch {
  time: number
}
/** A zone is the wick-to-body area of a two-left/two-right pivot, confirmed
 * before the pattern starts. It must produce >=2 candle-range displacement,
 * remain unbroken by a completed close, be touched by the pattern, then receive
 * a next-candle close beyond the pattern's last high/low. Local numeric rules. */
export function recognizeZoneConfirmations(
  bars: Bar[],
  detect: (bs: Bar[]) => ArchiveMatch[]
): ArchiveMatch[] {
  if (
    bars.length < 9 ||
    bars.some(
      (b, i) =>
        ![b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) ||
        b.high < b.low ||
        b.high < Math.max(b.open, b.close) ||
        b.low > Math.min(b.open, b.close) ||
        (i > 0 && b.time <= bars[i - 1].time)
    )
  )
    return []
  const n = bars.length - 1,
    c = bars[n],
    p = bars[n - 1],
    out: ArchiveMatch[] = []
  const candidates = detect(bars.slice(0, -1)).filter(
    (m) =>
      m.side !== 'NEUTRAL' &&
      /Hammer|Star|Pin Bar|Engulfing|Harami|Marubozu|Soldiers|Crows|Tweezer|Window/i.test(m.name)
  )
  for (const m of candidates) {
    const bull = m.side === 'CALL'
    const span = /Morning|Evening|Soldiers|Crows/i.test(m.name)
      ? 3
      : /Engulfing|Harami|Tweezer|Window/i.test(m.name)
        ? 2
        : 1
    if (bull ? !(c.close > p.high && c.close > c.open) : !(c.close < p.low && c.close < c.open))
      continue
    for (let i = n - span - 3; i >= 2; i--) {
      const b = bars[i],
        ns = [bars[i - 2], bars[i - 1], bars[i + 1], bars[i + 2]],
        pivot = bull ? ns.every((x) => x.low > b.low) : ns.every((x) => x.high < b.high)
      if (!pivot) continue
      const lo = bull ? b.low : Math.max(b.open, b.close),
        hi = bull ? Math.min(b.open, b.close) : b.high,
        r = b.high - b.low
      if (!(r > 0)) continue
      const displaced = bars
        .slice(i + 1, n - 2)
        .some((x) => (bull ? x.high >= hi + 2 * r : x.low <= lo - 2 * r))
      if (!displaced || bars.slice(i + 1, n).some((x) => (bull ? x.close < lo : x.close > hi)))
        continue
      if (!bars.slice(n - span, n).some((x) => x.low <= hi && x.high >= lo)) continue
      out.push({
        ...m,
        pattern: `zone-${m.pattern}`,
        name: `${m.name.replace(/^(Bullish|Bearish)\s+/i, '')} confirmed at ${bull ? 'demand' : 'supply'}`,
        extreme: bull ? Math.min(lo, m.extreme) : Math.max(hi, m.extreme),
      })
      break
    }
  }
  return out
}
export interface ArchiveReading {
  side: 'BULL' | 'BEAR' | 'WAIT'
  name: string
  invalid: number | null
  price: number | null
  time: number | null
}
/** Only a current-candle observation can give a fresh reading. More-specific
 * confirmed zones/structure outrank raw shapes. Equal-tier disagreement waits.
 * Prices are chart units, not an order instruction or a fabricated success rate. */
export function latestArchiveReading(matches: TimedArchiveMatch[], bars: Bar[]): ArchiveReading {
  const last = bars.at(-1),
    wait = (name: string): ArchiveReading => ({
      side: 'WAIT',
      name,
      invalid: null,
      price: last?.close ?? null,
      time: last?.time ?? null,
    })
  if (!last) return wait('No completed candle')
  const latest = matches.filter(
    (m) =>
      m.time === last.time &&
      m.confirmed === true &&
      m.side !== 'NEUTRAL' &&
      Number.isFinite(m.extreme) &&
      (m.side === 'CALL' ? m.extreme < last.close : m.extreme > last.close)
  )
  if (!latest.length) return wait('No fresh confirmed pattern')
  const priority = (m: TimedArchiveMatch) =>
    m.pattern.startsWith('zone-') ? 3 : m.pattern.startsWith('institutional_') ? 2 : 1
  const top = Math.max(...latest.map(priority)),
    best = latest.filter((m) => priority(m) === top)
  if (new Set(best.map((m) => m.side)).size > 1) return wait('Mixed signals')
  const chosen = best[0]
  return {
    side: chosen.side === 'CALL' ? 'BULL' : 'BEAR',
    name: chosen.name,
    invalid: chosen.extreme,
    price: last.close,
    time: last.time,
  }
}

/** Watch shapes become directional observations after a next-candle range break. */
export function recognizeCandleConfirmations(
  bars: Bar[],
  detect: (bs: Bar[]) => ArchiveMatch[]
): ArchiveMatch[] {
  if (bars.length < 2) return []
  const c = bars.at(-1)!,
    p = bars.at(-2)!
  return detect(bars.slice(0, -1))
    .filter(
      (m) =>
        m.side !== 'NEUTRAL' &&
        (m.side === 'CALL'
          ? c.close > p.high && c.close > c.open
          : c.close < p.low && c.close < c.open)
    )
    .map((m) => ({
      ...m,
      name: `${m.name.replace(/^(Bullish|Bearish)\s+/i, '')} confirmed`,
      pattern: `confirmed-${m.pattern}`,
      confirmed: true,
    }))
}
