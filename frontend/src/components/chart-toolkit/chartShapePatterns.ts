import type { Bar } from './model'

export interface ChartShapeMatch {
  side: 'CALL' | 'PUT'
  /** False only for explicitly requested pre-breakout geometry. */
  confirmed?: boolean
  name: string
  pattern: string
  /** Protective structural extreme; never a forecast or an execution instruction. */
  extreme: number
  entry?: number
  /** Measured projection, not a probability or promise. */
  target?: number
  startTime?: number
  /** Two endpoints of the crossed boundary, in original price/time coordinates. */
  boundary?: Array<{ time: number; price: number }>
  /** Exact observed geometry, stopped at the confirmation candle. */
  structure?: Array<Array<{ time: number; price: number }>>
}
interface Turn {
  i: number
  p: number
  high: boolean
}
interface Line {
  at: (i: number) => number
  slope: number
}

/**
 * Practical, deliberately restrictive OHLC definitions (not image classification):
 * - Strict two-left/two-right pivots, already confirmed BEFORE the breakout candle.
 * - Double/triple turns: alternating equal extremes, tolerance 8% of formation height;
 *   H&S: equal shoulders, a head at least 15% deeper, and a fitted two-touch neckline.
 * - Triangles/wedges/channels/rectangles: three touches on EACH fitted boundary,
 *   residual <= 8% of height, contained closes, at least 16 bars of structure.
 * - Flags/pennants additionally require a preceding directional pole >= 1.5x height,
 *   a consolidation shorter than 4x pole duration, and a retracement <= 65% of pole.
 * - Cup/rounding detection uses the separate smooth-curve fit below; a V is rejected.
 * All matches require the latest close to cross a boundary from an inside prior close.
 * Volume is validated but is not used as proof of a geometric pattern. Prices and
 * timestamps must be positive, chronological and finite. Only last 180 bars are fit.
 */
