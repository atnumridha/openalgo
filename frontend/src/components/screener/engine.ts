import { ToolkitEngine, closeTime, ema, type Bar } from '../chart-toolkit/model'
import { adjacent } from '../neo-desk/chartTradePlan'
import { detectPattern } from '../chart-toolkit/candleProbability'
import { isPatternSelection } from '../chart-toolkit/candlePatterns'
import { resolveIndicatorChart } from '../chart-toolkit/indicatorChartContext'
import {
  FIELDS,
  OPS,
  FRAMES,
  frameSeconds,
  type ScreenDefinition,
  type RuleNode,
  type Operand,
  type ScanDataset,
  type ScanRow,
} from './model'
const fail = () => {
  throw Error('Use supported fields, valid values, up to 24 conditions and three nested groups.')
}
export function validateDefinition(input: unknown): ScreenDefinition {
  const d = input as ScreenDefinition
  if (
    !d ||
    d.version !== 1 ||
    typeof d.name !== 'string' ||
    !d.name.trim() ||
    d.name.length > 64 ||
    !FRAMES.includes(d.interval) ||
    !['observe', 'bullish', 'bearish'].includes(d.intent) ||
    !d.universe ||
    !['stored', 'watchlist', 'nifty50', 'custom'].includes(d.universe.kind) ||
    d.rule?.type !== 'group'
  )
    return fail()
  let leaves = 0
  const operand = (v: Operand) => {
    if (typeof v === 'number') {
      if (!Number.isFinite(v) || Math.abs(v) > 1e15) fail()
      return
    }
    if (
      !v ||
      !FIELDS.some(([k]) => k === v.field) ||
      (v.offset != null && v.offset !== 0 && v.offset !== 1)
    )
      fail()
    if (v.period != null && (!Number.isInteger(v.period) || v.period < 1 || v.period > 500)) fail()
    if (v.pattern != null && !isPatternSelection(v.pattern)) fail()
  }
  const node = (n: RuleNode, depth: number) => {
    if (
      !n ||
      typeof n.id !== 'string' ||
      !n.id ||
      n.id.length > 80 ||
      depth > 3 ||
      (n.enabled != null && typeof n.enabled !== 'boolean')
    )
      fail()
    if (n.type === 'group') {
      if (!['all', 'any'].includes(n.op) || !Array.isArray(n.children) || n.children.length > 24)
        fail()
      n.children.forEach((c) => node(c, depth + 1))
    } else if (n.type === 'condition') {
      if (++leaves > 24 || !OPS.some(([k]) => k === n.op)) fail()
      operand(n.left)
      operand(n.right)
      if (
        n.op === 'within_pct' &&
        (!(Number(n.tolerance) >= 0) || !Number.isFinite(n.tolerance) || Number(n.tolerance) > 100)
      )
        fail()
    } else fail()
  }
  node(d.rule, 0)
  if (
    d.universe.kind === 'watchlist' &&
    (!Number.isInteger(d.universe.id) || Number(d.universe.id) < 1)
  )
    fail()
  if (
    d.universe.items &&
    (!Array.isArray(d.universe.items) ||
      d.universe.items.length > 500 ||
      d.universe.items.some(
        (i) =>
          !i ||
          typeof i.symbol !== 'string' ||
          !i.symbol ||
          i.symbol.length > 100 ||
          typeof i.exchange !== 'string' ||
          !i.exchange ||
          i.exchange.length > 20
      ))
  )
    fail()
  return { ...d, name: d.name.trim() }
}
const valid = (b: Bar) =>
  [b.time, b.open, b.high, b.low, b.close].every(Number.isFinite) &&
  b.time > 0 &&
  b.low > 0 &&
  b.low <= Math.min(b.open, b.close) &&
  b.high >= Math.max(b.open, b.close)
