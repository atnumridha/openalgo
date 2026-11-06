/** Pure chart planning. Inputs are already-observed completed UTC candles, never quotes. */
export interface PlanBar {
  time: number
  open: number
  high: number
  low: number
  close: number
}
export type PlanDirection = 'long' | 'short'
export interface EntryPlan {
  entry: number
  stop: number
  target: number
  direction: PlanDirection
  atr: number
  buffer: number
  structure: number
  risk: number
  asOf: number
  id: string
}
export interface PlanResult {
  plan: EntryPlan | null
  reason: string
  status?: string
}
type Pivot = { price: number; time: number; knownAt: number }
const valid = (b: PlanBar) =>
  [b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) &&
  b.time > 0 &&
  Math.min(b.open, b.high, b.low, b.close) > 0 &&
  b.low <= Math.min(b.open, b.close) &&
  b.high >= Math.max(b.open, b.close)
const scale = 1e8
const units = (n: number) => Math.round(n * scale)
const snap = (n: number, tick: number, up = false) =>
  ((up ? Math.ceil : Math.floor)(units(n) / units(tick)) * units(tick)) / scale
const positive = (n: number) => Number.isFinite(n) && n > 0

export interface PlanSession {
  start: number
  end: number
  offset: number
}
const equitySession: PlanSession = { start: 555, end: 930, offset: 19800 }
function adjacent(previous: PlanBar, current: PlanBar, seconds: number, session?: PlanSession) {
  if (current.time - previous.time === seconds) return true
  if (!session) return false
  const local = (time: number) => ({
    day: Math.floor((time + session.offset) / 86400),
    minute: Math.floor(((time + session.offset) % 86400) / 60),
  })
  const p = local(previous.time),
    c = local(current.time)
  if (c.day <= p.day || c.day - p.day > 4) return false
  // The calendar is not inferred from missing intraday candles. Across a daily
  // closure accept only the next observed weekday, including a normal weekend.
  let next = p.day + 1
  while ([0, 6].includes(new Date(next * 86400000).getUTCDay())) next++
  if (c.day !== next) return false
  if (seconds >= 86400) return c.minute === p.minute
  const lastStart =
    session.start + Math.floor((session.end - session.start - 1) / (seconds / 60)) * (seconds / 60)
  return p.minute === lastStart && c.minute === session.start
}

