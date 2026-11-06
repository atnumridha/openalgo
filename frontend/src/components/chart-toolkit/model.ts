import type { PlanSession } from '../neo-desk/chartTradePlan'
// Visual analysis only. UTC epoch seconds throughout; no order/execution dependencies.
export interface Bar {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}
export type Direction = 'BULL' | 'BEAR' | 'WAIT'
export interface Decision {
  status: Direction
  reason: string
  rsiAge: number | null
  crossAge: number | null
}
export interface Metrics {
  ema9: number | null
  emaSlow: number | null
  rsi: number | null
  macd: number | null
  signal: number | null
  histogram: number | null
  imi: number | null
  mfi: number | null
  atr: number
  bbHigh: number | null
  bbLow: number | null
  bbWidth: number | null
}
export interface Zone {
  id: number
  time: number
  confirmedTime: number
  high: number
  low: number
  above: boolean
}
export interface Pool {
  time: number
  confirmedTime: number
  level: number
  high: number
  low: number
  above: boolean
  touches: number
  state: 'active' | 'taken' | 'swept'
  end?: number
  lastIndex: number
}
export interface Pivot {
  index: number
  time: number
  price: number
  above: boolean
}
export interface Trend {
  start: Pivot
  end: Pivot
  above: boolean
  slope: number
}
export interface Signal {
  time: number
  price: number
  side: 'BULL' | 'BEAR'
}
export interface PriceEvent {
  time: number
  price: number
  kind: 'breakout-up' | 'breakout-down' | 'sweep-high' | 'sweep-low'
}
export interface Reference {
  name: string
  price: number
  time: number
  color: string
}
export interface ToolkitConfig {
  slow: 15 | 21
  left: number
  right: number
  window: number
  markerLimit: number
  zonesPerSide: number
}
export const defaults: ToolkitConfig = {
  slow: 15,
  left: 10,
  right: 5,
  window: 5,
  markerLimit: 4,
  zonesPerSide: 2,
}
export const colors = {
  bull: '#26a69a',
  bear: '#ef5350',
  fast: '#3988ff',
  slow: '#f5a623',
  highLiq: '#e8b552',
  lowLiq: '#b596ff',
  day: '#a7b0c0',
  four: '#00b8d4',
  hour: '#ce70e3',
}
export interface Result {
  revision: string
  current: Metrics
  confirmed: Decision
  preview: Decision
  closedTime: number | null
  points: Array<{ time: number; metrics: Metrics }>
  signals: Signal[]
  allSignals: Signal[]
  zones: Zone[]
  pools: Pool[]
  trends: Trend[]
  events: PriceEvent[]
  sourceCount: number
}
interface Timing {
  bullExit: number
  bearExit: number
  bullCross: number
  bearCross: number
  usedBull: number
  usedBear: number
}
export const emptyTiming = (): Timing => ({
  bullExit: -Infinity,
  bearExit: -Infinity,
  bullCross: -Infinity,
  bearCross: -Infinity,
  usedBull: -Infinity,
  usedBear: -Infinity,
})
interface SetupInput {
  rsi: number | null
  previousRsi: number | null
  macd: number | null
  previousMacd: number | null
  signal: number | null
  previousSignal: number | null
  histogram: number | null
  previousHistogram: number | null
}
export function advanceSetup(s: Timing, m: SetupInput, i: number, window = 5): Decision {
  const wait = (reason: string): Decision => ({
    status: 'WAIT',
    reason,
    rsiAge: null,
    crossAge: null,
  })
  if (Object.values(m).some((v) => v == null || !Number.isFinite(v)))
    return wait('Indicators warming up')
  const rsi = m.rsi!,
    previousRsi = m.previousRsi!,
    histogram = m.histogram!
  if (rsi > 30 && previousRsi <= 30) s.bullExit = i
  if (rsi < 70 && previousRsi >= 70) s.bearExit = i
  if (m.macd! > m.signal! && m.previousMacd! <= m.previousSignal!) s.bullCross = i
  if (m.macd! < m.signal! && m.previousMacd! >= m.previousSignal!) s.bearCross = i
  const bull = s.bullExit > s.bearExit,
    exit = bull ? s.bullExit : s.bearExit,
    cross = bull ? s.bullCross : s.bearCross
  const rsiAge = Number.isFinite(exit) ? i - exit : null,
    crossAge = Number.isFinite(cross) ? i - cross : null
  const reason =
    rsiAge == null || rsiAge > window || rsi <= 30 || rsi >= 70
      ? 'Wait for a fresh RSI exit from 30 / 70'
      : exit <= (bull ? s.usedBull : s.usedBear)
        ? 'RSI exit used · wait for a new setup'
        : crossAge == null ||
            crossAge > window ||
            (bull ? s.bullCross < s.bearCross : s.bearCross < s.bullCross)
          ? 'Wait for a matching MACD cross'
          : bull
            ? histogram <= 0 || histogram <= m.previousHistogram!
              ? 'Bull momentum is not building'
              : ''
            : histogram >= 0 || histogram >= m.previousHistogram!
              ? 'Bear momentum is not building'
              : ''
  if (reason) return { status: 'WAIT', reason, rsiAge, crossAge }
  if (bull) s.usedBull = exit
  else s.usedBear = exit
  return {
    status: bull ? 'BULL' : 'BEAR',
    reason: 'Price checks pass · IV is separate',
    rsiAge,
    crossAge,
  }
}

