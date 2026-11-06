import type { BookBar, BookFormation, BookPivot, BookSettings, BookSide } from './types'
import { mean, project, validBar } from './math'
/** All pivot arguments are filtered by recognition time here, even for direct callers. */
export function detectShapes(
  bars: BookBar[],
  i: number,
  s: BookSettings,
  tick: number,
  atr: number,
  input: BookPivot[]
): BookFormation[] {
  if (!Number.isFinite(atr) || atr <= 0 || !bars[i] || !validBar(bars[i]!)) return []
  const pivots = input.filter((p) => p.recognitionIndex < i && p.index < i),
    out: BookFormation[] = [],
    tol = Math.max(s.minToleranceTicks * tick, s.levelToleranceATR * atr)
  const add = (
    id: string,
    name: string,
    side: BookSide,
    ps: BookPivot[],
    photo: number,
    stop: number,
    mode: BookFormation['mode'],
    extra: Partial<BookFormation> = {}
  ) => {
    if (s.disabledPatterns.includes(id)) return
    const points = ps.map((p) => ({
      index: p.index,
      time: p.time,
      price: p.price,
      recognitionTime: p.recognitionTime,
      role: p.side,
    }))
    out.push({
      patternId: id,
      name,
      side,
      sourcePhotos: [photo],
      kind: 'shape',
      mode,
      startIndex: ps[0]!.index,
      endIndex: ps.at(-1)!.index,
      recognitionIndex: Math.max(...ps.map((p) => p.recognitionIndex)),
      shapeWindow: { startIndex: ps[0]!.index, minBars: 0, maxBars: s.shapeMaxBars },
      trigger: ps.at(-2)?.price ?? stop,
      stopAnchor: stop,
      stopMethod: 'Source latest opposite structural extreme',
      targetMethod: 'r-multiple',
      scale: atr,
      contacts: ps.length,
      rank: 2,
      points,
      segments: points
        .slice(1)
        .map((p, j) => ({ from: points[j]!, to: p, role: 'swing-connector' })),
      confirmationRule: 'shape-close',
      notes: [],
      ...extra,
    })
  }
  const ps = pivots.slice(-4),
    highs = ps.filter((p) => p.side === 'high'),
    lows = ps.filter((p) => p.side === 'low')
  if (
    ps.length === 4 &&
    highs.length === 2 &&
    lows.length === 2 &&
    ps.every((p, j) => j === 0 || p.side !== ps[j - 1]!.side)
  ) {
    const [h1, h2] = highs as [BookPivot, BookPivot],
      [l1, l2] = lows as [BookPivot, BookPivot]
    const first = Math.max(h1.index, l1.index),
      last = Math.max(h2.index, l2.index),
      span = last - ps[0]!.index
    const upper = (n: number) => project(h1, h2, n),
      lower = (n: number) => project(l1, l2, n)
    const w0 = upper(first) - lower(first),
      w1 = upper(last) - lower(last),
      wi = upper(i) - lower(i)
    const ratio = w1 / w0,
      converge = ratio < s.convergenceRatio,
      parallel = ratio >= s.convergenceRatio && ratio <= s.parallelMaxRatio
    const upperFlat = Math.abs(h2.price - h1.price) <= tol,
      lowerFlat = Math.abs(l2.price - l1.price) <= tol
    const upperRise = h2.price - h1.price > tol,
      upperFall = h1.price - h2.price > tol,
      lowerRise = l2.price - l1.price > tol,
      lowerFall = l1.price - l2.price > tol
    const inside = bars
      .slice(ps[0]!.index, last + 1)
      .every(
        (b, j) =>
          validBar(b) &&
          b.close <= upper(j + ps[0]!.index) + tol &&
          b.close >= lower(j + ps[0]!.index) - tol
      )
    if (w0 > 0 && w1 > 0 && wi > 0 && inside) {
      const extra: Partial<BookFormation> = {
        upperLine: [h1, h2],
        lowerLine: [l1, l2],
        measuredHeight: Math.max(upper(ps[0]!.index) - lower(ps[0]!.index), w1),
        segments: [
          { from: { ...psPoint(h1) }, to: psPoint(h2), role: 'resistance' },
          { from: psPoint(l1), to: psPoint(l2), role: 'support' },
        ],
      }
      if (span >= s.shapeMinBars && span <= s.shapeMaxBars) {
        if (converge && upperFall && lowerRise) {
          add('symmetrical-triangle', 'Symmetrical triangle', 'long', ps, 10, l2.price, 'neutral', {
            ...extra,
            trigger: upper(i),
          })
          add(
            'symmetrical-triangle',
            'Symmetrical triangle',
            'short',
            ps,
            10,
            h2.price,
            'neutral',
            { ...extra, trigger: lower(i) }
          )
        }
        if (converge && upperFlat && lowerRise)
          add(
            'ascending-triangle',
            'Ascending triangle',
            'long',
            ps,
            12,
            l2.price,
            'continuation',
            {
              ...extra,
              trigger: upper(i),
              targetMethod: 'measured',
              measuredBoundary: upper(i),
              stopMethod: 'Local structural fallback: latest lower pivot',
            }
          )
        if (converge && lowerFlat && upperFall)
          add(
            'descending-triangle',
            'Descending triangle',
            'short',
            ps,
            11,
            h2.price,
            'continuation',
            {
              ...extra,
              trigger: lower(i),
              stopMethod: 'Local structural fallback: latest upper pivot',
            }
          )
        if (parallel && upperFlat && lowerFlat) {
          add('bull-rectangle', 'Bull rectangle', 'long', ps, 16, l2.price, 'continuation', {
            ...extra,
            trigger: upper(i),
            confirmationRule: 'next-boundary',
            targetMethod: 'measured',
            measuredBoundary: upper(i),
            stopMethod: 'Source original breakout candle low',
          })
          add(
            'bear-rectangle',
            'Bear rectangle',
            'short',
            ps,
            15,
            Math.max(h1.price, h2.price),
            'continuation',
            {
              ...extra,
              trigger: lower(i),
              confirmationRule: 'next-boundary',
              targetMethod: 'measured',
              measuredBoundary: lower(i),
              stopMethod: 'Source rectangle resistance (asymmetric)',
            }
          )
        }
        if (converge && upperFall && lowerFall)
          add('falling-wedge', 'Falling wedge', 'long', ps, 18, l2.price, 'reversal', {
            ...extra,
            trigger: upper(i),
          })
        if (converge && upperRise && lowerRise)
          add('rising-wedge', 'Rising wedge', 'short', ps, 19, h2.price, 'reversal', {
            ...extra,
            trigger: lower(i),
          })
      }
      if (
        span >= s.flagMinBars &&
        span <= s.flagMaxBars &&
        i - ps[0]!.index <= s.flagMaxBars &&
        parallel
      ) {
        for (const bull of [true, false]) {
          if (!(bull ? upperFall && lowerFall : upperRise && lowerRise)) continue
          const start = ps[0]!.index,
            poleEnd = bull ? Math.max(h1.price, l1.price) : Math.min(h1.price, l1.price)
          let poleStart: number | undefined
          for (let n = s.poleMinBars; n <= s.poleMaxBars; n++) {
            const b = bars[start - n]
            if (!b || !bars.slice(start - n, start + 1).every(validBar)) continue
            const impulse = bull ? poleEnd - b.close : b.close - poleEnd
            if (impulse >= s.poleMinATR * atr) {
              const retrace = bull
                ? poleEnd - Math.min(l1.price, l2.price)
                : Math.max(h1.price, h2.price) - poleEnd
              if (retrace <= s.flagMaxRetracement * impulse) {
                poleStart = start - n
                break
              }
            }
          }
          if (poleStart !== undefined)
            add(
              bull ? 'bull-flag' : 'bear-flag',
              bull ? 'Bull flag' : 'Bear flag',
              bull ? 'long' : 'short',
              ps,
              bull ? 13 : 17,
              bull ? Math.min(l1.price, l2.price) : Math.max(h1.price, h2.price),
              'continuation',
              {
                ...extra,
                startIndex: poleStart,
                shapeWindow: { startIndex: start, minBars: s.flagMinBars, maxBars: s.flagMaxBars },
                trigger: bull ? upper(i) : lower(i),
                confirmationRule: bull ? 'shape-close' : 'next-boundary',
                stopMethod: 'Source complete corrective flag extreme',
              }
            )
        }
      }
    }
  }
  const spacing = (p: BookPivot[], side: 'high' | 'low') => {
    const outer = p.filter((x) => x.side === side)
    return outer
      .slice(1)
      .every(
        (x, j) =>
          x.index - outer[j]!.index >= s.multiSwingMinBars &&
          x.index - outer[j]!.index <= s.multiSwingMaxBars
      )
  }
  for (const bottom of [true, false]) {
    const side = bottom ? 'low' : 'high',
      direction = bottom ? 'long' : 'short'
    const three = pivots.slice(-3)
    if (
      three.length === 3 &&
      three[0]!.side === side &&
      three[1]!.side !== side &&
      three[2]!.side === side &&
      spacing(three, side)
    ) {
      const [a, m, b] = three as [BookPivot, BookPivot, BookPivot]
      if (
        Math.abs(a.price - b.price) <= tol &&
        (bottom ? m.price - Math.max(a.price, b.price) : Math.min(a.price, b.price) - m.price) >=
          s.reboundATR * atr
      )
        add(
          bottom ? 'double-bottom' : 'double-top',
          bottom ? 'Double bottom' : 'Double top',
          direction,
          three,
          bottom ? 24 : 25,
          b.price,
          'reversal',
          {
            trigger: m.price,
            targetMethod: 'support-resistance',
            segments: [
              ...three.slice(1).map((p, j) => ({
                from: psPoint(three[j]!),
                to: psPoint(p),
                role: 'swing-connector',
              })),
              {
                from: psPoint(m),
                to: { ...psPoint(m), index: i, time: bars[i]!.time },
                role: 'neckline',
              },
            ],
          }
        )
    }
    const five = pivots.slice(-5)
    if (
      five.length !== 5 ||
      five.some((p, j) => p.side !== (j % 2 === 0 ? side : bottom ? 'high' : 'low')) ||
      !spacing(five, side)
    )
      continue
    const [a, n1, h, n2, c] = five as [BookPivot, BookPivot, BookPivot, BookPivot, BookPivot]
    const extremes = [a.price, h.price, c.price],
      equal = Math.max(...extremes) - Math.min(...extremes) <= tol
    const rebound = bottom
      ? Math.min(n1.price - Math.max(a.price, h.price), n2.price - Math.max(h.price, c.price))
      : Math.min(Math.min(a.price, h.price) - n1.price, Math.min(h.price, c.price) - n2.price)
    if (equal && rebound >= s.reboundATR * atr)
      add(
        bottom ? 'triple-bottom' : 'triple-top',
        bottom ? 'Triple bottom' : 'Triple top',
        direction,
        five,
        bottom ? 22 : 23,
        c.price,
        'reversal',
        {
          trigger: bottom ? Math.max(n1.price, n2.price) : Math.min(n1.price, n2.price),
          stopMethod: 'Conservative local final-extreme anchor',
        }
      )
    const depth = bottom
      ? Math.min(a.price, c.price) - h.price
      : h.price - Math.max(a.price, c.price)
    if (
      depth >= s.headDepthATR * atr &&
      Math.abs(a.price - c.price) <= s.shoulderToleranceATR * atr
    )
      add(
        bottom ? 'inverse-head-shoulders' : 'head-shoulders',
        bottom ? 'Inverse head and shoulders' : 'Head and shoulders',
        direction,
        five,
        bottom ? 20 : 21,
        c.price,
        'reversal',
        {
          trigger: project(n1, n2, i),
          line: [n1, n2],
          stopMethod: 'Source right shoulder',
          segments: [
            ...five.slice(1).map((p, j) => ({
              from: psPoint(five[j]!),
              to: psPoint(p),
              role: 'swing-connector',
            })),
            { from: psPoint(n1), to: psPoint(n2), role: 'neckline' },
          ],
        }
      )
  }
  // A cup has its own duration contract; never collapse it into a three-pivot V bottom.
  const cup = pivots.slice(-4)
  if (cup.length === 4 && cup.map((p) => p.side).join(',') === 'high,low,high,low') {
    const [left, bottom, right] = cup as [BookPivot, BookPivot, BookPivot, BookPivot]
    const geometry = cupGeometry(bars, i, s, atr, left, bottom, right)
    if (geometry)
      add('cup-handle', 'Cup and handle', 'long', cup, 14, geometry.stopAnchor, 'continuation', {
        ...geometry,
        shapeWindow: {
          startIndex: right.index,
          minBars: s.handleMinBars,
          maxBars: s.handleMaxBars,
        },
        stopMethod: 'Source complete received handle low',
        notes: ['Rounded U uses seven bucket means of five-bar-smoothed closes; rejects V bases.'],
      })
  }
  return out
}
function psPoint(p: BookPivot) {
  return {
    index: p.index,
    time: p.time,
    price: p.price,
    recognitionTime: p.recognitionTime,
    role: p.side,
  }
}