function analyse(
  input: readonly PlanBar[],
  seconds: number,
  indian: boolean | PlanSession = false
) {
  const session = typeof indian === 'object' ? indian : indian ? equitySession : undefined
  const bars = [...new Map(input.filter(valid).map((b) => [b.time, b])).values()].sort(
    (a, b) => a.time - b.time
  )
  const atrs: Array<number | null> = [],
    highs: Pivot[] = [],
    lows: Pivot[] = []
  let atr: number | null = null,
    seed = 0,
    count = 0
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i],
      previous = bars[i - 1]
    if (previous) {
      if (!adjacent(previous, b, seconds, session)) {
        atr = null
        seed = 0
        count = 0
        atrs.push(null)
        continue
      }
      const tr = Math.max(
        b.high - b.low,
        Math.abs(b.high - previous.close),
        Math.abs(b.low - previous.close)
      )
      if (atr == null) {
        seed += tr
        if (++count === 14) atr = seed / 14
      } else atr = (atr * 13 + tr) / 14
    }
    atrs.push(atr)
    if (i < 4) continue
    const p = bars[i - 2],
      neighbours = [bars[i - 4], bars[i - 3], bars[i - 1], b]
    // A hole is not a confirming candle. Pivots need four actual adjacent source bars.
    if (
      bars
        .slice(i - 4, i + 1)
        .some((bar, j, all) => j > 0 && !adjacent(all[j - 1], bar, seconds, session))
    )
      continue
    if (neighbours.every((n) => p.high > n.high))
      highs.push({ price: p.high, time: p.time, knownAt: b.time + seconds })
    if (neighbours.every((n) => p.low < n.low))
      lows.push({ price: p.low, time: p.time, knownAt: b.time + seconds })
  }
  return { bars, atrs, highs, lows }
}
function build(
  entry: number,
  tick: number,
  direction: PlanDirection,
  atr: number | null,
  structure: number | undefined,
  asOf: number
): PlanResult {
  if (!positive(entry) || !positive(tick) || units(tick) < 1 || !Number.isSafeInteger(units(entry)))
    return { plan: null, reason: 'Enter a positive entry and a verified contract price increment.' }
  if (units(entry) % units(tick) !== 0)
    return {
      plan: null,
      reason: `Entry must follow the ${tick} price increment. An off-tick average fill cannot produce an exact executable 1:2 plan.`,
    }
  if (!atr || !positive(atr))
    return { plan: null, reason: 'Waiting for enough completed candles for ATR 14.' }
  if (structure == null || !positive(structure))
    return {
      plan: null,
      reason: `Waiting for a confirmed swing ${direction === 'long' ? 'low below' : 'high above'} entry.`,
    }
  const buffer = Math.max(tick, 0.1 * atr)
  const stop =
    direction === 'long'
      ? snap(Math.min(structure - buffer, entry - 1.5 * atr), tick)
      : snap(Math.max(structure + buffer, entry + 1.5 * atr), tick, true)
  const riskUnits = Math.abs(units(entry) - units(stop)),
    targetUnits = units(entry) + (direction === 'long' ? 2 : -2) * riskUnits
  if (!positive(stop) || riskUnits <= 0 || targetUnits <= 0 || !Number.isSafeInteger(targetUnits))
    return {
      plan: null,
      reason: 'This entry and chart structure cannot produce positive SL and target prices.',
    }
  const target = targetUnits / scale,
    risk = riskUnits / scale
  return {
    plan: {
      entry,
      stop,
      target,
      direction,
      atr,
      buffer,
      structure,
      risk,
      asOf,
      id: `${asOf}:${direction}:${units(entry)}:${units(stop)}`,
    },
    reason: '',
  }
}
export function calculateEntryPlan(
  input: readonly PlanBar[],
  entry: number,
  tick: number,
  direction: PlanDirection,
  seconds = 300,
  indian: boolean | PlanSession = false
): PlanResult {
  const data = analyse(input, seconds, indian),
    last = data.bars.at(-1)
  const points = direction === 'long' ? data.lows : data.highs
  const structure = [...points]
    .reverse()
    .find((p) => (direction === 'long' ? p.price < entry : p.price > entry))?.price
  return build(
    entry,
    tick,
    direction,
    data.atrs.at(-1) ?? null,
    structure,
    last ? last.time + seconds : 0
  )
}
function trendFrom(highs: Pivot[], lows: Pivot[], asOf: number): 'long' | 'short' | 'none' {
  const h = highs.filter((p) => p.knownAt <= asOf).slice(-2),
    l = lows.filter((p) => p.knownAt <= asOf).slice(-2)
  if (h.length < 2 || l.length < 2) return 'none'
  if (h[1].price > h[0].price && l[1].price > l[0].price) return 'long'
  if (h[1].price < h[0].price && l[1].price < l[0].price) return 'short'
  return 'none'
}
export function confirmedTrend(input: readonly PlanBar[], asOf: number, seconds = 900) {
  const data = analyse(
    input.filter((b) => b.time + seconds <= asOf),
    seconds
  )
  return trendFrom(data.highs, data.lows, asOf)
}
/** Causal breakout → retest within 3 bars → entry within 2 bars. No simulated broker fills. */
export function findAutomaticSetup(
  input: readonly PlanBar[],
  trendBars: readonly PlanBar[],
  tick: number,
  allowed: 'both' | 'long' | 'short' | 'CE' | 'PE',
  seconds = 300,
  session: boolean | PlanSession = allowed === 'CE' || allowed === 'PE'
): PlanResult {
  if (!positive(tick)) return { plan: null, reason: 'Contract price increment unavailable.' }
  const data = analyse(input, seconds, session),
    trend = analyse(trendBars, 900, session)
  let breakout: { index: number; level: number; direction: PlanDirection } | null = null
  let candidate: { plan: EntryPlan; index: number; invalid: number; state: string } | null = null
  let lastResult: PlanResult = {
    plan: null,
    reason: 'Waiting for a confirmed breakout and retest.',
    status: 'Waiting',
  }
  for (let i = 1; i < data.bars.length; i++) {
    const b = data.bars[i],
      previous = data.bars[i - 1],
      asOf = b.time + seconds
    const bias = trendFrom(trend.highs, trend.lows, asOf)
    const permitted: PlanDirection | 'none' =
      allowed === 'CE'
        ? bias === 'long'
          ? 'long'
          : 'none'
        : allowed === 'PE'
          ? bias === 'short'
            ? 'long'
            : 'none'
          : allowed === 'both'
            ? bias
            : allowed === bias
              ? bias
              : 'none'
    if (b.time - previous.time !== seconds) {
      breakout = null
      if (candidate && ['Armed', 'Entry touched'].includes(candidate.state)) {
        candidate.state = 'Data gap'
        lastResult = {
          plan: candidate.plan,
          reason: 'A history gap prevents verifying this setup.',
          status: candidate.state,
        }
      }
    }
    if (candidate && ['Armed', 'Entry touched'].includes(candidate.state)) {
      const { plan } = candidate,
        long = plan.direction === 'long'
      const stopHit = long ? b.low <= plan.stop : b.high >= plan.stop,
        targetHit = long ? b.high >= plan.target : b.low <= plan.target
      if (candidate.state === 'Armed') {
        const invalid = long ? b.low <= candidate.invalid : b.high >= candidate.invalid
        const touched = long ? b.high >= plan.entry : b.low <= plan.entry
        const gap = long ? b.open > plan.entry + tick : b.open < plan.entry - tick
        if (touched && gap) candidate.state = 'Missed entry'
        else if (touched && invalid) candidate.state = 'Ambiguous candle'
        else if (invalid) candidate.state = 'Invalidated'
        else if (touched)
          candidate.state = stopHit
            ? 'Ambiguous candle'
            : targetHit
              ? 'Target reached'
              : 'Entry touched'
        else if (i >= candidate.index + 2) candidate.state = 'Expired'
      } else if (stopHit) candidate.state = targetHit ? 'SL / target same candle' : 'SL reached'
      else if (targetHit) candidate.state = 'Target reached'
      lastResult = {
        plan,
        reason:
          candidate.state === 'Entry touched'
            ? 'Chart price touched entry; this does not confirm a broker fill.'
            : '',
        status: candidate.state,
      }
      if (['Armed', 'Entry touched'].includes(candidate.state)) continue
    }
    if (breakout) {
      const long = breakout.direction === 'long',
        level = breakout.level,
        atr = data.atrs[i]
      const buffer = Math.max(tick, (atr ?? 0) * 0.1)
      if (
        i > breakout.index + 3 ||
        permitted !== breakout.direction ||
        (long ? b.close < level - buffer : b.close > level + buffer)
      )
        breakout = null
      else if (
        long
          ? b.low <= level + buffer && b.close > level && b.close > b.open
          : b.high >= level - buffer && b.close < level && b.close < b.open
      ) {
        const entry = long ? snap(b.high + tick, tick, true) : snap(b.low - tick, tick)
        const result = build(entry, tick, breakout.direction, atr, long ? b.low : b.high, asOf)
        if (result.plan) {
          candidate = {
            plan: result.plan,
            index: i,
            invalid: long ? b.low : b.high,
            state: 'Armed',
          }
          lastResult = { ...result, status: 'Armed' }
        } else lastResult = result
        breakout = null
        continue
      }
    }
    if (!breakout && permitted !== 'none' && data.atrs[i]) {
      const points: Pivot[] = permitted === 'long' ? data.highs : data.lows
      const pivot: Pivot | undefined = points.filter((p: Pivot) => p.knownAt <= b.time).at(-1)
      if (
        pivot &&
        (permitted === 'long'
          ? previous.close <= pivot.price && b.close > pivot.price
          : previous.close >= pivot.price && b.close < pivot.price)
      )
        breakout = { index: i, level: pivot.price, direction: permitted }
    }
  }
  if (breakout && (!candidate || !['Armed', 'Entry touched'].includes(candidate.state)))
    return {
      plan: null,
      reason: 'Breakout confirmed; waiting for a retest close.',
      status: 'Waiting for retest',
    }
  if (!trend.highs.length || !trend.lows.length)
    return {
      plan: null,
      reason: 'Waiting for confirmed 15-minute directional structure.',
      status: 'Waiting for trend',
    }
  return lastResult
}