export const ema = (previous: number | null, value: number, length: number) =>
  previous == null ? value : previous + (2 / (length + 1)) * (value - previous)
const sum = (values: number[]) => values.reduce((a, b) => a + b, 0)
const oscillator = (up: number, down: number) =>
  up + down === 0 ? 50 : down === 0 ? 100 : up === 0 ? 0 : 100 - 100 / (1 + up / down)
interface NumericState {
  fast: number | null
  slow: number | null
  mFast: number | null
  mSlow: number | null
  signal: number | null
  gain: number | null
  loss: number | null
  atr: number | null
}
const freshNumeric = (): NumericState => ({
  fast: null,
  slow: null,
  mFast: null,
  mSlow: null,
  signal: null,
  gain: null,
  loss: null,
  atr: null,
})
function metricsAt(bars: Bar[], i: number, s: NumericState, slow: number): Metrics {
  const b = bars[i],
    previous = bars[i - 1]
  s.fast = ema(s.fast, b.close, 9)
  s.slow = ema(s.slow, b.close, slow)
  s.mFast = ema(s.mFast, b.close, 12)
  s.mSlow = ema(s.mSlow, b.close, 26)
  const macd = s.mFast - s.mSlow
  s.signal = ema(s.signal, macd, 9)
  const delta = previous ? b.close - previous.close : 0
  if (i === 14) {
    const changes = bars.slice(1, 15).map((x, j) => x.close - bars[j].close)
    s.gain = sum(changes.map((v) => Math.max(0, v))) / 14
    s.loss = sum(changes.map((v) => Math.max(0, -v))) / 14
  } else if (i > 14) {
    s.gain = (s.gain! * 13 + Math.max(0, delta)) / 14
    s.loss = (s.loss! * 13 + Math.max(0, -delta)) / 14
  }
  const tr = (x: Bar, prior?: Bar) =>
    prior
      ? Math.max(x.high - x.low, Math.abs(x.high - prior.close), Math.abs(x.low - prior.close))
      : x.high - x.low
  if (i === 13) s.atr = sum(bars.slice(0, 14).map((x, j) => tr(x, bars[j - 1]))) / 14
  else if (i > 13) s.atr = (s.atr! * 13 + tr(b, previous)) / 14
  const recent = bars.slice(Math.max(0, i - 13), i + 1)
  const imi =
    i < 13
      ? null
      : oscillator(
          sum(recent.map((x) => Math.max(x.close - x.open, 0))),
          sum(recent.map((x) => Math.max(x.open - x.close, 0)))
        )
  let mfi: number | null = null
  if (i >= 14 && recent.every((x) => Number.isFinite(x.volume) && x.volume > 0)) {
    let pos = 0,
      neg = 0
    const typical = (x: Bar) => (x.high + x.low + x.close) / 3
    for (let j = i - 13; j <= i; j++) {
      const flow = typical(bars[j]) * bars[j].volume,
        change = typical(bars[j]) - typical(bars[j - 1])
      if (change > 0) pos += flow
      if (change < 0) neg += flow
    }
    mfi = oscillator(pos, neg)
  }
  const closes = bars.slice(Math.max(0, i - 19), i + 1).map((x) => x.close),
    mean = sum(closes) / closes.length
  const deviation = Math.sqrt(sum(closes.map((c) => (c - mean) ** 2)) / closes.length)
  return {
    ema9: s.fast,
    emaSlow: s.slow,
    rsi: i >= 14 ? oscillator(s.gain!, s.loss!) : null,
    macd: i >= 25 ? macd : null,
    signal: i >= 33 ? s.signal : null,
    histogram: i >= 33 ? macd - s.signal : null,
    imi,
    mfi,
    atr: s.atr ?? Math.max(b.high - b.low, b.close * 0.001),
    bbHigh: i >= 19 ? mean + 2 * deviation : null,
    bbLow: i >= 19 ? mean - 2 * deviation : null,
    bbWidth: i >= 19 && mean > 0 ? (400 * deviation) / mean : null,
  }
}
const setupInput = (current: Metrics, previous?: Metrics): SetupInput => ({
  rsi: current.rsi,
  previousRsi: previous?.rsi ?? null,
  macd: current.macd,
  previousMacd: previous?.macd ?? null,
  signal: current.signal,
  previousSignal: previous?.signal ?? null,
  histogram: current.histogram,
  previousHistogram: previous?.histogram ?? null,
})
export function breakoutStrength(
  b: Pick<Bar, 'open' | 'high' | 'low' | 'close'>,
  atr: number,
  up: boolean
) {
  const range = b.high - b.low,
    body = Math.abs(b.close - b.open)
  return (
    range > 0 &&
    body / range >= 0.55 &&
    body >= 0.5 * atr &&
    (up
      ? b.close > b.open && b.high - b.close <= 0.25 * range
      : b.close < b.open && b.close - b.low <= 0.25 * range)
  )
}