export function recognizeChartShapes(history: Bar[], includePending = false): ChartShapeMatch[] {
  if (
    history.length < 12 ||
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
    matches: ChartShapeMatch[] = []
  // Reflecting prices makes every bearish definition exactly symmetric.
  for (const bullish of [true, false]) {
    const sign = bullish ? 1 : -1
    const bars = source.map((b) => ({
      high: bullish ? b.high : -b.low,
      low: bullish ? b.low : -b.high,
      close: sign * b.close,
    }))
    const n = bars.length - 1,
      current = bars[n].close,
      previous = bars[n - 1].close
    const turns: Turn[] = []
    for (let i = 2; i + 2 < n; i++) {
      const neighbors = [bars[i - 2], bars[i - 1], bars[i + 1], bars[i + 2]]
      const high = neighbors.every((b) => bars[i].high > b.high)
      const low = neighbors.every((b) => bars[i].low < b.low)
      if (high === low) continue // Ambiguous outside bars never count as two turns.
      const t = { i, p: high ? bars[i].high : bars[i].low, high }
      const last = turns.at(-1)
      if (last && last.high === high) {
        if (high ? t.p > last.p : t.p < last.p) turns[turns.length - 1] = t
      } else if (!last || i - last.i >= 3) turns.push(t)
    }
    const add = (
      bull: string,
      bear: string,
      boundary: (i: number) => number,
      start: number,
      measuredHeight?: number,
      projectedTarget?: number,
      outline?: Array<Array<{ i: number; p: number }>>
    ) => {
      const crossed = previous <= boundary(n - 1) && current > boundary(n)
      if (!crossed && !includePending) return
      // A prior completed close through this boundary invalidates this formation.
      const lastTurn = turns.at(-1)?.i ?? start
      if (bars.slice(lastTurn + 1, n).some((b, j) => b.close > boundary(lastTurn + 1 + j))) return
      const pattern = bullish ? bull : bear
      if (matches.some((m) => m.pattern === pattern && m.side === (bullish ? 'CALL' : 'PUT')))
        return
      const extreme = sign * Math.min(...bars.slice(start, n).map((b) => b.low))
      const height =
        measuredHeight ??
        Math.max(...bars.slice(start, n).map((b) => b.high)) -
          Math.min(...bars.slice(start, n).map((b) => b.low))
      const target = sign * (projectedTarget ?? boundary(n) + height)
      const entry = source[n].close
      if (
        !Number.isFinite(target) ||
        target <= 0 ||
        sign * (target - entry) <= 0 ||
        sign * (entry - extreme) <= 0
      )
        return
      if (!crossed && (bullish ? source[n].low <= extreme : source[n].high >= extreme)) return
      matches.push({
        entry: crossed ? entry : undefined,
        ...(includePending ? { confirmed: crossed } : {}),
        target,
        startTime: source[start].time,
        structure: (
          outline ?? [
            turns.filter((t) => t.i >= start),
            [start, n].map((i) => ({ i, p: boundary(i) })),
          ]
        )
          .filter((line) => line.length >= 2)
          .map((line) =>
            line.map((point) => ({ time: source[point.i].time, price: sign * point.p }))
          ),
        boundary: [start, n].map((i) => ({ time: source[i].time, price: sign * boundary(i) })),
        side: bullish ? 'CALL' : 'PUT',
        pattern,
        name: pattern
          .split('-')
          .map((w) => w[0].toUpperCase() + w.slice(1))
          .join(' '),
        extreme,
      })
    }
    const fitBoundary = (points: Turn[]): Line => {
      const mx = points.reduce((v, p) => v + p.i, 0) / points.length
      const my = points.reduce((v, p) => v + p.p, 0) / points.length
      const slope =
        points.reduce((v, p) => v + (p.i - mx) * (p.p - my), 0) /
        points.reduce((v, p) => v + (p.i - mx) ** 2, 0)
      return { slope, at: (i) => my + slope * (i - mx) }
    }
    for (const count of [5, 3]) {
      const p = turns.slice(-count)
      if (p.length !== count || p[0].high || p.at(-1)!.high || n - p.at(-1)!.i > 16) continue
      const lows = p.filter((x) => !x.high),
        highs = p.filter((x) => x.high)
      const height = Math.max(...highs.map((x) => x.p)) - Math.min(...lows.map((x) => x.p))
      if (height <= Math.abs(current) * 0.003 || p.at(-1)!.i - p[0].i < (count - 1) * 3) continue
      const equal = (values: number[]) => Math.max(...values) - Math.min(...values) <= height * 0.08
      const boundary = highs.length === 1 ? () => highs[0].p : fitBoundary(highs).at
      if (equal(lows.map((x) => x.p)) && equal(highs.map((x) => x.p)))
        add(
          count === 3 ? 'double-bottom' : 'triple-bottom',
          count === 3 ? 'double-top' : 'triple-top',
          boundary,
          p[0].i
        )
      if (
        count === 5 &&
        equal([lows[0].p, lows[2].p]) &&
        lows[1].p < Math.min(lows[0].p, lows[2].p) - height * 0.15 &&
        equal(highs.map((x) => x.p))
      )
        add('inverse-head-and-shoulders', 'head-and-shoulders', boundary, p[0].i)
      if (
        count === 5 &&
        lows[1].p > lows[0].p + height * 0.08 &&
        lows[2].p > lows[1].p + height * 0.08 &&
        highs[1].p > highs[0].p + height * 0.08
      )
        add('three-rising-valleys', 'three-descending-peaks', () => highs[1].p, p[0].i, height)
      if (count === 3) {
        const pole = highs[0].p - lows[0].p
        const retrace = (highs[0].p - lows[1].p) / pole
        const firstDuration = highs[0].i - lows[0].i
        const pullbackDuration = lows[1].i - highs[0].i
        if (
          retrace >= 0.25 &&
          retrace <= 0.65 &&
          pullbackDuration >= firstDuration * 0.5 &&
          pullbackDuration <= firstDuration * 2
        )
          add('measured-move-up', 'measured-move-down', boundary, p[0].i, pole, lows[1].p + pole)
      }
    }
    // Smooth bowls require a confirmed left rim and central trough, >=24 bars,
    // and a pointwise quadratic U fit within 8% of depth (rejects sharp V turns).
    // A handle must be 4..50% of bowl duration and retrace only 8..35% of depth.
    for (const rim of turns.filter((t) => t.high).slice(-6)) {
      for (let end = rim.i + 24; end < n; end++) {
        const span = end - rim.i,
          arc = bars.slice(rim.i, end + 1)
        const bottom = Math.min(...arc.map((b) => b.low)),
          depth = rim.p - bottom
        if (depth <= Math.abs(current) * 0.01 || Math.abs(bars[end].high - rim.p) > depth * 0.08)
          continue
        const trough = turns.find(
          (t) =>
            !t.high &&
            t.i > rim.i + span * 0.4 &&
            t.i < rim.i + span * 0.6 &&
            Math.abs(t.p - bottom) < depth * 0.03
        )
        if (
          !trough ||
          arc.some(
            (b, j) =>
              Math.abs(b.close - (bottom + depth * ((2 * j) / span - 1) ** 2)) > depth * 0.08
          )
        )
          continue
        const boundary = Math.max(rim.p, bars[end].high)
        if (bars.slice(rim.i + 1, n).some((b) => b.close > boundary)) continue
        if (end === n - 1) add('rounding-bottom', 'rounding-top', () => boundary, rim.i)
        const duration = n - 1 - end
        if (duration < 4 || duration > span / 2) continue
        // The right rim and handle low must both be independently confirmed.
        if (!turns.some((t) => t.high && t.i === end)) continue
        const handleLow = turns.find((t) => !t.high && t.i > end && t.i <= n - 3)
        if (!handleLow) continue
        const retrace = boundary - handleLow.p
        if (
          retrace >= depth * 0.08 &&
          retrace <= depth * 0.35 &&
          bars.slice(end + 1, n).every((b) => b.low >= handleLow.p)
        )
          add(
            'cup-and-handle',
            'inverse-cup-and-handle',
            () => boundary,
            rim.i,
            undefined,
            undefined,
            [
              bars.slice(rim.i, n).map((b, j) => ({ i: rim.i + j, p: b.close })),
              [rim.i, n].map((i) => ({ i, p: boundary })),
            ]
          )
      }
    }
    // A scallop is a smooth rising bowl: detrend its unequal rims before fitting
    // a quadratic. Both the depth and the rim rise must be material.
    for (const rim of turns.filter((t) => t.high).slice(-6)) {
      const end = n - 1,
        span = end - rim.i
      if (span < 24 || span > 80) continue
      const rise = bars[end].high - rim.p
      const arc = bars.slice(rim.i, end + 1)
      const detrended = arc.map((b, j) => b.close - (rise * j) / span)
      const bottom = Math.min(...detrended),
        depth = bars[rim.i].close - bottom
      if (depth <= Math.abs(current) * 0.01 || rise < depth * 0.15 || rise > depth * 0.65) continue
      const troughIndex = detrended.indexOf(bottom)
      if (
        troughIndex < span * 0.4 ||
        troughIndex > span * 0.6 ||
        detrended.some(
          (price, j) =>
            Math.abs(price - (bottom + depth * ((2 * j) / span - 1) ** 2)) > depth * 0.08
        )
      )
        continue
      const boundary = bars[end].high
      if (arc.some((b) => b.close > boundary)) continue
      add('ascending-scallop', 'descending-scallop', () => boundary, rim.i, depth)
    }
    // Eight alternating touches must widen first and then contract on both sides.
    // Each half fits independent boundaries, so ordinary triangles do not qualify.
    const diamond = turns.slice(-8)
    if (diamond.length === 8 && n - diamond[7].i <= 12) {
      const dh = diamond.filter((t) => t.high),
        dl = diamond.filter((t) => !t.high)
      const height = Math.max(...dh.map((t) => t.p)) - Math.min(...dl.map((t) => t.p))
      if (
        dh.length === 4 &&
        dl.length === 4 &&
        diamond[7].i - diamond[0].i >= 24 &&
        dh[1].p > dh[0].p + height * 0.1 &&
        dl[1].p < dl[0].p - height * 0.1 &&
        dh[2].p < dh[1].p - height * 0.08 &&
        dh[3].p < dh[2].p - height * 0.08 &&
        dl[2].p > dl[1].p + height * 0.08 &&
        dl[3].p > dl[2].p + height * 0.08
      ) {
        const upper = fitBoundary(dh.slice(-2)),
          lower = fitBoundary(dl.slice(-2))
        const contractionStart = Math.max(dh[1].i, dl[1].i)
        if (
          upper.at(n) > lower.at(n) &&
          bars
            .slice(contractionStart, n)
            .every(
              (b, j) =>
                b.close <= upper.at(contractionStart + j) + height * 0.03 &&
                b.close >= lower.at(contractionStart + j) - height * 0.03
            )
        )
          add('diamond-bottom', 'diamond-top', upper.at, diamond[0].i, height, undefined, [
            dh.slice(0, 2),
            dl.slice(0, 2),
            dh.slice(1),
            dl.slice(1),
          ])
      }
    }
    const p = turns.slice(-6),
      highs = p.filter((t) => t.high),
      lows = p.filter((t) => !t.high)
    if (p.length === 6 && highs.length === 3 && lows.length === 3 && n - p.at(-1)!.i <= 16) {
      const upper = fitBoundary(highs),
        lower = fitBoundary(lows),
        start = p[0].i,
        span = p.at(-1)!.i - start
      const width = upper.at(start) - lower.at(start),
        endWidth = upper.at(n) - lower.at(n)
      const good =
        span >= 16 &&
        width > Math.abs(current) * 0.003 &&
        endWidth > width * 0.12 &&
        p.every((t) => Math.abs(t.p - (t.high ? upper : lower).at(t.i)) <= width * 0.08) &&
        bars
          .slice(start, n)
          .every(
            (b, j) =>
              b.close <= upper.at(start + j) + width * 0.03 &&
              b.close >= lower.at(start + j) - width * 0.03
          )
      if (good) {
        const outline = [upper, lower].map((line) => [start, n].map((i) => ({ i, p: line.at(i) })))
        const u = (upper.slope * span) / width,
          l = (lower.slope * span) / width
        const flatU = Math.abs(u) <= 0.08,
          flatL = Math.abs(l) <= 0.08
        const parallel = Math.abs(u - l) <= 0.08
        const converging = endWidth < width * 0.8
        if (flatU && flatL)
          add('rectangle', 'rectangle', upper.at, start, undefined, undefined, outline)
        else if (parallel && Math.abs(u) > 0.08)
          add('channel', 'channel', upper.at, start, undefined, undefined, outline)
        if (flatU && l > 0.12 && converging)
          add(
            'ascending-triangle',
            'descending-triangle',
            upper.at,
            start,
            undefined,
            undefined,
            outline
          )
        if (flatL && u < -0.12 && converging)
          add(
            'descending-triangle',
            'ascending-triangle',
            upper.at,
            start,
            width,
            undefined,
            outline
          )
        if (u < -0.12 && l > 0.12 && converging)
          add(
            'symmetrical-triangle',
            'symmetrical-triangle',
            upper.at,
            start,
            undefined,
            undefined,
            outline
          )
        if (u < -0.12 && l < -0.04 && u < l - 0.1 && converging)
          add('falling-wedge', 'rising-wedge', upper.at, start, undefined, undefined, outline)
        // The pole must lead directly into the first consolidation high.
        const firstHigh = highs[0].i,
          poleStart = Math.max(0, firstHigh - Math.max(5, Math.ceil(span / 2)))
        const poleLow = Math.min(...bars.slice(poleStart, firstHigh).map((b) => b.low)),
          pole = highs[0].p - poleLow
        const retrace = highs[0].p - Math.min(...lows.map((t) => t.p))
        const poleDuration = firstHigh - poleStart
        if (
          p[0].high &&
          pole >= width * 1.5 &&
          retrace <= pole * 0.65 &&
          span <= poleDuration * 4
        ) {
          const poleLowIndex =
            poleStart + bars.slice(poleStart, firstHigh).findIndex((bar) => bar.low === poleLow)
          const flagOutline = [
            ...outline,
            [
              { i: poleLowIndex, p: poleLow },
              { i: firstHigh, p: highs[0].p },
            ],
          ]
          if (parallel && u < -0.08)
            add('bull-flag', 'bear-flag', upper.at, start, pole, undefined, flagOutline)
          if (u < -0.12 && l > 0.12 && converging)
            add('bull-pennant', 'bear-pennant', upper.at, start, pole, undefined, flagOutline)
        }
      }
    }
  }
  return matches
}
