import type { Bar } from './model'

export interface InstitutionalPattern {
  side: 'CALL' | 'PUT' | 'NEUTRAL'
  name: string
  pattern: string
  extreme: number
}
type Pivot = { index: number; price: number; kind: 'high' | 'low' }

/** Archive 09 is a schematic, not a numerical specification. These are explicitly
 * operational variants: strict two-left/two-right pivots; a closing structure
 * break; an actual level touch and directional closing rejection on the last bar.
 * Quick means <=6 bars after the break; late means >6. Re-entry is the second
 * separated shoulder visit, after a first visit rejected on the broken side.
 * Squeeze requires three nested pre-retest ranges with rising lows; continuation
 * requires two descending prior swing highs/lows and a head below the prior high
 * (all geometry mirrors for CALL).
 * No volume, profitability, institutional-order-flow or proprietary-rule claims.
 * Caller must pass completed bars only. All calculations use this prefix alone.
 *
 * Wolfe geometry follows Bill & Brian Wolfe's five-point, converging-boundary
 * description, with a stricter operational fifth-point overshoot and first close
 * back inside on the bar that confirms that pivot. No Fibonacci ratios are used.
 * Author-written source (mirrored PDF), pages 5–6:
 * https://funwiththinkscript.com/wp-content/uploads/2017/03/seeingTheFuture.pdf
 */
export const INSTITUTIONAL_PATTERN_CATALOG = [
  ...[
    ['QM Quick Retest', 'institutional_qm_quick_retest'],
    ['QM Late Retest', 'institutional_qm_late_retest'],
    ['QM Re-entry', 'institutional_qm_reentry'],
    ['QM Squeeze', 'institutional_qm_squeeze'],
    ['Continuation QM', 'institutional_qm_continuation'],
    ['Wolfe Wave', 'institutional_wolfe_wave'],
  ].map(([name, pattern]) => ({
    name,
    pattern,
    status: 'operational' as const,
    reason: 'Explicit local geometry; not a claim to reproduce proprietary rules.',
  })),
  ...[
    ['RX / S Takeout', 'institutional_liquidity_sweep'],
    ['Fakeout V1 (Default)', 'institutional_liquidity_sweep'],
    ['Fakeout V2 (S/R Flip)', 'institutional_sr_flip'],
    ['Fakeout V3 (Diamond)', 'institutional_diamond_breakout'],
    ['Fakeout V4 (Diamond S/R)', 'institutional_diamond_breakout'],
    ['Double S/R', 'institutional_repeated_level_breakout'],
    ['Compression (CP)', 'institutional_compression_breakout'],
    ['Compression Short', 'institutional_compression_breakout'],
    ['3 Drive', 'institutional_three_drive'],
    ['Cash Can', 'institutional_compressed_range_breakout'],
    ['Cash Can + Fakeout', 'institutional_liquidity_sweep'],
    ['Flag S', 'institutional_flag_limit_retest'],
    ['Flag', 'institutional_flag_limit_retest'],
    ['Flag A + Flag S', 'institutional_flag_limit_retest'],
    ['Competition (CP)', 'institutional_compression_breakout'],
    ['Competition Liquidity (CP/LQ)', 'institutional_compression_breakout'],
  ].map(([name, pattern]) => ({
    name,
    pattern,
    status: 'partial-operational' as const,
    reason:
      'Generic visible geometry only; proprietary variant details and combinations are not inferred from the sketch.',
  })),
  ...['Inverted QM / EQM / QMTM', 'Baker (Pentabar)', 'V Twin', 'MPS'].map((name) => ({
    name,
    pattern: null,
    status: 'unsupported' as const,
    reason:
      'Sketch lacks sufficient unambiguous rules to distinguish this named variant. Generic structural families remain available.',
  })),
]

function pivots(bars: Bar[]): Pivot[] {
  const result: Pivot[] = []
  for (let i = 2; i < bars.length - 2; i++) {
    const neighbors = [bars[i - 2], bars[i - 1], bars[i + 1], bars[i + 2]]
    const high = neighbors.every((b) => bars[i].high > b.high)
    const low = neighbors.every((b) => bars[i].low < b.low)
    // An outside bar can be both extrema; its intrabar order is unknowable.
    if (high === low) continue
    const p: Pivot = {
      index: i,
      price: high ? bars[i].high : bars[i].low,
      kind: high ? 'high' : 'low',
    }
    const prior = result.at(-1)
    if (prior?.kind === p.kind) {
      if (p.kind === 'high' ? p.price > prior.price : p.price < prior.price)
        result[result.length - 1] = p
    } else result.push(p)
  }
  return result
}
const line = (a: Pivot, b: Pivot, index: number) =>
  a.price + ((b.price - a.price) * (index - a.index)) / (b.index - a.index)

/** Generic archive-09 families. Equal-level tolerance is one quarter of the
 * mean candle range in the structure, an explicit local operational choice.
 * Compression uses six alternating, monotonically contracting extrema; a
 * diamond first expands for two legs, then contracts for two legs. Three-drive
 * exhaustion requires three higher highs with diminishing advances, higher
 * intervening lows and a latest close below the last intervening low.
 */
