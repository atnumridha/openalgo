import type {
  BookAlert,
  BookBar,
  BookContext,
  BookEvent,
  BookFilterState,
  BookFormation,
  BookGuideResult,
  BookIndicatorSnapshot,
  BookLevel,
  BookObservation,
  BookPlan,
  BookPivot,
  BookSegment,
  BookSettings,
  BookSide,
} from './types'
import { resolveBookSettings } from './settings'
import {
  confirmedPivots,
  direction,
  finite,
  indicators,
  project,
  tickRound,
  validBar,
} from './math'
import { detectCandles } from './candles'
import { detectShapes, revalidateBookShape } from './shapes'
import { buildLevels, detectLevelBreaks } from './levels'
import { calculateBookRisk } from './risk'
export type * from './types'
export { DEFAULT_BOOK_SETTINGS, resolveBookSettings } from './settings'
export { calculateBookRisk } from './risk'

/** Visibility follows the formation family, never its later confirmed direction. */
export function bookOrdinaryEventVisible(
  event: Pick<BookEvent, 'rank'>,
  showNeutral: boolean
): boolean {
  return showNeutral || event.rank !== 4
}

/** Display context only, using a bounded suffix of already confirmed pivots. */
export function bookContextTrendLines(
  pivots: BookPivot[],
  end: BookBar | undefined,
  index: number
): BookSegment[] {
  if (!end || !validBar(end)) return []
  const highs: BookPivot[] = [],
    lows: BookPivot[] = []
  for (let j = pivots.length - 1; j >= 0 && (highs.length < 2 || lows.length < 2); j--) {
    const p = pivots[j],
      side = p.side === 'high' ? highs : lows
    if (side.length < 2 && p.recognitionIndex <= index) side.unshift(p)
  }
  const lines: BookSegment[] = []
  for (const [points, role] of [
    [lows, 'Support trend'],
    [highs, 'Resistance trend'],
  ] as const) {
    if (points.length !== 2) continue
    const [a, b] = points
    if (
      b.index - a.index < 3 ||
      (role === 'Support trend' ? b.price <= a.price : b.price >= a.price)
    )
      continue
    const value = project(a, b, index)
    if (!finite(value) || value <= 0) continue
    lines.push({
      role,
      from: {
        index: a.index,
        time: a.time,
        price: a.price,
        role,
        recognitionTime: a.recognitionTime,
      },
      to: { index, time: end.time, price: value, role, recognitionTime: b.recognitionTime },
    })
  }
  return lines
}

