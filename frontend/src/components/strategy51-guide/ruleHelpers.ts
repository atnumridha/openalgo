import type {
  Candidate,
  EvaluationInput,
  Frame,
  Side,
  StrategyDefinition,
  StrategyRow,
  SuppliedContext,
} from './types'
export const green = (f: Frame) => f.bar.close > f.bar.open
export const red = (f: Frame) => f.bar.close < f.bar.open
/** Geometry uses only known source points at their real candle timestamps. */
export function connectSourcePoints(
  frames: readonly Frame[],
  points: Candidate['points']
): Pick<Candidate, 'points' | 'segments'> {
  const known = points
    .filter((p) => frames[p.index] && Number.isFinite(p.price))
    .sort((a, b) => a.index - b.index)
  const timed = known.map((p) => ({ ...p, time: frames[p.index].bar.time }))
  return {
    points: known,
    segments: timed.slice(1).map((p, i) => ({ from: timed[i], to: p, role: 'source formation' })),
  }
}
export const present = (...v: (number | undefined)[]) =>
  v.every((x) => x != null && Number.isFinite(x))
export const near = (price: number, level: number | undefined, f: Frame, tolerance = 0.25) =>
  level != null &&
  Math.abs(price - level) <= Math.max(0.000001, (f.atr ?? f.bar.high - f.bar.low) * tolerance)
export const touches = (f: Frame, level: number | undefined, tolerance = 0.25) =>
  level != null &&
  f.bar.low <= level + (f.atr ?? 0) * tolerance &&
  f.bar.high >= level - (f.atr ?? 0) * tolerance
export const crossUp = (previous: number | undefined, current: number | undefined, level: number) =>
  previous != null && current != null && previous <= level && current > level
export const crossDown = (
  previous: number | undefined,
  current: number | undefined,
  level: number
) => previous != null && current != null && previous >= level && current < level
export const body = (f: Frame) => Math.abs(f.bar.close - f.bar.open)
export const small = (f: Frame) => body(f) <= 0.35 * (f.bar.high - f.bar.low)
export const pin = (f: Frame, side: Side) => {
  const b = Math.max(body(f), 0.0000001),
    lower = Math.min(f.bar.close, f.bar.open) - f.bar.low,
    upper = f.bar.high - Math.max(f.bar.close, f.bar.open)
  return small(f) && (side === 'long' ? lower >= 2 * b && upper <= b : upper >= 2 * b && lower <= b)
}
export const reversal = (f: Frame, p: Frame, side: Side) =>
  side === 'long'
    ? green(f) && (pin(f, side) || f.bar.close > p.bar.open || red(p))
    : red(f) && (pin(f, side) || f.bar.close < p.bar.open || green(p))