function genericFamilies(
  bars: Bar[],
  ps: Pivot[],
  emit: (pattern: string, name: string, extreme: number) => void
): void {
  const n = bars.length - 1,
    last = bars[n],
    previous = bars[n - 1]
  const confirmed = ps.filter((p) => p.index + 2 < n)
  const highs = confirmed.filter((p) => p.kind === 'high'),
    lows = confirmed.filter((p) => p.kind === 'low')
  const tolerance = (from: number) =>
    bars.slice(from, n).reduce((sum, b) => sum + b.high - b.low, 0) / (n - from) / 4
  const clustered = (points: Pivot[]) =>
    Math.max(...points.map((p) => p.price)) - Math.min(...points.map((p) => p.price)) <=
    tolerance(points[0].index)
  const firstBreak = (boundary: (index: number) => number, from: number) =>
    last.close < boundary(n) &&
    previous.close >= boundary(n - 1) &&
    bars.slice(from, n).every((b, j) => b.close >= boundary(from + j))
  const hs = highs.slice(-2)
  if (
    hs.length === 2 &&
    clustered(hs) &&
    last.high > Math.max(...hs.map((p) => p.price)) &&
    last.close < Math.min(...hs.map((p) => p.price)) &&
    bars.slice(hs[1].index + 1, n).every((b) => b.high <= Math.max(...hs.map((p) => p.price)))
  ) {
    emit('institutional_liquidity_sweep', 'Resistance sweep rejection', last.high)
  }
  const ls = lows.slice(-3)
  if (ls.length === 3 && clustered(ls)) {
    const support = Math.min(...ls.map((p) => p.price))
    if (firstBreak(() => support, ls[0].index + 1))
      emit(
        'institutional_repeated_level_breakout',
        'Repeated support break',
        Math.max(...bars.slice(ls[0].index).map((b) => b.high))
      )
  }
  const six = confirmed.slice(-6)
  if (six.length === 6 && six[0].kind === 'high') {
    const [a, b, c, d, e, f] = six
    const fallingHighs = a.price > c.price && c.price > e.price
    const risingLows = b.price < d.price && d.price < f.price
    const bottom = (i: number) => line(d, f, i)
    if (
      fallingHighs &&
      risingLows &&
      bottom(n) < line(c, e, n) &&
      firstBreak(bottom, f.index + 1)
    ) {
      emit('institutional_compression_breakout', 'Compression breakout', e.price)
    }
    if (clustered([a, c, e]) && risingLows && firstBreak(() => b.price, b.index + 1)) {
      emit(
        'institutional_compressed_range_breakout',
        'Compressed range breakout',
        Math.max(a.price, c.price, e.price)
      )
    }
  }
  const five = confirmed.slice(-5)
  if (five.length === 5 && five[0].kind === 'high') {
    const [a, b, c, d, e] = five
    if (
      a.price < c.price &&
      c.price < e.price &&
      e.price - c.price < c.price - a.price &&
      d.price > b.price &&
      firstBreak(() => d.price, e.index + 1)
    ) {
      emit('institutional_three_drive', 'Three-drive reversal break', e.price)
    }
  }
  const eight = confirmed.slice(-8)
  if (eight.length === 8 && eight[0].kind === 'high') {
    const [a, b, c, d, e, f, g, h] = eight
    const bottom = (i: number) => line(f, h, i)
    if (
      c.price > a.price &&
      d.price < b.price &&
      e.price < c.price &&
      g.price < e.price &&
      f.price > d.price &&
      h.price > f.price &&
      bottom(n) < line(e, g, n) &&
      firstBreak(bottom, h.index + 1)
    ) {
      emit('institutional_diamond_breakout', 'Expanding-contracting range breakout', c.price)
    }
  }
  for (let i = 0; i <= confirmed.length - 6; i++) {
    const [impulseHigh, impulseLow, a, b, c, d] = confirmed.slice(i, i + 6)
    if (
      impulseHigh.kind !== 'high' ||
      impulseHigh.price <= c.price ||
      impulseLow.price >= b.price ||
      c.price <= a.price ||
      d.price <= b.price ||
      last.high < a.price ||
      last.high >= c.price ||
      last.close >= a.price
    )
      continue
    const broken = bars.findIndex((bar, j) => j > d.index + 2 && j < n && bar.close < d.price)
    if (broken < 0 || bars.slice(broken + 1, n).some((bar) => bar.high >= a.price)) continue
    emit('institutional_flag_limit_retest', 'Flag supply retest after structure break', c.price)
  }
}