// Market timestamps are actual UTC. Exchange bars stop at the cash session close;
// crypto bars remain 24/7. Daily candles use the exchange date, not +24h from 09:15.
export function sessionBounds(time: number, indian: boolean) {
  const day = Math.floor((time + (indian ? 19800 : 0)) / 86400) * 86400 - (indian ? 19800 : 0)
  return { start: day + (indian ? 33300 : 0), end: day + (indian ? 55800 : 86400), day }
}
export function closeTime(bar: Bar, seconds: number, indian = false, window?: PlanSession | null) {
  if (window) {
    const day = Math.floor((bar.time + window.offset) / 86400) * 86400 - window.offset
    return seconds >= 86400
      ? day + window.end * 60
      : Math.min(bar.time + seconds, day + window.end * 60)
  }
  if (!indian) return bar.time + seconds
  const session = sessionBounds(bar.time, true)
  return seconds >= 86400 ? session.end : Math.min(bar.time + seconds, session.end)
}

function validTrends(pivots: Pivot[], bars: Bar[], atr: number): Trend[] {
  const result: Trend[] = []
  for (const above of [false, true]) {
    const candidates = pivots
      .filter((p) => p.above === above && bars.length - 1 - p.index <= 500)
      .slice(-16)
    let found: Trend | undefined
    for (let j = candidates.length - 1; j > 0 && !found; j--) {
      const end = candidates[j]
      for (let k = j - 1; k >= 0; k--) {
        const start = candidates[k],
          slope = (end.price - start.price) / (end.index - start.index)
        if (above ? slope >= 0 : slope <= 0) continue
        let valid = true
        for (let n = start.index; n < bars.length; n++) {
          const line = start.price + slope * (n - start.index)
          if (above ? bars[n].high > line + atr * 0.05 : bars[n].low < line - atr * 0.05) {
            valid = false
            break
          }
        }
        if (valid) {
          found = { start, end, slope, above }
          break
        }
      }
    }
    if (found) result.push(found)
  }
  return result
}
interface ClosedState {
  segmentStart: number
  points: Result['points']
  signals: Signal[]
  zones: Zone[]
  pools: Pool[]
  pivots: Pivot[]
  events: PriceEvent[]
  numeric: NumericState
  timing: Timing
  confirmed: Decision
}
const emptyState = (): ClosedState => ({
  segmentStart: 0,
  points: [],
  signals: [],
  zones: [],
  pools: [],
  pivots: [],
  events: [],
  numeric: freshNumeric(),
  timing: emptyTiming(),
  confirmed: { status: 'WAIT', reason: 'Indicators warming up', rsiAge: null, crossAge: null },
})
export class ToolkitEngine {
  private key = ''
  private state = emptyState()
  private trends: Trend[] = []
  private config: ToolkitConfig
  constructor(config: Partial<ToolkitConfig> = {}) {
    this.config = { ...defaults, ...config }
  }
  update(
    input: Bar[],
    {
      seconds,
      asOf,
      indian = false,
      continuous = false,
      session,
    }: {
      seconds: number
      asOf: number
      indian?: boolean
      continuous?: boolean
      session?: PlanSession | null
    }
  ): Result {
    // Hash the entire closed prefix so broker corrections invalidate the cache.
    const bars = input.filter(
      (b) =>
        b.time <= asOf &&
        [b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) &&
        b.close > 0 &&
        b.high >= Math.max(b.open, b.close) &&
        b.low <= Math.min(b.open, b.close)
    )
    const closed = bars.filter((b) => closeTime(b, seconds, indian, session) <= asOf)
    let hash = 2166136261
    const bytes = new DataView(new ArrayBuffer(8))
    for (const b of closed)
      for (const v of [b.time, b.open, b.high, b.low, b.close, b.volume]) {
        bytes.setFloat64(0, v)
        hash = Math.imul(hash ^ bytes.getUint32(0), 16777619) >>> 0
        hash = Math.imul(hash ^ bytes.getUint32(4), 16777619) >>> 0
      }
    const key = `${seconds}:${indian}:${continuous}:${JSON.stringify(session)}:${closed.length}:${hash}`
    if (key !== this.key) {
      this.state = this.calculate(closed, seconds, continuous)
      this.trends = validTrends(
        this.state.pivots,
        closed,
        this.state.points.at(-1)?.metrics.atr ?? 0
      )
      this.key = key
    }
    const s = this.state,
      last = s.points.at(-1),
      live = bars.at(-1)
    const current =
      live && closeTime(live, seconds, indian, session) > asOf
        ? metricsAt(
            bars.slice(s.segmentStart),
            bars.length - 1 - s.segmentStart,
            { ...s.numeric },
            this.config.slow
          )
        : (last?.metrics ??
          metricsAt(
            [{ time: 0, open: 0, high: 0, low: 0, close: 0, volume: 0 }],
            0,
            freshNumeric(),
            this.config.slow
          ))
    const preview =
      live && closeTime(live, seconds, indian, session) > asOf
        ? advanceSetup(
            { ...s.timing },
            setupInput(current, last?.metrics),
            closed.length,
            this.config.window
          )
        : s.confirmed
    const price = closed.at(-1)?.close ?? live?.close ?? 0
    const zones = [false, true].flatMap((above) =>
      s.zones
        .filter((z) => z.above === above && (above ? z.high >= price : z.low <= price))
        .sort(
          (a, b) => Math.abs((a.high + a.low) / 2 - price) - Math.abs((b.high + b.low) / 2 - price)
        )
        .slice(0, this.config.zonesPerSide)
    )
    return {
      revision: key,
      current,
      confirmed: s.confirmed,
      preview,
      closedTime: last?.time ?? null,
      points: [
        ...s.points,
        ...(live && closeTime(live, seconds, indian, session) > asOf
          ? [{ time: live.time, metrics: current }]
          : []),
      ],
      signals: s.signals.slice(-this.config.markerLimit),
      allSignals: s.signals,
      zones,
      pools: s.pools.filter((p) => p.touches >= 2).slice(-12),
      trends: this.trends,
      events: s.events.slice(-4),
      sourceCount: bars.length,
    }
  }
  private calculate(bars: Bar[], seconds: number, continuous: boolean): ClosedState {
    const s = emptyState(),
      c = this.config
    let segment = bars
    for (let i = 0; i < bars.length; i++) {
      const b = bars[i],
        previous = bars[i - 1]
      if (continuous && previous && b.time - previous.time !== seconds) {
        s.segmentStart = i
        segment = bars.slice(i)
        s.numeric = freshNumeric()
        s.timing = emptyTiming()
        s.zones = []
        s.pools = []
        s.pivots = []
      }
      const priorMetrics = i > s.segmentStart ? s.points.at(-1)?.metrics : undefined
      const metrics = metricsAt(segment, i - s.segmentStart, s.numeric, c.slow),
        atr = priorMetrics?.atr ?? metrics.atr
      const decision = advanceSetup(s.timing, setupInput(metrics, priorMetrics), i, c.window)
      if (i - s.segmentStart < 34) {
        decision.status = 'WAIT'
        decision.reason = 'Indicators warming up'
      }
      s.confirmed = decision
      s.points.push({ time: b.time, metrics })
      if (decision.status !== 'WAIT')
        s.signals.push({
          time: b.time,
          price: decision.status === 'BULL' ? b.low : b.high,
          side: decision.status,
        })
      let up: number | null = null,
        down: number | null = null
      // Consume the levels that were active before this bar. New pivots cannot
      // retroactively create a breakout on the candle that confirms them.
      s.pools = s.pools.filter((p) => i - p.lastIndex <= 500 || p.state !== 'active')
      for (const p of s.pools) {
        if (p.state !== 'active' || p.touches < 2 || p.confirmedTime >= b.time) continue
        const touched = p.above ? b.high > p.high : b.low < p.low
        if (!touched) continue
        const swept = p.above ? b.close <= p.high : b.close >= p.low
        p.state = swept ? 'swept' : 'taken'
        p.end = b.time
        if (swept)
          s.events.push({
            time: b.time,
            price: p.level,
            kind: p.above ? 'sweep-high' : 'sweep-low',
          })
        if (
          previous &&
          (p.above
            ? previous.close <= p.high && b.close > p.high + 0.05 * atr
            : previous.close >= p.low && b.close < p.low - 0.05 * atr)
        ) {
          if (p.above) up = p.high
          else down = p.low
        }
      }
      s.zones = s.zones.filter((z) => {
        const broken = z.above ? b.close > z.high : b.close < z.low
        if (
          broken &&
          previous &&
          (z.above
            ? previous.close <= z.high && b.close > z.high + 0.05 * atr
            : previous.close >= z.low && b.close < z.low - 0.05 * atr)
        ) {
          if (z.above) up = z.high
          else down = z.low
        }
        return !broken
      })
      if (up != null && breakoutStrength(b, atr, true))
        s.events.push({ time: b.time, price: up, kind: 'breakout-up' })
      if (down != null && breakoutStrength(b, atr, false))
        s.events.push({ time: b.time, price: down, kind: 'breakout-down' })
      const pIndex = i - c.right
      if (pIndex - c.left >= s.segmentStart)
        for (const above of [true, false]) {
          const pivot = bars[pIndex],
            value = above ? pivot.high : pivot.low
          // Strict left side, inclusive right side gives one deterministic pivot
          // for flat highs/lows and avoids using any future bars.
          const left = bars.slice(pIndex - c.left, pIndex),
            right = bars.slice(pIndex + 1, i + 1)
          if (
            !left.every((x) => (above ? x.high < value : x.low > value)) ||
            !right.every((x) => (above ? x.high <= value : x.low >= value))
          )
            continue
          const width = Math.max(s.points[pIndex].metrics.atr * 0.25, value * 0.000001)
          const high = above ? value : value + width,
            low = above ? value - width : value
          s.pivots.push({ index: pIndex, time: pivot.time, price: value, above })
          if (!(above ? b.close > high : b.close < low)) {
            const existing = s.zones.find(
              (z) => z.above === above && Math.abs((above ? z.high : z.low) - value) <= width
            )
            if (!existing)
              s.zones.push({
                id: pIndex * 2 + Number(above),
                time: pivot.time,
                confirmedTime: b.time,
                high,
                low,
                above,
              })
          }
          const tolerance = s.points[pIndex].metrics.atr * 0.15
          const pool = [...s.pools]
            .reverse()
            .find(
              (p) =>
                p.above === above && p.state === 'active' && Math.abs(p.level - value) <= tolerance
            )
          if (pool) {
            pool.level = (pool.level * pool.touches + value) / (pool.touches + 1)
            pool.touches++
            pool.lastIndex = pIndex
            pool.high = Math.max(pool.high, value + tolerance / 2)
            pool.low = Math.min(pool.low, value - tolerance / 2)
            pool.confirmedTime = b.time
            // A pool taken during its confirmation delay cannot become active now.
            const after = bars.slice(pIndex + 1, i + 1)
            if (after.some((x) => (above ? x.high > pool.high : x.low < pool.low))) {
              pool.state = 'taken'
              pool.end = b.time
            }
          } else
            s.pools.push({
              time: pivot.time,
              confirmedTime: b.time,
              level: value,
              high: value + tolerance / 2,
              low: value - tolerance / 2,
              above,
              touches: 1,
              state: 'active',
              lastIndex: pIndex,
            })
          if (s.zones.length > 60) s.zones.shift()
          if (s.pools.length > 80) s.pools.shift()
          if (s.pivots.length > 200) s.pivots.shift()
        }
    }
    return s
  }
}