/** Advance price-touch status only; the entry, stop and target remain the snapshot. */
export function advanceFrozenPlan(
  plan: EntryPlan,
  bars: readonly PlanBar[],
  tick: number,
  seconds: number
): PlanResult {
  let state = 'Armed',
    previous = plan.asOf - seconds,
    count = 0
  const long = plan.direction === 'long'
  for (const b of bars) {
    if (b.time < plan.asOf) continue
    if (!valid(b) || b.time !== previous + seconds) {
      state = 'Data gap'
      break
    }
    previous = b.time
    count++
    const stop = long ? b.low <= plan.stop : b.high >= plan.stop,
      target = long ? b.high >= plan.target : b.low <= plan.target
    if (state === 'Armed') {
      const invalid = long ? b.low <= plan.structure : b.high >= plan.structure
      const touched = long ? b.high >= plan.entry : b.low <= plan.entry
      const gap = long ? b.open > plan.entry + tick : b.open < plan.entry - tick
      if (touched && gap) state = 'Missed entry'
      else if (touched && invalid) state = 'Ambiguous candle'
      else if (invalid) state = 'Invalidated'
      else if (touched)
        state = stop ? 'Ambiguous candle' : target ? 'Target reached' : 'Entry touched'
      else if (count >= 2) state = 'Expired'
    } else if (stop) state = target ? 'SL / target same candle' : 'SL reached'
    else if (target) state = 'Target reached'
    if (!['Armed', 'Entry touched'].includes(state)) break
  }
  return {
    plan,
    status: state,
    reason:
      state === 'Entry touched'
        ? 'Chart price touched entry; this does not confirm a broker fill.'
        : '',
  }
}
