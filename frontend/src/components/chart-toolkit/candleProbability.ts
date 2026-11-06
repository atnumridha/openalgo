import { closeTime, type Bar } from './model'
import { recognizePattern, type PatternSelection } from './candlePatterns'
import type {
  CandleCounts,
  CandleEstimate,
  CandleGeometry,
  CandleModel,
  CandleOptions,
  CandleOutcome,
  CandleSetup,
  CandleStudy,
} from './candleProbabilityTypes'

const emptyCounts = (): CandleCounts => ({ targets: 0, stops: 0, timeouts: 0, ambiguous: 0 })
export function evidenceEstimate(counts: CandleCounts): CandleEstimate {
  const n = counts.targets + counts.stops + counts.timeouts
  if (!n) return { samples: 0, targets: 0, probability: null, lower: null, upper: null }
  const p = counts.targets / n,
    z2 = 1.96 ** 2,
    denominator = 1 + z2 / n
  const center = (p + z2 / (2 * n)) / denominator
  const radius = (1.96 * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / denominator
  return {
    samples: n,
    targets: counts.targets,
    probability: (counts.targets + 1) / (n + 2),
    lower: Math.max(0, center - radius),
    upper: Math.min(1, center + radius),
  }
}

/** Pure price geometry; no instrument-specific rules and no volume dependency. */
export function detectPattern(
  history: Bar[],
  selected: PatternSelection = 'all'
): CandleGeometry | null {
  if (history.length < 11) return null
  const c = history.at(-1)!
  const previous = history.slice(-11, -1)
  const recent = history.slice(-10)
  const atr =
    recent.reduce((sum, b, i) => {
      const before = i ? recent[i - 1].close : previous[0].close
      return sum + Math.max(b.high - b.low, Math.abs(b.high - before), Math.abs(b.low - before))
    }, 0) / 10
  if (!(atr > 0)) return null
  const recognized = recognizePattern(history, selected)
  if (!recognized) return null
  const { side, pattern, name, extreme } = recognized
  const direction = side === 'CALL' ? 1 : -1
  const move = previous.at(-1)!.close - previous[0].close
  const context =
    Math.abs(move) <= 0.5 * atr ? 'flat' : move * direction > 0 ? 'aligned' : 'opposing'
  const risk = Math.max(direction * (c.close - extreme) + 0.1 * atr, 0.5 * atr)
  return {
    side,
    pattern,
    name,
    context,
    key: `${pattern}:${side}:${context}`,
    entry: c.close,
    stop: c.close - direction * risk,
    target: c.close + direction * 2 * risk,
    support: Math.min(...previous.map((b) => b.low)),
    resistance: Math.max(...previous.map((b) => b.high)),
  }
}

function session(time: number, o: CandleOptions) {
  const window = o.session ?? { start: 555, end: 930, offset: 19800 }
  const day = Math.floor((time + window.offset) / 86400) * 86400 - window.offset
  return { start: day + window.start * 60, end: day + window.end * 60 }
}
const sessionKey = (o: Pick<CandleOptions, 'indian' | 'session'>) =>
  JSON.stringify(o.session ?? (o.indian ? { start: 555, end: 930, offset: 19800 } : null))
function valid(b: Bar) {
  return (
    [b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) &&
    b.high >= Math.max(b.open, b.close) &&
    b.low <= Math.min(b.open, b.close) &&
    b.high >= b.low
  )
}
function follows(previous: Bar, next: Bar, o: CandleOptions) {
  if (next.time === previous.time + o.seconds) return true
  // Indian daily history has no Saturday/Sunday bars. Missing weekdays remain
  // unknown: no holiday calendar is silently inferred from absent prices.
  if (
    !(o.indian || o.session) ||
    o.seconds !== 86400 ||
    next.time - previous.time > 3 * 86400 ||
    (next.time - previous.time) % 86400 !== 0
  )
    return false
  for (let time = previous.time + 86400; time < next.time; time += 86400) {
    const day = new Date((time + (o.session?.offset ?? 19800)) * 1000).getUTCDay()
    if (day !== 0 && day !== 6) return false
  }
  return true
}
function seedMatches(seed: CandleModel | undefined, o: CandleOptions): seed is CandleModel {
  return (
    !!seed &&
    seed.version === 1 &&
    seed.symbol === o.symbol &&
    seed.exchange === o.exchange &&
    seed.seconds === o.seconds &&
    seed.indian === o.indian &&
    sessionKey(seed) === sessionKey(o) &&
    (seed.tickSize ?? 0) === (o.tickSize ?? 0) &&
    (seed.pattern ?? 'all') === (o.pattern ?? 'all') &&
    Number.isFinite(seed.trainedThrough) &&
    seed.trainedThrough <= o.asOf &&
    !!seed.counts &&
    Object.values(seed.counts).every(
      (c) =>
        [c.targets, c.stops, c.timeouts, c.ambiguous].every(
          (n) => Number.isSafeInteger(n) && n >= 0
        ) && c.ambiguous <= c.stops
    )
  )
}

/** One reference observation at a time, updated only when its outcome becomes known. */
export function analyzeCandles(raw: Bar[], o: CandleOptions, seed?: CandleModel): CandleStudy {
  const seedUsed = seedMatches(seed, o)
  const model: CandleModel = {
    version: 1,
    symbol: o.symbol,
    exchange: o.exchange,
    seconds: o.seconds,
    indian: o.indian,
    session: o.session,
    tickSize: o.tickSize,
    pattern: o.pattern,
    trainedThrough: seedUsed ? seed.trainedThrough : 0,
    source: seedUsed ? seed.source : 'Loaded chart candles',
    counts: seedUsed
      ? Object.fromEntries(Object.entries(seed.counts).map(([k, v]) => [k, { ...v }]))
      : {},
  }
  const result: CandleStudy = {
    bars: [],
    setups: [],
    outcomes: [],
    signalOutcomes: [],
    latest: null,
    lastSetup: null,
    active: null,
    lastOutcome: null,
    support: null,
    resistance: null,
    closedTime: null,
    model,
    seedUsed,
  }
  if (!(o.seconds > 0) || !Number.isFinite(o.seconds) || !Number.isFinite(o.asOf)) return result
  const intraday = !!(o.indian || o.session) && o.seconds < 86400
  const closes = (b: Bar) => closeTime(b, o.seconds, o.indian, o.session)
  const byTime = new Map<number, Bar>(),
    rejected = new Set<number>()
  let latestInput = 0
  for (const b of raw) {
    if (!Number.isFinite(b.time) || closes(b) > o.asOf) continue
    if (intraday && (b.time < session(b.time, o).start || b.time >= session(b.time, o).end))
      continue
    latestInput = Math.max(latestInput, b.time)
    const old = byTime.get(b.time)
    if (
      !valid(b) ||
      (old &&
        [old.open !== b.open, old.high !== b.high, old.low !== b.low, old.close !== b.close].some(
          Boolean
        ))
    ) {
      rejected.add(b.time)
      byTime.delete(b.time)
    } else if (!rejected.has(b.time)) byTime.set(b.time, b)
  }
  result.bars = [...byTime.values()].sort((a, b) => a.time - b.time)
  const threshold =
    Number.isFinite(o.minProbability) && o.minProbability! >= 0 && o.minProbability! <= 1
      ? o.minProbability!
      : 0.8
  const minimum = Number.isSafeInteger(o.minSamples) && o.minSamples! > 0 ? o.minSamples! : 50
  const cutoff = seedUsed ? seed.trainedThrough : -Infinity
  let segment: Bar[] = [],
    learning: CandleSetup | null = null,
    signal: CandleSetup | null = null
  let learningAge = 0,
    signalAge = 0
  function settle(setup: CandleSetup, b: Bar, gap: boolean, age: number): CandleOutcome | null {
    const direction = setup.side === 'CALL' ? 1 : -1
    const risk = Math.abs(setup.entry - setup.stop)
    if (gap)
      return { setup, time: b.time, result: 'UNKNOWN', ambiguous: false, price: null, r: null }
    const stop = direction === 1 ? b.low <= setup.stop : b.high >= setup.stop
    const target = direction === 1 ? b.high >= setup.target : b.low <= setup.target
    if (stop) {
      const price = direction === 1 ? Math.min(b.open, setup.stop) : Math.max(b.open, setup.stop)
      return {
        setup,
        time: b.time,
        result: 'STOP',
        ambiguous: target,
        price,
        r: (direction * (price - setup.entry)) / risk,
      }
    }
    if (target)
      return { setup, time: b.time, result: 'TARGET', ambiguous: false, price: setup.target, r: 2 }
    if (age >= 10)
      return {
        setup,
        time: b.time,
        result: 'TIMEOUT',
        ambiguous: false,
        price: b.close,
        r: (direction * (b.close - setup.entry)) / risk,
      }
    return null
  }
  for (const b of result.bars) {
    const previous = segment.at(-1)
    const gap =
      !!previous &&
      (!follows(previous, b, o) ||
        (intraday && session(b.time, o).start !== session(previous.time, o).start))
    if (learning) {
      const outcome = settle(learning, b, gap, ++learningAge)
      if (outcome) {
        result.outcomes.push(outcome)
        if (outcome.result !== 'UNKNOWN') {
          const counts = model.counts[learning.key] ?? (model.counts[learning.key] = emptyCounts())
          if (outcome.result === 'TARGET') counts.targets++
          else if (outcome.result === 'STOP') counts.stops++
          else counts.timeouts++
          if (outcome.ambiguous) counts.ambiguous++
        }
        learning = null
      }
    }
    if (signal) {
      const outcome = settle(signal, b, gap, ++signalAge)
      if (outcome) {
        result.signalOutcomes.push(outcome)
        result.lastOutcome = outcome
        signal = null
      }
    }
    if (gap) segment = []
    segment.push(b)
    if (segment.length > 11) segment.shift()
    result.closedTime = b.time
    if (segment.length >= 11) {
      result.support = Math.min(...segment.slice(0, -1).map((x) => x.low))
      result.resistance = Math.max(...segment.slice(0, -1).map((x) => x.high))
    } else {
      result.support = null
      result.resistance = null
    }
    if (closes(b) <= cutoff) continue
    model.trainedThrough = Math.max(model.trainedThrough, closes(b))
    const detected = detectPattern(segment, o.pattern)
    if (!detected) continue
    let geometry = detected
    if (o.tickSize != null && o.tickSize > 0) {
      const tick = o.tickSize,
        bull = detected.side === 'CALL'
      if (
        !Number.isFinite(tick) ||
        Math.abs(detected.entry / tick - Math.round(detected.entry / tick)) > 1e-6
      )
        continue
      const stop = Number(
        (
          (bull ? Math.floor : Math.ceil)(detected.stop / tick + (bull ? 1e-8 : -1e-8)) * tick
        ).toFixed(8)
      )
      const target = Number((detected.entry + 2 * (detected.entry - stop)).toFixed(8))
      if (stop <= 0 || target <= 0 || stop === detected.entry) continue
      geometry = { ...detected, stop, target }
    }
    const estimate = evidenceEstimate(model.counts[geometry.key] ?? emptyCounts())
    const room = !intraday || b.time + 11 * o.seconds <= session(b.time, o).end
    const reason = !room
      ? 'Not enough session time for ten candles'
      : estimate.samples < minimum
        ? `Learning: ${estimate.samples}/${minimum} matching outcomes`
        : estimate.probability! < threshold
          ? 'Probability below signal threshold'
          : signal
            ? 'Already tracking a qualified setup'
            : 'Pattern and evidence threshold met'
    const candidate: CandleSetup = {
      ...geometry,
      time: b.time,
      estimate,
      qualified:
        room && estimate.samples >= minimum && estimate.probability! >= threshold && !signal,
      reason,
    }
    result.setups.push(candidate)
    result.lastSetup = candidate
    if (room && !learning) {
      learning = candidate
      learningAge = 0
    }
    if (candidate.qualified) {
      signal = candidate
      signalAge = 0
    }
  }
  if (result.closedTime !== null && latestInput > result.closedTime) {
    const invalid = { time: latestInput } as Bar
    if (learning) result.outcomes.push(settle(learning, invalid, true, 0)!)
    if (signal) {
      result.lastOutcome = settle(signal, invalid, true, 0)!
      result.signalOutcomes.push(result.lastOutcome)
      signal = null
    }
  }
  result.latest =
    result.lastSetup?.time === result.closedTime && result.closedTime === latestInput
      ? result.lastSetup
      : null
  result.active = signal
  return result
}