/** Cup anchors are confirmed, while every already received handle candle still changes resistance/stop until breakout. */
function cupGeometry(
  bars: BookBar[],
  i: number,
  s: BookSettings,
  atr: number,
  left: Pick<BookPivot, 'index' | 'price'>,
  bottom: Pick<BookPivot, 'index' | 'price'>,
  right: Pick<BookPivot, 'index' | 'price'>
): Pick<BookFormation, 'trigger' | 'stopAnchor'> | undefined {
  const duration = right.index - left.index,
    handleDuration = i - right.index
  const rim = Math.max(left.price, right.price),
    depth = rim - bottom.price
  const handle = bars.slice(right.index, i)
  if (
    duration < s.cupMinBars ||
    duration > s.cupMaxBars ||
    handleDuration < s.handleMinBars ||
    handleDuration > s.handleMaxBars ||
    Math.abs(left.price - right.price) > s.rimToleranceATR * atr ||
    depth < s.cupMinDepthATR * atr ||
    depth > s.cupMaxDepthFraction * rim ||
    !handle.length ||
    !handle.every((b) => validBar(b) && b.low >= rim - depth * s.handleMaxDepthFraction)
  )
    return undefined
  const rows = bars.slice(left.index, right.index + 1)
  if (!rows.every(validBar)) return undefined
  const smooth = rows.map((_, j) =>
    mean(rows.slice(Math.max(0, j - 2), Math.min(rows.length, j + 3)).map((b) => b.close))
  )
  const buckets = Array.from({ length: 7 }, (_, k) =>
    mean(smooth.slice(Math.floor((k * rows.length) / 7), Math.floor(((k + 1) * rows.length) / 7)))
  )
  const rounded =
    buckets[0]! > buckets[1]! &&
    buckets[1]! > buckets[2]! &&
    buckets[2]! > buckets[3]! &&
    buckets[3]! < buckets[4]! &&
    buckets[4]! < buckets[5]! &&
    buckets[5]! < buckets[6]!
  if (!rounded || rows.filter((b) => b.low <= bottom.price + 0.15 * depth).length < 3)
    return undefined
  return {
    trigger: Math.max(rim, ...handle.map((b) => b.high)),
    stopAnchor: Math.min(...handle.map((b) => b.low)),
  }
}
/** Revalidate using only candles preceding the prospective breakout; no candidate may outlive newer geometry. */
export function revalidateBookShape(
  formation: BookFormation,
  bars: BookBar[],
  i: number,
  s: BookSettings,
  tick: number,
  pivots: BookPivot[]
): BookFormation | undefined {
  const window = formation.shapeWindow
  if (window && (i - window.startIndex < window.minBars || i - window.startIndex > window.maxBars))
    return undefined
  if (formation.patternId === 'cup-handle') {
    const anchors = formation.points.filter((p) => p.role === 'high' || p.role === 'low')
    if (anchors.length < 4) return undefined
    const geometry = cupGeometry(bars, i, s, formation.scale, anchors[0]!, anchors[1]!, anchors[2]!)
    return geometry ? { ...formation, ...geometry } : undefined
  }
  const current = detectShapes(bars, i, s, tick, formation.scale, pivots).find(
    (f) =>
      f.patternId === formation.patternId &&
      f.side === formation.side &&
      f.startIndex === formation.startIndex &&
      f.endIndex === formation.endIndex &&
      f.recognitionIndex === formation.recognitionIndex
  )
  if (!current) return undefined
  if (current.upperLine && current.lowerLine) {
    const tolerance = Math.max(s.minToleranceTicks * tick, s.levelToleranceATR * formation.scale)
    if (
      !bars
        .slice(current.endIndex + 1, i)
        .every(
          (b, j) =>
            validBar(b) &&
            b.close <= project(...current.upperLine!, current.endIndex + 1 + j) + tolerance &&
            b.close >= project(...current.lowerLine!, current.endIndex + 1 + j) - tolerance
        )
    )
      return undefined
  }
  if (current.patternId === 'bull-flag' || current.patternId === 'bear-flag') {
    const start = current.shapeWindow!.startIndex,
      channel = bars.slice(start, i),
      long = current.side === 'long'
    const stopAnchor = long
      ? Math.min(...channel.map((b) => b.low))
      : Math.max(...channel.map((b) => b.high))
    const firstHigh = current.points.find((p) => p.role === 'high')!,
      firstLow = current.points.find((p) => p.role === 'low')!
    const poleEnd = long
      ? Math.max(firstHigh.price, firstLow.price)
      : Math.min(firstHigh.price, firstLow.price)
    const impulse = long
      ? poleEnd - bars[current.startIndex]!.close
      : bars[current.startIndex]!.close - poleEnd
    const retracement = long ? poleEnd - stopAnchor : stopAnchor - poleEnd
    if (!channel.every(validBar) || retracement > s.flagMaxRetracement * impulse) return undefined
    return { ...current, stopAnchor }
  }
  return current
}