export function bookFilterStates(
  b: BookBar | undefined,
  s: BookSettings,
  x: BookIndicatorSnapshot,
  side: BookSide
): BookFilterState[] {
  const long = side === 'long'
  return [
    {
      name: 'rsi',
      state: !s.rsiFilter
        ? 'off'
        : !finite(x.rsi)
          ? 'unavailable'
          : (long ? x.rsi > 50 : x.rsi < 50)
            ? 'pass'
            : 'fail',
      value: x.rsi,
    },
    {
      name: 'macd',
      state: !s.macdFilter
        ? 'off'
        : !finite(x.macd) || !finite(x.macdSignal)
          ? 'unavailable'
          : (long ? x.macd > x.macdSignal : x.macd < x.macdSignal)
            ? 'pass'
            : 'fail',
      value: x.macd,
      baseline: x.macdSignal,
    },
    {
      name: 'volume',
      state: !s.volumeFilter
        ? 'off'
        : !b || !finite(b.volume) || b.volume <= 0 || !finite(x.volumeMean)
          ? 'unavailable'
          : b.volume >= s.volumeExpansion * x.volumeMean
            ? 'pass'
            : 'fail',
      value: b?.volume,
      baseline: x.volumeMean,
    },
  ]
}
export function qualifyBookEvent(
  e: BookEvent,
  b: BookBar,
  index: number,
  c: BookContext,
  s: BookSettings,
  levels: BookLevel[],
  snapshot: BookIndicatorSnapshot
): { plan?: BookPlan; reason: string } {
  if (!validBar(b) || !finite(c.tickSize) || c.tickSize <= 0)
    return { reason: 'WAIT: valid completed candle and tick size are required' }
  if (e.side === 'neutral') return { reason: 'WAIT: direction is not confirmed' }
  const long = e.side === 'long',
    desired = long ? 'bull' : 'bear',
    opposite = long ? 'bear' : 'bull'
  const prior = e.priorTrend ?? 'unavailable'
  if (e.mode === 'reversal' && prior !== opposite)
    return { reason: `WAIT: preceding ${opposite} reversal context is ${prior}` }
  if (
    e.mode === 'continuation' &&
    (prior !== desired ||
      !finite(snapshot.maFast) ||
      (long ? b.close <= snapshot.maFast : b.close >= snapshot.maFast))
  )
    return {
      reason: `WAIT: continuation requires preceding ${desired} trend and close beyond current MA${s.maFast}`,
    }
  if (e.mode === 'neutral' && snapshot.trend !== desired)
    return { reason: `WAIT: local breakout requires current ${desired} trend (${snapshot.trend})` }
  const filters = bookFilterStates(b, s, snapshot, e.side),
    failed = filters.find((f) => f.state === 'fail' || f.state === 'unavailable')
  if (failed) return { reason: `WAIT: ${failed.name} filter ${failed.state}` }
  const buffer = Math.max(c.tickSize, s.stopBufferATR * e.scale)
  const stop = tickRound(e.stopAnchor + (long ? -buffer : buffer), c.tickSize, !long),
    entry = b.close,
    distance = long ? entry - stop : stop - entry
  if (!finite(distance) || distance <= 0 || stop <= 0)
    return { reason: 'WAIT: supported stop is on the wrong side of entry' }
  if (long ? b.low <= stop : b.high >= stop)
    return {
      reason:
        'WAIT: confirmation candle already breaches the buffered stop; intrabar order is unknown',
    }
  let method = e.targetMethod,
    target: number
  if (method === 'measured') {
    if (!finite(e.measuredBoundary) || !finite(e.measuredHeight) || e.measuredHeight <= 0)
      return { reason: 'WAIT: measured target geometry is unavailable' }
    target = e.measuredBoundary + (long ? e.measuredHeight : -e.measuredHeight)
  } else if (method === 'support-resistance') {
    const targets = levels
      .filter((l) => l.recognitionIndex < index && (long ? l.price > entry : l.price < entry))
      .map((l) => l.price)
      .sort((a, b) => (long ? a - b : b - a))
    if (targets.length) target = targets[0]!
    else {
      target = entry + (long ? 1 : -1) * s.targetR * distance
      method = 'r-fallback'
    }
  } else target = entry + (long ? 1 : -1) * s.targetR * distance
  target = tickRound(target, c.tickSize, !long)
  const reward = long ? target - entry : entry - target,
    rr = reward / distance
  if (!finite(target) || target <= 0 || reward <= 0)
    return { reason: 'WAIT: supported target is not on the profitable side of entry' }
  if (rr + 1e-9 < s.minRR)
    return {
      reason: `WAIT: supported target reward/risk ${rr.toFixed(2)} is below ${s.minRR.toFixed(2)}; target is not stretched`,
    }
  const notes = [...e.notes]
  if (method === 'r-multiple' || method === 'r-fallback')
    notes.push(`${s.targetR}R is a local planning constraint, not independent market evidence.`)
  if (e.mode === 'reversal' && snapshot.trend !== desired)
    notes.push(
      `Broader MA trend remains ${snapshot.trend}; a slow crossover is not required for this reversal.`
    )
  if (s.gapPolicy === 'continuous')
    notes.push('Continuous-market local variant: explicit gap comparisons are relaxed.')
  const plan: BookPlan = {
    id: `plan:${e.id}:${b.time}`,
    eventId: e.id,
    side: e.side,
    name: e.name,
    createdAt: b.time,
    createdIndex: index,
    entry,
    stop,
    target,
    rr,
    status: 'active',
    targetMethod: method,
    stopMethod: e.stopMethod,
    notes,
  }
  plan.sizing = calculateBookRisk(plan, s, c.instrument)
  return { plan, reason: 'Qualified closed-candle price references' }
}
/** Public pure lifecycle primitive; never treats OHLC touches as broker fills. */
export function advanceBookPlan(
  plan: BookPlan,
  b: BookBar,
  index: number,
  s: BookSettings
): BookPlan {
  if (plan.status !== 'active' || index <= plan.createdIndex) return plan
  const stop = validBar(b) && (plan.side === 'long' ? b.low <= plan.stop : b.high >= plan.stop),
    target = validBar(b) && (plan.side === 'long' ? b.high >= plan.target : b.low <= plan.target)
  const status =
    stop && target
      ? 'ambiguous'
      : stop
        ? 'stop-touched'
        : target
          ? 'target-touched'
          : index - plan.createdIndex >= s.planExpiryBars
            ? 'expired'
            : 'active'
  return status === 'active'
    ? plan
    : { ...plan, status, terminalTime: b.time, terminalIndex: index }
}
export function chooseBookPlan(
  plans: BookPlan[],
  events: BookEvent[]
): { plan?: BookPlan; reason: string } {
  if (new Set(plans.map((p) => p.side)).size > 1)
    return { reason: 'WAIT: Conflicting qualified Long and Short evidence' }
  const byId = new Map(events.map((e) => [e.id, e]))
  const sorted = [...plans].sort((a, b) => {
    const ea = byId.get(a.eventId),
      eb = byId.get(b.eventId)
    return (
      (ea?.rank ?? 9) - (eb?.rank ?? 9) ||
      (eb?.contacts ?? 0) - (ea?.contacts ?? 0) ||
      (eb?.formationEnd ?? 0) - (ea?.formationEnd ?? 0) ||
      (ea?.patternId ?? a.id).localeCompare(eb?.patternId ?? b.id)
    )
  })
  return sorted[0]
    ? {
        plan: sorted[0],
        reason: 'One qualified plan selected by source rank, contacts, recency and pattern ID',
      }
    : { reason: 'WAIT: no newly qualified price trigger' }
}
export interface BookCandidate {
  event: BookEvent
  armIndex?: number
  boundary?: number
}
type Candidate = BookCandidate
/** Pure single-candle transition shared by the batch engine and parity consumers. Input state is never mutated. */
export function advanceBookCandidate(
  candidate: BookCandidate,
  bars: BookBar[],
  index: number,
  context: BookContext,
  settings: BookSettings
): { candidate: BookCandidate; state: 'confirmed' | 'waiting' | 'expired' | 'invalidated' } {
  const updated = { ...candidate, event: { ...candidate.event } }
  const state = evaluate(updated, bars, index, context, settings)
  return { candidate: updated, state }
}
function makeEvent(
  f: BookFormation,
  bars: BookBar[],
  all: BookIndicatorSnapshot[],
  c: BookContext
): BookEvent {
  return {
    ...f,
    id: `${c.exchange ?? ''}:${c.symbol}:${c.intervalSeconds}:${f.patternId}:${f.side}:${bars[f.startIndex]!.time}:${bars[f.endIndex]!.time}:${bars[f.recognitionIndex]!.time}`,
    formationStart: bars[f.startIndex]!.time,
    formationEnd: bars[f.endIndex]!.time,
    recognitionTime: bars[f.recognitionIndex]!.time,
    status: 'pending',
    nextCondition: nextCondition(f, c.tickSize),
    priorTrend: all[f.startIndex - 1]?.trend ?? 'unavailable',
  }
}
function nextCondition(f: BookFormation, tick: number) {
  if (f.confirmationRule === 'inverted-body')
    return `Very next candle must open and close green above real-body top ${f.trigger}`
  if (f.confirmationRule === 'retest')
    return 'Wait for a later retest of the frozen trendline and directional closing rejection'
  if (f.confirmationRule === 'next-boundary')
    return 'Wait for a directional boundary close, then very next candle open and directional close beyond the frozen boundary'
  if (f.confirmationRule === 'next-extreme')
    return `Very next candle directional close at least one tick beyond breakout extreme ${f.trigger}`
  return f.side === 'neutral'
    ? 'Wait for a later directional close outside the complete formation, with current directional trend'
    : `Wait for later ${f.side === 'long' ? 'green' : 'red'} close ${f.side === 'long' ? 'above' : 'below'} ${f.trigger} by at least ${tick}`
}
function beyond(b: BookBar, side: BookSide, anchor: number, tick: number) {
  return side === 'long' ? b.close >= anchor + tick - 1e-10 : b.close <= anchor - tick + 1e-10
}
function directional(b: BookBar, side: BookSide) {
  return direction(b) === side
}
function stopBroken(e: BookEvent, b: BookBar, c: BookContext, s: BookSettings) {
  if (e.side === 'neutral') return false
  const long = e.side === 'long',
    stop = tickRound(
      e.stopAnchor + (long ? -1 : 1) * Math.max(c.tickSize, s.stopBufferATR * e.scale),
      c.tickSize,
      !long
    )
  return long ? b.low <= stop : b.high >= stop
}
function evaluate(
  candidate: Candidate,
  bars: BookBar[],
  i: number,
  c: BookContext,
  s: BookSettings
): 'confirmed' | 'waiting' | 'expired' | 'invalidated' {
  const e = candidate.event,
    b = bars[i]!,
    later = i - e.endIndex,
    rule = e.confirmationRule
  if (i <= e.recognitionIndex) return 'waiting'
  if (!validBar(b)) return 'invalidated'
  const shape = e.kind === 'shape'
  if (shape && candidate.armIndex === undefined) {
    const window = e.shapeWindow
    if (window ? i - window.startIndex > window.maxBars : i - e.startIndex > s.shapeMaxBars)
      return 'expired'
  }
  if (
    !shape &&
    rule !== 'retest' &&
    later > (rule === 'inverted-body' || rule === 'next-extreme' ? 1 : s.candleTriggerBars)
  )
    return 'expired'
  if (rule === 'retest' && later > s.retestBars) return 'expired'
  if (rule === 'next-boundary' && candidate.armIndex !== undefined && i > candidate.armIndex + 1)
    return 'expired'
  if (e.upperLine && e.lowerLine && project(...e.upperLine, i) <= project(...e.lowerLine, i))
    return 'expired'
  if (e.side === 'neutral') {
    const high = Math.max(...e.points.filter((p) => p.role === 'high').map((p) => p.price)),
      low = Math.min(...e.points.filter((p) => p.role === 'low').map((p) => p.price))
    const side = direction(b)
    if (side !== 'neutral' && beyond(b, side, side === 'long' ? high : low, c.tickSize)) {
      e.side = side
      e.trigger = side === 'long' ? high : low
      e.stopAnchor = side === 'long' ? low : high
      return stopBroken(e, b, c, s) ? 'invalidated' : 'confirmed'
    }
    return 'waiting'
  }
  const side = e.side
  if (rule === 'inverted-body')
    return later === 1 && directional(b, side) && b.open > e.trigger && b.close > e.trigger
      ? stopBroken(e, b, c, s)
        ? 'invalidated'
        : 'confirmed'
      : 'expired'
  if (rule === 'retest') {
    const boundary = project(...e.line!, i),
      tol = Math.max(s.minToleranceTicks * c.tickSize, s.levelToleranceATR * e.scale)
    if (
      b.high >= boundary - tol &&
      b.low <= boundary + tol &&
      directional(b, side) &&
      beyond(b, side, boundary, c.tickSize)
    ) {
      e.trigger = boundary
      e.stopAnchor = side === 'long' ? b.low : b.high
      e.points = [...e.points, { time: b.time, index: i, price: boundary, role: 'retest' }]
      return 'confirmed'
    }
    return 'waiting'
  }
  if (rule === 'next-boundary') {
    if (candidate.armIndex !== undefined) {
      const B = candidate.boundary!
      return directional(b, side) &&
        (side === 'long' ? b.open > B && b.close > B : b.open < B && b.close < B)
        ? stopBroken(e, b, c, s)
          ? 'invalidated'
          : 'confirmed'
        : 'expired'
    }
    const boundary =
      e.upperLine && side === 'long'
        ? project(...e.upperLine, i)
        : e.lowerLine && side === 'short'
          ? project(...e.lowerLine, i)
          : e.trigger
    if (directional(b, side) && beyond(b, side, boundary, c.tickSize)) {
      candidate.armIndex = i
      candidate.boundary = boundary
      e.trigger = boundary
      e.measuredBoundary = boundary
      e.armingId = `arm:${e.id}:${b.time}`
      e.armedAt = b.time
      e.armedIndex = i
      if (e.patternId === 'bull-rectangle') e.stopAnchor = b.low
      e.points = [...e.points, { time: b.time, index: i, price: boundary, role: 'breakout' }]
      e.nextCondition = `Only the next candle may confirm with ${side === 'long' ? 'green' : 'red'} open and close beyond ${boundary}`
      return stopBroken(e, b, c, s) ? 'invalidated' : 'waiting'
    }
    return 'waiting'
  }
  if (stopBroken(e, b, c, s)) return 'invalidated'
  if (e.line) e.trigger = project(...e.line, i)
  else if (e.upperLine && side === 'long') e.trigger = project(...e.upperLine, i)
  else if (e.lowerLine && side === 'short') e.trigger = project(...e.lowerLine, i)
  if (e.targetMethod === 'measured') e.measuredBoundary = e.trigger
  const closeValid = beyond(b, side, e.trigger, c.tickSize) && (shape || directional(b, side))
  if (!closeValid) return rule === 'next-extreme' ? 'expired' : 'waiting'
  if (
    s.gapPolicy === 'explicit' &&
    (e.patternId === 'bull-engulfing' || e.patternId === 'bear-engulfing')
  ) {
    const second = bars[e.endIndex]!
    if (!(side === 'long' ? b.open > second.close : b.open < second.close)) return 'waiting'
  }
  return 'confirmed'
}
function observation(
  id: string,
  type: string,
  time: number,
  text: string,
  photos: number[],
  side?: BookSide
): BookObservation {
  return { id, type, time, text, sourcePhotos: photos, side }
}
function contextObservations(
  bars: BookBar[],
  snapshots: BookIndicatorSnapshot[],
  i: number,
  s: BookSettings,
  pivots: ReturnType<typeof confirmedPivots>
): BookObservation[] {
  const out: BookObservation[] = [],
    x = snapshots[i]!,
    p = snapshots[i - 1],
    b = bars[i]!,
    previous = bars[i - 1]
  const cross = (
    a: number | undefined,
    bb: number | undefined,
    pa: number | undefined,
    pb: number | undefined,
    type: string,
    photos: number[]
  ) => {
    if (![a, bb, pa, pb].every(finite)) return
    if (a! > bb! && pa! <= pb!)
      out.push(
        observation(
          `${type}:${b.time}:long`,
          type,
          b.time,
          `${type}: bullish closed-candle cross; context only`,
          photos,
          'long'
        )
      )
    if (a! < bb! && pa! >= pb!)
      out.push(
        observation(
          `${type}:${b.time}:short`,
          type,
          b.time,
          `${type}: bearish closed-candle cross; context only`,
          photos,
          'short'
        )
      )
  }
  if (p && previous) {
    cross(x.maFast, x.maSlow, p.maFast, p.maSlow, 'ma-cross', [5, 6])
    cross(b.close, x.maFast, previous.close, p.maFast, 'price-ma-cross', [6])
    cross(x.macd, x.macdSignal, p.macd, p.macdSignal, 'macd-signal-cross', [4, 5])
    cross(x.macd, 0, p.macd, 0, 'macd-zero-cross', [4])
    if (finite(x.rsi) && finite(p.rsi)) {
      if (p.rsi <= 30 && x.rsi > 30)
        out.push(
          observation(
            `rsi30:${b.time}`,
            'rsi-recross',
            b.time,
            'RSI recross above 30; price confirmation still required',
            [8, 9],
            'long'
          )
        )
      if (p.rsi >= 70 && x.rsi < 70)
        out.push(
          observation(
            `rsi70:${b.time}`,
            'rsi-recross',
            b.time,
            'RSI recross below 70; price confirmation still required',
            [8, 9],
            'short'
          )
        )
    }
    if (b.open > previous.close)
      out.push(
        observation(
          `gap-up:${b.time}`,
          'gap',
          b.time,
          'Opening above previous close; gap context, no automatic entry',
          [50],
          'long'
        )
      )
    if (b.open < previous.close)
      out.push(
        observation(
          `gap-down:${b.time}`,
          'gap',
          b.time,
          'Opening below previous close; gap context, no automatic entry',
          [50],
          'short'
        )
      )
  }
  // Oscillators are sampled at the same price pivot bars, then published only when the second pivot is recognized.
  for (const high of [true, false]) {
    const ps = pivots.filter((p) => p.side === (high ? 'high' : 'low')).slice(-2)
    if (ps.length !== 2 || ps[1]!.recognitionIndex !== i) continue
    const [a, z] = ps as [(typeof ps)[number], (typeof ps)[number]],
      distance = z.index - a.index
    if (distance < s.divergenceMinBars || distance > s.divergenceMaxBars) continue
    for (const oscillator of ['rsi', 'macd'] as const) {
      const av = snapshots[a.index]?.[oscillator],
        zv = snapshots[z.index]?.[oscillator]
      if (!finite(av) || !finite(zv)) continue
      if (high ? z.price > a.price && zv < av : z.price < a.price && zv > av) {
        const side = high ? 'short' : 'long',
          o = observation(
            `${oscillator}-divergence:${a.time}:${z.time}`,
            `${oscillator}-divergence`,
            b.time,
            `${oscillator.toUpperCase()} confirmed-pivot divergence setup; requires a separate price-pattern breakout`,
            oscillator === 'rsi' ? [7, 8] : [4],
            side
          )
        o.points = [
          {
            time: a.time,
            index: a.index,
            price: a.price,
            role: 'price-pivot',
            recognitionTime: a.recognitionTime,
          },
          {
            time: z.time,
            index: z.index,
            price: z.price,
            role: 'price-pivot',
            recognitionTime: z.recognitionTime,
          },
        ]
        out.push(o)
      }
    }
  }
  return out
}
function readiness(
  c: BookContext,
  s: BookSettings
): { status: BookGuideResult['readiness']; reasons: string[] } {
  const reasons: string[] = []
  if (!c.sourceReady) reasons.push('Source history is not ready')
  if (!c.connected) reasons.push('Source is disconnected')
  if (c.chartType !== 'standard') reasons.push('Synthetic chart types are unsupported')
  if (
    !finite(c.intervalSeconds) ||
    c.intervalSeconds <= 0 ||
    !finite(c.now) ||
    !finite(c.observedAt) ||
    !finite(c.tickSize) ||
    c.tickSize <= 0
  )
    reasons.push('Interval, time or tick size is unavailable')
  if (
    c.marketOpen &&
    (!finite(c.quoteObservedAt ?? c.observedAt) ||
      c.now - (c.quoteObservedAt ?? c.observedAt) > s.staleQuoteSeconds)
  )
    reasons.push('Live quote is stale')
  return {
    status: reasons.length ? 'unavailable' : c.marketOpen ? 'ready' : 'last-session',
    reasons,
  }
}
/** Deterministic batch entry point. It never emits historical alerts; use a persistent engine for fresh alerts. */
export function analyzeBookGuide(
  input: BookBar[],
  context: BookContext,
  settings: Partial<BookSettings> = {}
): BookGuideResult {
  return runBatch(input, context, resolveBookSettings(settings)).result
}
/** Completion is based on a received observation as well as the clock. Invalid explicit metadata never falls back silently. */
export function bookBarCloseTime(bar: BookBar, intervalSeconds: number): number | undefined {
  const close = bar.closeTime === undefined ? bar.time + intervalSeconds : bar.closeTime
  return finite(close) && close > bar.time ? close : undefined
}
function completedBars(input: BookBar[], c: BookContext): BookBar[] {
  const cap = Math.min(c.now, c.observedAt),
    out: BookBar[] = []
  for (const b of input) {
    if (!finite(b.time)) continue
    const close = bookBarCloseTime(b, c.intervalSeconds)
    if (close === undefined) {
      if (b.time + c.intervalSeconds <= cap) out.push({ ...b, repaired: true })
      continue
    }
    if (close > cap) break
    const previous = out.at(-1)
    out.push(previous && b.time <= previous.time ? { ...b, repaired: true } : b)
  }
  return out
}
function runBatch(
  input: BookBar[],
  c: BookContext,
  s: BookSettings
): {
  result: BookGuideResult
  baseResult: BookGuideResult
  timeline: BookAlert[]
  closed: BookBar[]
} {
  const bars = completedBars(input, c)
  const empty: BookIndicatorSnapshot = { trend: 'unavailable' },
    snapshots = indicators(bars, s),
    events: BookEvent[] = [],
    pending: Candidate[] = [],
    observations: BookObservation[] = [],
    timeline: BookAlert[] = [],
    seen = new Set<string>()
  let contextPivots: BookPivot[] = []
  const breakouts: { event: BookEvent; index: number; boundary: number }[] = []
  const recordBreakout = (e: BookEvent, index: number, boundary: number) => {
    if (breakouts.some((b) => b.event.id === e.id)) return
    breakouts.push({ event: e, index, boundary })
    observations.push({
      ...observation(
        `break:${e.id}`,
        'direct-breakout',
        bars[index]!.time,
        `Closed directional breakout at frozen boundary ${boundary}; volume is evidence, not proof against a retest`,
        [26, 27],
        e.side === 'neutral' ? undefined : e.side
      ),
      parentEventId: e.id,
    })
  }
  let active: BookPlan | undefined,
    lastTerminal: BookPlan | undefined,
    levels: BookLevel[] = [],
    alternatives: BookEvent[] = [],
    reason = 'WAIT: closed valid candles and trend warm-up are required',
    next = reason
  let lastDecisionIndex = -1
  const alert = (type: BookAlert['type'], e: BookEvent, time: number, id = e.id, text = e.name) =>
    timeline.push({
      id: `${c.exchange ?? ''}:${c.symbol}:${c.intervalSeconds}:${id}:${type}:${time}`,
      type,
      time,
      eventId: id,
      patternId: e.patternId,
      side: e.side,
      text,
    })
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i]!,
      x = snapshots[i]!
    if (active) {
      const advanced = advanceBookPlan(active, b, i, s)
      if (advanced.status !== 'active') {
        lastTerminal = advanced
        alternatives = []
        reason = `${advanced.name}: ${advanced.status}; wait for a new qualified setup.`
        next = 'Wait for newly confirmed price-pattern geometry and context'
        lastDecisionIndex = i
        const e = events.find((e) => e.id === advanced.eventId)
        if (e && advanced.status !== 'expired')
          alert(
            advanced.status === 'ambiguous'
              ? 'ambiguous-reference-touch'
              : advanced.status === 'stop-touched'
                ? 'stop-reference-touch'
                : 'target-reference-touch',
            e,
            b.time,
            advanced.id,
            `${advanced.name}: ${advanced.status}; price reference only`
          )
        active = undefined
      }
    }
    if (!validBar(b)) {
      for (const p of pending) p.event.status = 'invalidated'
      pending.length = 0
      continue
    }
    const pivots = confirmedPivots(bars.slice(0, i + 1), s.pivotLeft, s.pivotRight, s.pivotSpacing)
    contextPivots = pivots
    const atr = snapshots[i - 1]?.atr
    observations.push(...contextObservations(bars, snapshots, i, s, pivots))
    if (!finite(atr) || atr <= 0 || !finite(c.tickSize) || c.tickSize <= 0) continue
    levels = buildLevels(pivots, i, atr, c.tickSize, s)
    const qualified: BookPlan[] = [],
      fresh: BookEvent[] = []
    const process = (candidate: Candidate) => {
      const e = candidate.event
      if (e.kind === 'shape' && candidate.armIndex === undefined) {
        const updated = revalidateBookShape(e, bars, i, s, c.tickSize, pivots)
        if (!updated) {
          e.status = 'expired'
          e.nextCondition = 'Received shape geometry or its family window no longer qualifies'
          return
        }
        Object.assign(e, updated)
      }
      const transition = advanceBookCandidate(candidate, bars, i, c, s),
        state = transition.state
      Object.assign(e, transition.candidate.event)
      candidate.armIndex = transition.candidate.armIndex
      candidate.boundary = transition.candidate.boundary
      if (candidate.armIndex === i) recordBreakout(e, i, candidate.boundary!)
      if (state === 'waiting') return
      if (state === 'confirmed') {
        e.status = 'confirmed'
        e.confirmationTime = b.time
        e.confirmationIndex = i
        e.confirmationId = `confirm:${e.id}:${b.time}`
        e.nextCondition = 'Closed-candle pattern confirmed'
        if (!e.armingId) {
          e.armingId = `arm:${e.id}:${b.time}`
          e.armedAt = b.time
          e.armedIndex = i
        }
        if (e.kind === 'shape') recordBreakout(e, i, e.measuredBoundary ?? e.trigger)
        e.points = [...e.points, { time: b.time, index: i, price: b.close, role: 'confirmation' }]
        alert('confirmed-pattern', e, b.time)
        const q = qualifyBookEvent(e, b, i, c, s, levels, x)
        e.qualificationReason = q.reason
        lastDecisionIndex = i
        if (q.plan) {
          e.qualificationId = `qualify:${e.id}:${b.time}`
          e.qualificationTime = b.time
          qualified.push(q.plan)
          fresh.push(e)
        } else {
          reason = q.reason
          next = q.reason
        }
      } else {
        e.status = state
        e.nextCondition =
          state === 'expired'
            ? 'Trigger window expired; wait for new geometry'
            : 'Pattern stop or data invalidated before confirmation'
      }
    }
    for (const candidate of [...pending]) process(candidate)
    for (let j = pending.length - 1; j >= 0; j--)
      if (pending[j]!.event.status !== 'pending') pending.splice(j, 1)
    const formations = [
      ...detectCandles(bars, i, s, c.tickSize, atr, pivots),
      ...detectShapes(bars, i, s, c.tickSize, atr, pivots),
      ...detectLevelBreaks(bars, i, s, c.tickSize, atr, levels, pivots),
    ]
    for (const f of formations) {
      const e = makeEvent(f, bars, snapshots, c)
      if (seen.has(e.id)) continue
      seen.add(e.id)
      events.push(e)
      if (f.kind !== 'shape') {
        e.armingId = `arm:${e.id}:${b.time}`
        e.armedAt = b.time
        e.armedIndex = i
      }
      if (f.kind === 'level' || f.kind === 'trendline')
        recordBreakout(e, i, f.measuredBoundary ?? f.trigger)
      const candidate: Candidate = { event: e }
      // Geometry may be known before this bar, but a newly formed candle requires a later candle.
      if (f.kind === 'shape' && f.recognitionIndex < i) process(candidate)
      if (e.stopCheckFrom === i && stopBroken(e, b, c, s)) {
        e.status = 'invalidated'
        e.nextCondition = 'Corrective stop was already breached by the fifth candle'
      }
      if (e.status === 'pending') pending.push(candidate)
    }
    for (const original of breakouts) {
      const { event: e, index: breakIndex, boundary } = original,
        age = i - breakIndex
      if (age <= 0 || age > Math.max(s.failedBreakoutBars, s.retestBars)) continue
      const failed = e.side === 'long' ? b.close <= boundary : b.close >= boundary
      if (
        failed &&
        age <= s.failedBreakoutBars &&
        !observations.some((o) => o.id === `failed:${e.id}`)
      )
        observations.push({
          ...observation(
            `failed:${e.id}`,
            'failed-breakout',
            b.time,
            'Completed close returned inside the original boundary; this does not authorize an opposite plan',
            [26, 27]
          ),
          parentEventId: e.id,
        })
      else if (
        !failed &&
        age <= s.retestBars &&
        b.high >= boundary - e.scale * s.levelToleranceATR &&
        b.low <= boundary + e.scale * s.levelToleranceATR &&
        !observations.some((o) => o.id === `retest:${e.id}`)
      )
        observations.push({
          ...observation(
            `retest:${e.id}`,
            'breakout-retest',
            b.time,
            'Later retest of original frozen breakout boundary; prior resistance/support may reverse its role',
            [26, 27, 48]
          ),
          parentEventId: e.id,
        })
    }
    if (!active) alternatives = fresh
    if (!active && qualified.length) {
      const chosen = chooseBookPlan(qualified, fresh)
      reason = chosen.reason
      next = chosen.reason
      if (chosen.plan) {
        active = chosen.plan
        const e = fresh.find((e) => e.id === active!.eventId)!
        alert('qualified-plan', e, b.time, active.id)
        alternatives = fresh.filter((e) => e.id !== active!.eventId)
      }
    } else if (active) {
      alternatives = [
        ...new Map(
          [...alternatives, ...fresh].filter((e) => e.id !== active!.eventId).map((e) => [e.id, e])
        ).values(),
      ].slice(-s.maxDrawings)
    }
    if (active) {
      reason = `${active.name}: frozen ${active.side === 'long' ? 'Long' : 'Short'} Entry ${active.entry}, SL ${active.stop}, Target ${active.target}.`
      next = `Wait for a completed-candle stop/target reference touch or ${s.planExpiryBars}-candle expiry.`
      if (alternatives.some((e) => e.side !== active!.side))
        reason += ' Opposite qualified evidence: review the active reference plan.'
    }
  }
  if (!active && pending.length && lastDecisionIndex < bars.length - 1) {
    const relevant = pending.filter(
      (p) =>
        p.event.mode === 'neutral' ||
        (p.event.mode === 'reversal'
          ? p.event.priorTrend === (p.event.side === 'long' ? 'bear' : 'bull')
          : p.event.priorTrend === (p.event.side === 'long' ? 'bull' : 'bear'))
    )
    const newest = [...(relevant.length ? relevant : pending)].sort(
      (a, b) =>
        b.event.endIndex - a.event.endIndex ||
        a.event.rank - b.event.rank ||
        a.event.patternId.localeCompare(b.event.patternId)
    )[0]!.event
    reason = `WAIT: ${newest.name} geometry observed. ${newest.nextCondition}`
    next = newest.nextCondition
  }
  const confirmed = events.filter((e) => e.status === 'confirmed'),
    last = bars.length - 1
  const visible = confirmed
    .filter(
      (e) =>
        bookOrdinaryEventVisible(e, s.showNeutral) &&
        (s.fullHistory || (e.confirmationIndex ?? -Infinity) > last - s.labelLookback)
    )
    .slice(-Math.min(s.maxDrawings, s.maxLabels))
  const current = snapshots.at(-1) ?? empty
  const invalid = bars.filter((b) => !validBar(b)).length
  const unavailableReasons = invalid
    ? [`${invalid} invalid or repaired candle(s) excluded; affected indicator warm-up resets`]
    : []
  const result: BookGuideResult = {
    events: confirmed,
    pendingEvents: events.filter((e) => e.status === 'pending'),
    visibleEvents: visible,
    observations,
    activePlan: active,
    lastTerminalPlan: lastTerminal,
    alternatives,
    explanation: reason,
    nextCondition: next,
    alerts: [],
    readiness: 'ready',
    unavailableReasons,
    indicators: current,
    filters: bookFilterStates(bars.at(-1), s, current, active?.side ?? 'long'),
    levels,
    trendLines: bookContextTrendLines(contextPivots, bars.at(-1), bars.length - 1),
  }
  return {
    result: refreshQuoteState(result, input, c, s),
    baseResult: result,
    timeline,
    closed: bars,
  }
}
function refreshQuoteState(
  base: BookGuideResult,
  input: BookBar[],
  c: BookContext,
  s: BookSettings
): BookGuideResult {
  const ready = readiness(c, s),
    active = base.activePlan
  const result: BookGuideResult = {
    ...base,
    alerts: [],
    readiness: ready.status,
    unavailableReasons: [...base.unavailableReasons, ...ready.reasons],
    explanation:
      ready.status === 'unavailable'
        ? `${base.explanation} Source unavailable: ${ready.reasons.join('; ')}.`
        : ready.status === 'last-session'
          ? `${base.explanation} Last-session references.`
          : base.explanation,
  }
  let receivedIndex = input.length - 1
  while (receivedIndex >= 0 && input[receivedIndex].time > c.now) receivedIndex--
  const received = input[receivedIndex]
  if (received && validBar(received) && c.sourceReady && finite(c.now)) {
    result.trendLines = base.trendLines
      ?.map((line) => ({
        ...line,
        to: {
          ...line.to,
          time: received.time,
          index: receivedIndex,
          price:
            line.from.price +
            ((line.to.price - line.from.price) * (receivedIndex - line.from.index)) /
              (line.to.index - line.from.index),
        },
      }))
      .filter((line) => finite(line.to.price) && line.to.price > 0)
  }
  const forming = input.at(-1)
  if (
    forming &&
    validBar(forming) &&
    (bookBarCloseTime(forming, c.intervalSeconds) ?? Infinity) > Math.min(c.now, c.observedAt)
  )
    result.provisional = {
      time: forming.time,
      price: forming.close,
      ...(active
        ? {
            distanceToStop: Math.abs(forming.close - active.stop),
            distanceToTarget: Math.abs(forming.close - active.target),
          }
        : {}),
    }
  return result
}
/** Reconciliation compares actual completed OHLCV, so corrections invalidate all dependent cached state. */
export class BookPatternEngine {
  private identity = ''
  private previous: BookBar[] = []
  private initialized = false
  private delivered = new Set<string>()
  private cached?: BookGuideResult
  private previousReady = false
  private deliveryBlockedThrough = -Infinity
  reconcile(
    bars: BookBar[],
    context: BookContext,
    settings: Partial<BookSettings> = {}
  ): BookGuideResult {
    const s = resolveBookSettings(settings),
      key = JSON.stringify([
        context.exchange,
        context.symbol,
        context.intervalSeconds,
        context.tickSize,
        context.chartType,
        context.instrument,
        { ...s, showTrendLines: undefined }, // Display-only toggles do not reset alert delivery.
      ])
    // Failed/snapshot/loading history has no new verified completion watermark. Retain
    // this identity's last verified state; never promote cached OHLC using wall time.
    if (this.initialized && this.identity === key && !context.sourceReady && this.cached) {
      this.previousReady = false
      if (finite(context.observedAt))
        this.deliveryBlockedThrough = Math.max(
          this.deliveryBlockedThrough,
          Math.min(context.now, context.observedAt)
        )
      return structuredClone(refreshQuoteState(this.cached, [], context, s))
    }
    const closed = completedBars(bars, context)
    const same = (a: BookBar, b: BookBar) =>
      a.time === b.time &&
      a.open === b.open &&
      a.high === b.high &&
      a.low === b.low &&
      a.close === b.close &&
      Object.is(a.volume, b.volume) &&
      a.repaired === b.repaired &&
      Object.is(a.closeTime, b.closeTime)
    const correction =
      this.previous.length > closed.length ||
      this.previous.some((b, i) => !closed[i] || !same(b, closed[i]!))
    const reset = !this.initialized || this.identity !== key || correction
    const ready = readiness(context, s).status === 'ready'
    const resumed = this.initialized && !this.previousReady && ready
    const observedThrough = Math.min(context.now, context.observedAt)
    if (reset) this.deliveryBlockedThrough = finite(observedThrough) ? observedThrough : -Infinity
    else if ((!ready || resumed) && finite(observedThrough))
      this.deliveryBlockedThrough = Math.max(this.deliveryBlockedThrough, observedThrough)
    // Readiness transitions must be recorded even when no completed candle changed.
    this.previousReady = ready
    if (!reset && closed.length === this.previous.length && this.cached)
      return structuredClone(refreshQuoteState(this.cached, bars, context, s))
    const batch = runBatch(bars, context, s)
    const previousTime = this.previous.at(-1)?.time ?? -Infinity
    if (reset) this.delivered.clear()
    if (!reset && !resumed && ready) {
      const closeTimes = new Map(
        closed.map((bar) => [bar.time, bookBarCloseTime(bar, context.intervalSeconds)])
      )
      batch.result.alerts = batch.timeline.filter((a) => {
        const closeTime = closeTimes.get(a.time)
        return (
          a.time > previousTime &&
          !this.delivered.has(a.id) &&
          closeTime !== undefined &&
          closeTime > this.deliveryBlockedThrough &&
          closeTime <= observedThrough &&
          context.now - closeTime <= s.staleQuoteSeconds
        )
      })
    }
    // Even suppressed alerts are consumed; reconnecting never replays unavailable/history alerts.
    for (const a of batch.timeline) this.delivered.add(a.id)
    this.previous = closed.map((b) => ({ ...b }))
    this.identity = key
    this.initialized = true
    this.cached = structuredClone(batch.baseResult)
    return batch.result
  }
}