export function completedReferences(
  bars: Bar[],
  sourceSeconds: number,
  asOf: number,
  indian: boolean
): Reference[] {
  const result: Reference[] = []
  for (const [seconds, label, color] of [
    [3600, '1H', colors.hour],
    [14400, '4H', colors.four],
    [86400, '1D', colors.day],
  ] as const) {
    if (sourceSeconds > seconds || seconds % sourceSeconds !== 0) continue
    const buckets = new Map<
      number,
      { high: number; low: number; end: number; first: number; lastEnd: number; count: number }
    >()
    for (const b of bars) {
      const sourceEnd = closeTime(b, sourceSeconds, indian)
      if (sourceEnd > asOf) continue
      const session = sessionBounds(b.time, indian)
      const anchor = seconds === 86400 ? session.day : session.start
      const time =
        seconds === 86400 ? anchor : anchor + Math.floor((b.time - anchor) / seconds) * seconds
      const end = indian ? Math.min(time + seconds, session.end) : time + seconds
      const old = buckets.get(time)
      buckets.set(time, {
        high: Math.max(old?.high ?? -Infinity, b.high),
        low: Math.min(old?.low ?? Infinity, b.low),
        end,
        first: old?.first ?? b.time,
        lastEnd: sourceEnd,
        count: (old?.count ?? 0) + 1,
      })
    }
    const done = [...buckets]
      .filter(
        ([time, b]) =>
          b.end <= asOf &&
          b.lastEnd >= b.end &&
          b.first <= (seconds === 86400 && indian ? sessionBounds(time, true).start : time) &&
          b.count >= Math.ceil((b.end - b.first) / sourceSeconds)
      )
      .at(-1)
    if (done) {
      result.push(
        { name: `${label} High`, price: done[1].high, time: done[0], color },
        { name: `${label} Low`, price: done[1].low, time: done[0], color }
      )
    }
  }
  return result
}