export function evaluateScreen(
  dataset: ScanDataset,
  definition: ScreenDefinition,
  now: number
): ScanRow {
  const seconds = frameSeconds(definition.interval),
    session = dataset.session ?? undefined,
    continuous = dataset.exchange === 'DELTA'
  const base: ScanRow = {
    symbol: dataset.symbol,
    exchange: dataset.exchange,
    name: dataset.name,
    state: 'unavailable',
    fresh: false,
    direction: 'MATCH',
    time: null,
    observedAt: dataset.observedAt,
    source: dataset.source,
    reason: 'Verified candle history is unavailable',
    values: {},
  }
  if (
    dataset.error ||
    dataset.interval !== definition.interval ||
    !Number.isFinite(dataset.observedAt) ||
    dataset.observedAt > now + 2
  )
    return { ...base, reason: dataset.error || base.reason }
  const byTime = new Map<number, Bar>()
  for (const bar of dataset.candles) {
    if (!valid(bar)) return { ...base, reason: 'Source contains invalid candles' }
    const old = byTime.get(bar.time)
    if (
      old &&
      ['open', 'high', 'low', 'close', 'volume'].some(
        (k) => old[k as 'close'] !== bar[k as 'close']
      )
    )
      return { ...base, reason: 'Source contains conflicting candles' }
    byTime.set(bar.time, bar)
  }
  const asOf = Math.min(now, dataset.observedAt)
  let bars = [...byTime.values()]
    .filter((b) => {
      const minute = Math.floor(((b.time + (session?.offset ?? 0)) % 86400) / 60)
      return (
        b.time <= asOf &&
        (!session || seconds >= 86400 || (minute >= session.start && minute < session.end)) &&
        closeTime(b, seconds, !!session, session) <= asOf
      )
    })
    .sort((a, b) => a.time - b.time)
  if (!bars.length) return base
  for (let i = bars.length - 1; i > 0; i--)
    if (!adjacent(bars[i - 1], bars[i], seconds, session)) {
      bars = bars.slice(i)
      break
    }
  const last = bars.at(-1)!,
    age = now - closeTime(last, seconds, !!session, session),
    fresh = now - dataset.observedAt <= 90 && age >= 0 && age <= seconds + 90
  const engine = new ToolkitEngine(),
    cache = new Map<string, number | null>()
  const metrics = engine.update(bars, { seconds, asOf: dataset.observedAt, continuous, session })
  const day = (t: number) => Math.floor((t + (session?.offset ?? 0)) / 86400)
  const dailyBars = dataset.daily
    .filter((b) => valid(b) && closeTime(b, 86400, !!session, session) <= asOf)
    .sort((a, b) => a.time - b.time)
  const priorSession = (time: number) => {
    const candidate = dailyBars.filter((b) => day(b.time) < day(time)).at(-1)
    // A missing weekday is not an exchange holiday inferred from absent prices.
    return candidate && adjacent(
      { ...candidate, time: day(candidate.time) * 86400 },
      { ...candidate, time: day(time) * 86400 },
      86400,
      session
    ) ? candidate : undefined
  }
  const value = (ref: Operand, ago = 0): number | null => {
    if (typeof ref === 'number') return ref
    const offset = (ref.offset ?? 0) + ago,
      index = bars.length - 1 - offset,
      key = JSON.stringify([ref, ago])
    if (index < 0) return null
    if (cache.has(key)) return cache.get(key)!
    const bar = bars[index],
      previous = bars[index - 1],
      period = ref.period ?? 20,
      point = metrics.points.find((p) => p.time === bar.time)?.metrics,
      daily = priorSession(bar.time)
    let v: number | null = null
    if (['open', 'high', 'low', 'close'].includes(ref.field)) v = bar[ref.field as 'close']
    else if (ref.field === 'volume')
      v = Number.isFinite(bar.volume) && bar.volume > 0 ? bar.volume : null
    else if (ref.field === 'bar_change_pct')
      v = previous ? 100 * (bar.close / previous.close - 1) : null
    else if (ref.field === 'session_change_pct')
      v = daily ? 100 * (bar.close / daily.close - 1) : null
    else if (ref.field === 'prior_day_high') v = daily?.high ?? null
    else if (ref.field === 'prior_day_low') v = daily?.low ?? null
    else if (ref.field === 'ema' && index + 1 >= period) {
      let seed: number | null = null
      for (let i = 0; i <= index; i++) seed = ema(seed, bars[i].close, period)
      v = seed
    } else if (ref.field === 'sma' && index + 1 >= period)
      v = bars.slice(index - period + 1, index + 1).reduce((sum, b) => sum + b.close, 0) / period
    else if (ref.field === 'relative_volume' && index >= period) {
      const prior = bars.slice(index - period, index)
      if (bar.volume > 0 && prior.every((b) => Number.isFinite(b.volume) && b.volume > 0))
        v = bar.volume / (prior.reduce((sum, b) => sum + b.volume, 0) / period)
    } else if (ref.field === 'highest_high' && index >= period)
      v = Math.max(...bars.slice(index - period, index).map((b) => b.high))
    else if (ref.field === 'lowest_low' && index >= period)
      v = Math.min(...bars.slice(index - period, index).map((b) => b.low))
    else if (ref.field === 'candle_pattern') {
      const segment = bars
        .slice(0, index + 1)
        .filter((b) => !session || seconds >= 86400 || day(b.time) === day(bar.time))
      if (segment.length >= 11) {
        const pattern = detectPattern(segment, ref.pattern)
        v = pattern ? (pattern.side === 'CALL' ? 1 : -1) : 0
      }
    } else if (['support', 'resistance'].includes(ref.field)) {
      const levels = offset
        ? new ToolkitEngine().update(bars.slice(0, index + 1), {
            seconds,
            asOf: dataset.observedAt,
            continuous,
            session,
          })
        : metrics
      const candidates = levels.zones
        .filter((z) => z.above === (ref.field === 'resistance'))
        .map((z) => (z.above ? z.low : z.high))
        .filter((v) => (ref.field === 'support' ? v <= bar.close : v >= bar.close))
      v = candidates.length
        ? ref.field === 'support'
          ? Math.max(...candidates)
          : Math.min(...candidates)
        : null
    } else if (ref.field === 'atr') v = index >= 13 ? (point?.atr ?? null) : null
    else if (ref.field === 'bb_upper') v = point?.bbHigh ?? null
    else if (ref.field === 'bb_lower') v = point?.bbLow ?? null
    else if (ref.field === 'rsi') v = point?.rsi ?? null
    else if (ref.field === 'macd') v = point?.macd ?? null
    else if (ref.field === 'signal') v = point?.signal ?? null
    else if (ref.field === 'histogram') v = point?.histogram ?? null
    if (v != null && !Number.isFinite(v)) v = null
    cache.set(key, v)
    return v
  }
  type Truth = boolean | null | 'skip'
  const reasons: string[] = []
  const evaluate = (node: RuleNode): Truth => {
    if (node.enabled === false) return 'skip'
    if (node.type === 'group') {
      const states = node.children.map(evaluate).filter((s) => s !== 'skip')
      if (!states.length) return null
      if (node.op === 'all')
        return states.includes(false) ? false : states.includes(null) ? null : true
      return states.includes(true) ? true : states.includes(null) ? null : false
    }
    const a = value(node.left),
      b = value(node.right)
    if (a == null || b == null) {
      reasons.push('A required field is missing or still warming up')
      return null
    }
    let hit = false
    switch (node.op) {
      case 'gt':
        hit = a > b
        break
      case 'gte':
        hit = a >= b
        break
      case 'lt':
        hit = a < b
        break
      case 'lte':
        hit = a <= b
        break
      case 'eq':
        hit = a === b
        break
      case 'within_pct':
        hit = b !== 0 && 100 * Math.abs(a / b - 1) <= Number(node.tolerance)
        break
      default: {
        const p = value(node.left, 1),
          q = value(node.right, 1)
        if (p == null || q == null) return null
        hit = node.op === 'cross_above' ? p <= q && a > b : p >= q && a < b
      }
    }
    if (hit)
      reasons.push(
        `${typeof node.left === 'number' ? node.left : node.left.field} ${node.op.replaceAll('_', ' ')} ${typeof node.right === 'number' ? node.right : node.right.field}`
      )
    return hit
  }
  const match = evaluate(definition.rule)
  const context = resolveIndicatorChart(dataset.symbol, dataset.exchange),
    bull = definition.intent === 'bullish'
  const direction =
    definition.intent === 'observe'
      ? 'MATCH'
      : context.optionSide
        ? `${bull ? 'BUY' : 'AVOID'} ${context.optionSide}`
        : continuous
          ? `${bull ? 'LONG' : 'SHORT'} setup`
          : `${bull ? 'BULLISH' : 'BEARISH'} setup`
  const values: ScanRow['values'] = {}
  for (const [field] of FIELDS) values[field] = value({ field })
  const pattern = (() => {
    let selected: ScanRow['pattern']
    const walk = (n: RuleNode) => {
      if (n.enabled === false) return
      if (n.type === 'group') n.children.forEach(walk)
      else if (typeof n.left !== 'number' && n.left.field === 'candle_pattern')
        selected = n.left.pattern ?? 'all'
    }
    walk(definition.rule)
    return selected
  })()
  return {
    ...base,
    state: match === true ? 'match' : match === false ? 'no-match' : 'unavailable',
    direction,
    fresh,
    time: last.time,
    values,
    pattern,
    reason:
      reasons.join(' · ') ||
      (match === false ? 'Conditions do not match' : 'Add an enabled condition'),
  }
}
export interface ScanRequest {
  revision: string
  definition: ScreenDefinition
  datasets: ScanDataset[]
  now: number
}
export const evaluateBatch = (request: ScanRequest) => ({
  revision: request.revision,
  rows: request.datasets.map((d) =>
    evaluateScreen(d, validateDefinition(request.definition), request.now)
  ),
})