export function row(
  d: StrategyDefinition,
  state: StrategyRow['state'],
  reason: string,
  next = reason,
  candidate?: Candidate
): StrategyRow {
  return { definition: d, state, reason, next, candidate, notes: d.notes }
}
export function waiting(d: StrategyDefinition, reason: string): StrategyRow {
  return row(d, 'waiting', reason, reason)
}
export function supplied(a: EvaluationInput, id: string): SuppliedContext | undefined {
  const f = a.frames[a.index]
  return [...(a.extras.supplied ?? []), ...a.settings.supplied].find(
    (x) =>
      x.strategyId === id &&
      x.symbol === a.context.symbol &&
      (x.exchange ?? '') === (a.context.exchange ?? '') &&
      x.intervalSeconds === a.context.intervalSeconds &&
      x.asOf <=
        Math.min(
          a.context.now,
          a.context.observedAt,
          f.bar.closeTime ?? f.bar.time + a.context.intervalSeconds
        ) &&
      x.asOf > 0 &&
      x.description.trim().length > 0
  )
}
export function candidate(
  d: StrategyDefinition,
  a: EvaluationInput,
  side: Side,
  signalIndex: number,
  stop: number | undefined,
  target: number | undefined,
  details: Partial<Candidate> = {}
): StrategyRow {
  const f = a.frames[a.index],
    q = a.frames[signalIndex],
    entry = f.bar.close
  const sourceTarget = target != null && Number.isFinite(target) ? target : undefined
  const c: Candidate = {
    strategyId: d.id,
    side,
    signalIndex,
    index: a.index,
    entry,
    stop,
    target: sourceTarget,
    targetMethod:
      sourceTarget != null
        ? 'Source target snapshot'
        : 'Source conditional exit; numerical target not specified',
    targetOrigin: sourceTarget != null ? (details.supplied ? 'supplied' : 'source') : undefined,
    stopMethod: 'Signal candle extreme',
    expected:
      side === 'long'
        ? 'Bullish continuation / reversal after closed-candle confirmation'
        : 'Bearish continuation / reversal after closed-candle confirmation',
    next: 'Monitor the stated stop, target and source exit condition',
    exitRule: d.exit,
    notes: [
      ...(signalIndex < a.index
        ? [
            'Local execution convention: a later candle must close through the source trigger; entry is that closed-candle price reference, not an assumed trigger fill.',
          ]
        : ['Source confirming-close reference; not a broker fill.']),
    ],
    points: [
      { index: signalIndex, price: side === 'long' ? q.bar.low : q.bar.high, role: 'signal' },
      { index: a.index, price: entry, role: 'confirmation' },
    ],
    ...details,
  }
  return row(
    d,
    'confirmed',
    `${side === 'long' ? 'Long' : 'Short'} conditions confirmed on a closed candle`,
    c.next,
    c
  )
}
export function breakout(
  a: EvaluationInput,
  side: Side,
  level: number | undefined,
  signalIndex = a.index - 1
): boolean {
  if (level == null || signalIndex < 0) return false
  const f = a.frames[a.index],
    p = a.frames[a.index - 1]
  return side === 'long'
    ? f.bar.close > level && p.bar.close <= level
    : f.bar.close < level && p.bar.close >= level
}
export function candleBreak(a: EvaluationInput, side: Side, signalIndex = a.index - 1): boolean {
  const q = a.frames[signalIndex]
  return !!q && breakout(a, side, side === 'long' ? q.bar.high : q.bar.low, signalIndex)
}
export function swingStop(f: Frame, side: Side): number | undefined {
  return (side === 'long' ? f.lows : f.highs).at(-1)?.price
}
export function nextPivot(f: Frame, side: Side, entry: number): number | undefined {
  const levels = [f.s2, f.s1, f.cprLow, f.pivot, f.cprHigh, f.r1, f.r2]
    .filter((x): x is number => x != null && (side === 'long' ? x > entry : x < entry))
    .sort((a, b) => a - b)
  return side === 'long' ? levels[0] : levels.at(-1)
}
export function rrTarget(
  entry: number,
  stop: number | undefined,
  side: Side,
  r: number
): number | undefined {
  return stop != null ? entry + (side === 'long' ? 1 : -1) * Math.abs(entry - stop) * r : undefined
}
export function contextPlan(
  d: StrategyDefinition,
  a: EvaluationInput,
  kind: SuppliedContext['kind'],
  onlyLong = false
): StrategyRow {
  const x = supplied(a, d.id)
  if (!x || x.kind !== kind)
    return row(d, 'needs-context', `Needs as-of ${kind} context`, d.requirements.join('; '))
  if (onlyLong && x.side === 'short')
    return row(
      d,
      'needs-context',
      'No unambiguous source short branch',
      'Choose the source long branch; short rules are unresolved'
    )
  if (!present(x.entry, x.stop) || !(x.entry! > 0 && x.stop! > 0))
    return row(
      d,
      'needs-context',
      'Context needs explicit valid entry and stop',
      'Enter the as-of source anchors in Details'
    )
  if (!breakout(a, x.side, x.entry))
    return waiting(
      d,
      `Wait for a closed candle ${x.side === 'long' ? 'above' : 'below'} supplied trigger ${x.entry}`
    )
  return candidate(d, a, x.side, a.index, x.stop, x.target, {
    supplied: true,
    stopMethod: 'Supplied source anchor',
    targetMethod: x.target != null ? 'Supplied target' : 'Source target not specified',
    notes: ['Context was supplied by the user; it was not automatically detected.', x.description],
  })
}
export function timeframe(d: StrategyDefinition, a: EvaluationInput): StrategyRow | undefined {
  const exact: Record<string, number[]> = {
    '1.1': [1800],
    '1.2': [1800],
    '1.3': [1800],
    '1.4': [86400],
    '1.5': [86400],
    '1.7': [3600, 86400],
    '2.1': [300],
    '2.2': [300],
    '2.3': [300],
    '2.4': [300],
    '2.5': [300],
    '2.6': [300],
    '2.7': [300],
    '3.5': [900],
    '4.1': [86400],
    '4.2': [86400],
    '4.4': [86400],
    '5.1': [180],
    '5.2': [60],
    '5.3': [60],
    '5.4': [60],
    '5.5': [300],
    '5.6': [60],
    '6.4': [300],
    '6.5': [300],
    '7.1': [300],
    '7.2': [86400],
    '7.4': [3600, 14400, 86400],
    '7.7': [60, 300],
  }
  const n = a.context.intervalSeconds,
    t = exact[d.id]
  if ((t && !t.includes(n)) || (d.id === '1.6' && n < 1800) || (d.id === '7.3' && n < 900))
    return row(
      d,
      'timeframe',
      'Different strategy timeframe',
      `Use ${t ? t.map((s) => (s >= 86400 ? '1d' : s >= 3600 ? `${s / 3600}h` : `${s / 60}m`)).join(' / ') : d.id === '1.6' ? '30m or higher' : '15m or higher'}; current ${n / 60}m`
    )
  return undefined
}