function cdf(x: number) {
  const a = Math.abs(x),
    t = 1 / (1 + 0.2316419 * a)
  const tail =
    0.3989422804014327 *
    Math.exp(-0.5 * a * a) *
    t *
    (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
  return x >= 0 ? 1 - tail : tail
}
export function optionPrice(
  spot: number,
  strike: number,
  years: number,
  rate: number,
  yieldRate: number,
  sigma: number,
  call: boolean
) {
  const root = Math.sqrt(years),
    d1 =
      (Math.log(spot / strike) + (rate - yieldRate + (sigma * sigma) / 2) * years) / (sigma * root),
    d2 = d1 - sigma * root
  const s = spot * Math.exp(-yieldRate * years),
    k = strike * Math.exp(-rate * years)
  return call ? s * cdf(d1) - k * cdf(d2) : k * cdf(-d2) - s * cdf(-d1)
}
export function impliedVolatility(
  premium: number,
  spot: number,
  strike: number,
  years: number,
  rate: number,
  yieldRate: number,
  call: boolean
): number | null {
  if (
    ![premium, spot, strike, years, rate, yieldRate].every(Number.isFinite) ||
    Math.min(premium, spot, strike, years) <= 0 ||
    years > 10
  )
    return null
  let low = 0.0001,
    high = 5
  if (
    premium < optionPrice(spot, strike, years, rate, yieldRate, low, call) - 0.00001 ||
    premium > optionPrice(spot, strike, years, rate, yieldRate, high, call) + 0.00001
  )
    return null
  for (let i = 0; i < 40; i++) {
    const mid = (low + high) / 2
    if (optionPrice(spot, strike, years, rate, yieldRate, mid, call) > premium) high = mid
    else low = mid
  }
  return (low + high) * 50
}
export function matchOptionSnapshot(option: Bar[], spot: Bar[], asOf: number) {
  const spots = new Map(spot.filter((b) => b.time + 60 <= asOf).map((b) => [b.time, b.close]))
  const match = [...option]
    .reverse()
    .find((b) => b.time + 60 <= asOf && b.close > 0 && (spots.get(b.time) ?? 0) > 0)
  return match
    ? {
        time: match.time,
        premium: match.close,
        spot: spots.get(match.time)!,
        fresh: asOf - (match.time + 60) <= 180,
      }
    : null
}
