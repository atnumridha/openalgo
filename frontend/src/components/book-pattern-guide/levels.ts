import type { BookPivot, BookLevel, BookSettings, BookFormation, BookBar } from './types'
import { median, project } from './math'
export function buildLevels(
  pivots: BookPivot[],
  index: number,
  atr: number,
  tick: number,
  s: BookSettings
): BookLevel[] {
  const tol = Math.max(s.minToleranceTicks * tick, s.levelToleranceATR * atr),
    out: BookLevel[] = []
  for (const side of ['high', 'low'] as const) {
    const clusters: BookPivot[][] = []
    for (const p of pivots.filter(
      (p) => p.side === side && p.index >= index - s.levelLookback && p.recognitionIndex < index
    )) {
      const c = clusters.find(
        (c) =>
          Math.abs(median(c.map((x) => x.price)) - p.price) <= tol &&
          c.every((x) => Math.abs(x.price - p.price) <= tol)
      )
      if (c) {
        if (p.index - c.at(-1)!.index >= s.pivotSpacing) c.push(p)
      } else clusters.push([p])
    }
    for (const c of clusters.filter((c) => c.length >= 2)) {
      const last = c.at(-1)!
      out.push({
        id: `${side}:${c.map((p) => p.index).join('-')}`,
        side: side === 'high' ? 'resistance' : 'support',
        price: median(c.map((p) => p.price)),
        contacts: c,
        recognitionTime: last.recognitionTime,
        recognitionIndex: last.recognitionIndex,
      })
    }
  }
  return out
}
export function detectLevelBreaks(
  bars: BookBar[],
  i: number,
  s: BookSettings,
  tick: number,
  atr: number,
  levels: BookLevel[],
  pivots: BookPivot[]
): BookFormation[] {
  const b = bars[i]!,
    prev = bars[i - 1],
    out: BookFormation[] = []
  const points = (ps: BookPivot[]) =>
    ps.map((p) => ({
      time: p.time,
      price: p.price,
      index: p.index,
      role: p.side,
      recognitionTime: p.recognitionTime,
    }))
  for (const level of levels) {
    const long = level.side === 'resistance',
      side = long ? 'long' : 'short'
    if (
      !(long
        ? b.close > b.open &&
          b.close >= level.price + tick &&
          !!prev &&
          prev.close < level.price + tick
        : b.close < b.open &&
          b.close <= level.price - tick &&
          !!prev &&
          prev.close > level.price - tick)
    )
      continue
    const p = points(level.contacts)
    out.push({
      patternId: `sr-${side}`,
      name: long ? 'Resistance breakout' : 'Support breakdown',
      side,
      sourcePhotos: [48, 49],
      kind: 'level',
      mode: 'neutral',
      startIndex: level.contacts[0]!.index,
      endIndex: i,
      recognitionIndex: i,
      trigger: long ? b.high : b.low,
      stopAnchor: long ? b.low : b.high,
      stopMethod: 'Source original breakout candle extreme',
      targetMethod: 'support-resistance',
      scale: atr,
      contacts: level.contacts.length,
      rank: 0,
      points: p,
      segments: [
        {
          from: p[0]!,
          to: { time: b.time, index: i, price: level.price, role: 'level' },
          role: 'horizontal-level',
        },
      ],
      confirmationRule: 'next-extreme',
      measuredBoundary: level.price,
      notes: ['Photo 49: only the very next observed closed candle may confirm.'],
    })
  }
  for (const high of [true, false]) {
    const ps = pivots
      .filter((p) => p.side === (high ? 'high' : 'low') && p.recognitionIndex < i)
      .slice(-2)
    if (ps.length !== 2) continue
    const [a, c] = ps as [BookPivot, BookPivot]
    // Descending resistance breaks long; ascending support breaks short.
    if (c.index - a.index < s.pivotSpacing || (high ? c.price >= a.price : c.price <= a.price))
      continue
    const boundary = project(a, c, i),
      previous = project(a, c, i - 1)
    if (
      !(high
        ? b.close >= boundary + tick && !!prev && prev.close < previous + tick
        : b.close <= boundary - tick && !!prev && prev.close > previous - tick)
    )
      continue
    const p = points(ps),
      side = high ? 'long' : 'short'
    out.push({
      patternId: `trendline-${side}`,
      name: high ? 'Descending trendline break/retest' : 'Rising trendline break/retest',
      side,
      sourcePhotos: [50, 51, 52],
      kind: 'trendline',
      mode: 'reversal',
      startIndex: a.index,
      endIndex: i,
      recognitionIndex: i,
      trigger: boundary,
      stopAnchor: high ? b.low : b.high,
      stopMethod: 'Local retest candle opposite extreme',
      targetMethod: 'r-multiple',
      scale: atr,
      contacts: 2,
      rank: 1,
      points: p,
      segments: [{ from: p[0]!, to: p[1]!, role: 'trendline' }],
      confirmationRule: 'retest',
      line: [a, c],
      notes: ['Frozen at break; retest must occur on a later candle.'],
    })
  }
  return out.filter((f) => !s.disabledPatterns.includes(f.patternId))
}