export function recognizeInstitutionalPatterns(history: Bar[]): InstitutionalPattern[] {
  if (
    history.length < 7 ||
    history.some(
      (b, i) =>
        ![b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) ||
        b.high <= b.low ||
        b.high < Math.max(b.open, b.close) ||
        b.low > Math.min(b.open, b.close) ||
        (i > 0 && b.time <= history[i - 1].time)
    )
  )
    return []
  const found: InstitutionalPattern[] = []
  for (const side of ['PUT', 'CALL'] as const) {
    const sign = side === 'PUT' ? 1 : -1
    const bars = history.map((b) =>
      sign === 1 ? b : { ...b, open: -b.open, high: -b.low, low: -b.high, close: -b.close }
    )
    const ps = pivots(bars),
      n = bars.length - 1,
      last = bars[n]
    const emit = (pattern: string, name: string, extreme: number) => {
      if (!found.some((p) => p.pattern === pattern && p.side === side)) {
        found.push({ side, pattern, name, extreme: extreme * sign })
      }
    }
    if (last.close >= last.open) continue
    genericFamilies(bars, ps, emit)
    // Generic confirmed swing support becomes resistance after its first close below.
    for (const p of ps.filter((p) => p.kind === 'low')) {
      const broken = bars.findIndex((b, i) => i >= p.index + 3 && i < n && b.close < p.price)
      if (broken < 0 || last.high < p.price || last.close >= p.price) continue
      if (bars.slice(broken + 1, n).some((b) => b.high >= p.price)) continue
      emit('institutional_sr_flip', 'S/R flip rejection (operational)', last.high)
      emit(
        'institutional_swing_retest',
        side === 'PUT'
          ? 'Swing support break / resistance retest'
          : 'Swing resistance break / support retest',
        last.high
      )
    }
    for (let i = 0; i <= ps.length - 4; i++) {
      const [a, b, c, d] = ps.slice(i, i + 4)
      if (
        a.kind !== 'high' ||
        b.kind !== 'low' ||
        c.kind !== 'high' ||
        d.kind !== 'low' ||
        c.price <= a.price ||
        d.price >= b.price ||
        d.index + 2 >= n
      )
        continue
      const broken = bars.findIndex((bar, j) => j > c.index && j <= d.index && bar.close < b.price)
      if (
        broken < 0 ||
        last.high < a.price ||
        last.close >= a.price ||
        bars.slice(c.index + 1).some((bar) => bar.high >= c.price)
      )
        continue
      const visits = bars.slice(broken + 1, n)
      if (visits.some((bar) => bar.close >= a.price)) continue
      let clusters = 0,
        touching = false
      for (const bar of visits) {
        if (bar.high >= a.price) {
          if (!touching) clusters++
          touching = true
        } else touching = false
      }
      if (touching) continue // same visit has not separated for a re-entry
      if (clusters === 0) {
        emit('institutional_qm_retest', 'Quasimodo shoulder rejection (operational)', c.price)
        const approach = bars.slice(n - 3, n)
        if (
          approach.length === 3 &&
          n - 3 > d.index &&
          approach[0].high >= approach[1].high &&
          approach[1].high >= approach[2].high &&
          approach[0].low < approach[1].low &&
          approach[1].low < approach[2].low
        ) {
          emit(
            'institutional_qm_squeeze',
            'QM nested-range squeeze rejection (operational)',
            c.price
          )
        }
        const prior = ps.slice(Math.max(0, i - 4), i)
        if (
          prior.length === 4 &&
          prior[0].kind === 'high' &&
          prior[1].kind === 'low' &&
          prior[2].kind === 'high' &&
          prior[3].kind === 'low' &&
          prior[2].price < prior[0].price &&
          prior[3].price < prior[1].price &&
          c.price < prior[2].price
        ) {
          emit(
            'institutional_qm_continuation',
            'QM prior-trend continuation rejection (operational)',
            c.price
          )
        }
        const quick = n - broken <= 6
        emit(
          quick ? 'institutional_qm_quick_retest' : 'institutional_qm_late_retest',
          `QM ${quick ? 'quick' : 'late'} retest (operational)`,
          c.price
        )
      } else if (clusters === 1) {
        emit(
          'institutional_qm_reentry',
          'QM second shoulder rejection (operational re-entry)',
          c.price
        )
      }
    }
    // Five alternating extrema, not a triangle carrying a Wolfe label.
    const wave = ps.slice(-5)
    if (wave.length !== 5) continue
    const [a, b, c, d, e] = wave
    if (
      a.kind !== 'high' ||
      b.kind !== 'low' ||
      c.kind !== 'high' ||
      d.kind !== 'low' ||
      e.kind !== 'high' ||
      e.index !== n - 2 ||
      c.price <= a.price ||
      d.price <= b.price ||
      d.price >= a.price
    )
      continue
    const outerSlope = (c.price - a.price) / (c.index - a.index)
    const innerSlope = (d.price - b.price) / (d.index - b.index)
    const gap = line(a, c, e.index) - line(b, d, e.index)
    if (innerSlope <= outerSlope || gap <= 0 || e.price <= line(a, c, e.index)) continue
    if (
      bars[e.index].close < line(a, c, e.index) ||
      bars[n - 1].close < line(a, c, n - 1) ||
      last.high < line(a, c, n) ||
      last.close >= line(a, c, n)
    )
      continue
    emit('institutional_wolfe_wave', 'Wolfe Wave five-pivot reclaim (operational)', e.price)
  }
  return found
}
