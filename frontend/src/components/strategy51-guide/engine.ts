import type { BookRisk, BookSegment } from '../book-pattern-guide/types'
import { calculateBookRisk } from '../book-pattern-guide/risk'
import { STRATEGIES_51 } from './catalog'
import { buildFrames, rsi } from './indicators'
import { strategySession } from './session'
import { assessStrategy } from './rules'
import { DEFAULT_STRATEGY51_SETTINGS } from './settings'
import type {
  Candidate,
  Frame,
  Strategy51Result,
  Strategy51Settings,
  StrategyBar,
  StrategyContext,
  StrategyEvent,
  StrategyExtras,
  StrategyPlan,
  StrategyRow,
} from './types'
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
function valid(b: StrategyBar) {
  return (
    [b.time, b.open, b.high, b.low, b.close, b.volume].every(finite) &&
    b.time > 0 &&
    b.open > 0 &&
    b.close > 0 &&
    b.low > 0 &&
    b.high >= Math.max(b.open, b.close) &&
    b.low <= Math.min(b.open, b.close) &&
    b.high >= b.low &&
    b.volume >= 0 &&
    !b.repaired
  )
}
function sizing(p: StrategyPlan, s: Strategy51Settings, c: StrategyContext): BookRisk {
  const unit = s.instrumentScope === `${c.exchange ?? ''}:${c.symbol}` ? s.instrument : undefined
  if (p.target != null) return calculateBookRisk({ ...p, target: p.target }, s, unit)
  const risk = Math.abs(p.entry - p.stop),
    out: BookRisk = {
      priceRisk: risk,
      priceReward: 0,
      rr: 0,
      unavailableReasons: [],
      notes: [
        'Source exit is conditional; a cash reward estimate is not defined.',
        'Margin, affordability and portfolio exposure are not established.',
      ],
    }
  if (!(s.equity > 0 && finite(s.equity))) out.unavailableReasons.push('Account equity is unset')
  if (!(s.riskPercent > 0 && s.riskPercent <= 100))
    out.unavailableReasons.push('Fixed risk percent is invalid')
  if (
    !unit ||
    unit.kind !== 'linear' ||
    !unit.accountCurrency ||
    !unit.quoteCurrency ||
    !unit.unitDefinition ||
    !(unit.valuePerPriceUnit! > 0) ||
    !(unit.quantityStep! > 0)
  )
    out.unavailableReasons.push('Exact scoped linear instrument units are not verified')
  if (unit?.unitDefinition === 'option-premium' && unit.chartPriceKind !== 'premium')
    out.unavailableReasons.push('Option quantity requires its premium chart')
  const conversion = unit?.quoteCurrency === unit?.accountCurrency ? 1 : unit?.conversionRate
  if (!(conversion! > 0)) out.unavailableReasons.push('Currency conversion is unavailable')
  if ([s.fixedCost, s.perUnitCost, s.slippagePrice].some((v) => !finite(v) || v < 0))
    out.unavailableReasons.push('Costs must be finite and nonnegative')
  if (out.unavailableReasons.length) return out
  const budget = (s.equity * s.riskPercent) / 100 - s.fixedCost,
    loss = (risk + s.slippagePrice) * unit!.valuePerPriceUnit! * conversion! + s.perUnitCost,
    step = unit!.quantityStep!,
    quantity = Math.floor(budget / (loss * step)) * step
  out.budget = budget
  out.lossPerUnit = loss
  if (!(quantity >= step)) {
    out.unavailableReasons.push('Risk budget cannot fund one quantity step')
    return out
  }
  out.quantity = quantity
  out.estimatedRiskCash = quantity * loss + s.fixedCost
  if (unit!.lotSize! > 0) out.lots = quantity / unit!.lotSize!
  return out
}
function makePlan(
  e: StrategyEvent,
  s: Strategy51Settings,
  c: StrategyContext
): StrategyPlan | undefined {
  if (
    !finite(e.stop) ||
    !(e.stop > 0) ||
    !(e.entry > 0) ||
    (e.side === 'long' ? e.stop >= e.entry : e.stop <= e.entry)
  )
    return
  const risk = Math.abs(e.entry - e.stop)
  let target = e.target,
    targetMethod = e.targetMethod,
    targetOrigin = e.targetOrigin
  if (target == null && s.localTargets) {
    const proposed = e.entry + (e.side === 'long' ? 1 : -1) * risk * s.targetR
    if (proposed > 0) {
      target = proposed
      targetMethod = `Local ${s.targetR}R planning target; source exit retained separately`
      targetOrigin = 'local'
    }
  }
  if (
    target != null &&
    (!finite(target) || target <= 0 || (e.side === 'long' ? target <= e.entry : target >= e.entry))
  )
    return
  const rr = target != null ? Math.abs(target - e.entry) / risk : undefined
  if (rr != null && rr < s.minRR) return
  const p: StrategyPlan = {
    ...e,
    stop: e.stop,
    target,
    targetMethod,
    targetOrigin,
    rr,
    createdAt: e.time,
    createdIndex: e.index,
    status: 'active',
  }
  p.sizing = sizing(p, s, c)
  return p
}
function terminate(
  p: StrategyPlan,
  f: Frame,
  frames: Frame[],
  s: Strategy51Settings,
  seconds: number
) {
  const b = f.bar,
    stop = p.currentStop ?? p.stop,
    stopHit = p.side === 'long' ? b.low <= stop : b.high >= stop,
    targetHit = p.target != null && (p.side === 'long' ? b.high >= p.target : b.low <= p.target)
  if (stopHit && targetHit) p.status = 'ambiguous'
  else if (stopHit) p.status = 'stop-touched'
  else if (targetHit) p.status = 'target-touched'
  const closeTime = b.closeTime ?? b.time + seconds,
    elapsed = closeTime - p.createdAt,
    closeMinute = ((closeTime + 19800) % 86400) / 60,
    entryDay = Math.floor((p.createdAt + 19800) / 86400)
  if (
    p.status === 'active' &&
    ((p.timeLimitSeconds != null && elapsed >= p.timeLimitSeconds) ||
      (p.exitAt != null && closeTime >= p.exitAt) ||
      (p.cutoffMinute != null && (f.day > entryDay || closeMinute >= p.cutoffMinute)) ||
      (p.nextSessionExitMinute != null &&
        f.day > entryDay &&
        closeMinute >= p.nextSessionExitMinute))
  )
    p.status = 'time-exit'
  if (p.status === 'active' && p.conditionalExit) {
    const rule = p.conditionalExit,
      prev = frames[f.index - 1],
      long = p.side === 'long'
    let exit = false
    if (rule === 'bb-mid' && f.basis != null) exit = long ? b.close < f.basis : b.close > f.basis
    if (rule === 'supertrend7' && f.st7 != null) exit = long ? b.close < f.st7 : b.close > f.st7
    if (rule === 'supertrend10' && f.st10 != null) exit = long ? b.close < f.st10 : b.close > f.st10
    if (rule === 'rsi70') exit = f.rsi != null && f.rsi >= 70
    if (rule === 'rsi30') exit = f.rsi != null && f.rsi <= 30
    if (rule === 'rsi-return70')
      exit = prev?.rsi != null && prev.rsi > 70 && f.rsi != null && f.rsi <= 70
    if (rule === 'rsi-return30')
      exit = prev?.rsi != null && prev.rsi < 30 && f.rsi != null && f.rsi >= 30
    if (rule === 'ema14' && f.ema[14] != null)
      exit = long ? b.close >= f.ema[14]! : b.close <= f.ema[14]!
    if (rule === 'vwap' && f.vwap != null) exit = long ? b.close <= f.vwap : b.close >= f.vwap
    if (exit) p.status = 'conditional-exit'
  }
  if (p.status === 'active' && p.partialAtR != null && !p.partialTime) {
    const at = p.entry + (p.side === 'long' ? 1 : -1) * Math.abs(p.entry - p.stop) * p.partialAtR
    if (p.side === 'long' ? b.high >= at : b.low <= at) {
      p.partialTime = b.closeTime ?? b.time + seconds
      if (p.breakevenAfterPartial) p.currentStop = p.entry
    }
  }
  if (
    p.status === 'active' &&
    p.side === 'short' &&
    p.breakevenAtPremiumFraction != null &&
    b.low <= p.entry * p.breakevenAtPremiumFraction
  )
    p.currentStop = p.entry
  // Explicit source time exits take precedence over the optional local bar expiry.
  if (
    p.status === 'active' &&
    p.timeLimitSeconds == null &&
    p.exitAt == null &&
    p.cutoffMinute == null &&
    p.nextSessionExitMinute == null &&
    f.index - p.createdIndex >= s.planExpiryBars
  )
    p.status = 'expired'
  if (p.status !== 'active') p.terminalTime = b.closeTime ?? b.time + seconds
}
function trends(f: Frame | undefined, frames: Frame[]): BookSegment[] {
  if (!f) return []
  const out: BookSegment[] = []
  for (const side of ['low', 'high'] as const) {
    const p = (side === 'low' ? f.lows : f.highs).slice(-2)
    if (p.length < 2) continue
    if (side === 'low' ? p[1].price <= p[0].price : p[1].price >= p[0].price) continue
    out.push({
      from: {
        index: p[0].index,
        time: frames[p[0].index].bar.time,
        price: p[0].price,
        role: side === 'low' ? 'support' : 'resistance',
      },
      to: {
        index: p[1].index,
        time: frames[p[1].index].bar.time,
        price: p[1].price,
        role: side === 'low' ? 'support' : 'resistance',
      },
      role: side === 'low' ? 'rising support' : 'falling resistance',
    })
  }
  return out
}
export class Strategy51Engine {
  private cache?: { key: string; result: Strategy51Result }
  reconcile(
    input: readonly StrategyBar[],
    context: StrategyContext,
    settings: Strategy51Settings = DEFAULT_STRATEGY51_SETTINGS,
    extras: StrategyExtras = {}
  ): Strategy51Result {
    const scope = `${context.exchange ?? ''}:${context.symbol}:${context.intervalSeconds}`,
      unavailable = (reason: string): Strategy51Result => ({
        scope,
        rows: STRATEGIES_51.map((definition) => ({
          definition,
          state: 'needs-data',
          reason,
          next: reason,
          notes: definition.notes,
        })),
        events: [],
        readiness: 'unavailable',
        viewMode: extras.historical ? 'history' : context.marketOpen ? 'live' : 'closed-session',
        tickSize: context.tickSize,
        reason,
        next: reason,
        expected: 'Wait for matching verified candle data',
        trend: 'unavailable',
        trendLines: [],
        processed: 0,
      })
    if (
      !context.sourceReady ||
      !finite(context.observedAt) ||
      context.observedAt <= 0 ||
      !finite(context.now) ||
      !finite(context.intervalSeconds) ||
      context.intervalSeconds <= 0 ||
      context.chartType !== 'standard'
    )
      return unavailable('Matching verified standard-candle history is unavailable')
    if (!input.length) return unavailable('Waiting for chart candles')
    if (
      input.some(
        (b, i) =>
          !valid(b) ||
          (i > 0 && b.time <= input[i - 1].time) ||
          (b.closeTime != null &&
            (!finite(b.closeTime) ||
              b.closeTime <= b.time ||
              b.closeTime > b.time + context.intervalSeconds))
      )
    )
      return unavailable(
        'Invalid, repaired, duplicate or out-of-order candle data; waiting for a clean refresh'
      )
    const cap = Math.min(context.now, context.observedAt),
      bars = input
        .filter((b) => (b.closeTime ?? b.time + context.intervalSeconds) <= cap)
        .slice(-1500),
      last = bars.at(-1)
    if (!last)
      return unavailable('Waiting for a candle to close and be observed by the data source')
    const lastClose = last.closeTime ?? last.time + context.intervalSeconds
    if (
      context.marketOpen &&
      (!context.connected ||
        context.now - context.observedAt > Math.max(30, context.intervalSeconds * 2) ||
        context.now - lastClose > context.intervalSeconds * 2 ||
        (context.quoteObservedAt != null && context.now - context.quoteObservedAt > 30))
    )
      return unavailable(
        'Live candle/quote source is delayed or disconnected; current entry guidance is paused'
      )
    const forming = [...input]
      .reverse()
      .find((b) => (b.closeTime ?? b.time + context.intervalSeconds) > cap)
    const key = JSON.stringify([
      scope,
      bars,
      settings,
      extras,
      context.marketOpen,
      context.instrument,
      context.tickSize,
    ])
    if (this.cache?.key === key)
      return {
        ...this.cache.result,
        forming: forming ? { time: forming.time, price: forming.close } : undefined,
      }
    const session = strategySession(context.exchange, extras.session)
    const frames = buildFrames(bars, context.intervalSeconds, session?.offset ?? 19800, {
      ...settings,
      session: session ?? null,
    })
    const h = extras.higher,
      higher =
        h &&
        finite(h.observedAt) &&
        h.observedAt > 0 &&
        h.intervalSeconds === 3600 &&
        h.bars.every(
          (b, i) =>
            valid(b) &&
            (i === 0 || b.time > h.bars[i - 1].time) &&
            (b.closeTime == null ||
              (finite(b.closeTime) && b.closeTime > b.time && b.closeTime <= b.time + 3600))
        )
          ? h
          : undefined
    const prepared: StrategyExtras = {
      ...extras,
      higher: higher
        ? {
            ...higher,
            rsi: rsi(
              higher.bars.map((b) => b.close),
              14
            ),
          }
        : undefined,
    } as StrategyExtras
    let plan: StrategyPlan | undefined,
      lastPlan: StrategyPlan | undefined,
      rows: StrategyRow[] = [],
      events: StrategyEvent[] = []
    const seen = new Set<string>(),
      cooldown = new Map<string, number>()
    for (let i = 2; i < frames.length; i++) {
      const f = frames[i]
      if (plan) {
        terminate(plan, f, frames, settings, context.intervalSeconds)
        if (plan.status !== 'active') {
          lastPlan = plan
          plan = undefined
        }
      }
      const candidates: { candidate: Candidate; definition: (typeof STRATEGIES_51)[number] }[] = []
      const evaluated = STRATEGIES_51.map((d) =>
        assessStrategy(d, { frames, index: i, context, settings, extras: prepared })
      )
      if (i === frames.length - 1) rows = evaluated
      for (const r of evaluated) {
        const c = r.candidate
        if (!c) continue
        const id = `${scope}:${c.strategyId}:${c.side}:${frames[c.signalIndex].bar.time}`
        if (seen.has(id)) continue
        seen.add(id)
        const event: StrategyEvent = {
          ...c,
          id,
          time: f.bar.closeTime ?? f.bar.time + context.intervalSeconds,
          signalTime: frames[c.signalIndex].bar.time,
          name: `${c.strategyId} · ${r.definition.title}`,
        }
        events.push(event)
        candidates.push({ candidate: event, definition: r.definition })
      }
      if (!plan) {
        for (const item of candidates) {
          const e = item.candidate as StrategyEvent
          // Focus and daily reference limits select a plan; they never pause detections.
          if (settings.selected !== 'auto' && e.strategyId !== settings.selected) continue
          if (e.strategyId === '2.3' && cooldown.get(e.strategyId) === f.day) continue
          const p = makePlan(e, settings, context)
          if (p) {
            plan = p
            if (e.strategyId === '2.3') cooldown.set(e.strategyId, f.day)
            break
          }
        }
      }
    }
    if (!rows.length)
      rows = STRATEGIES_51.map((definition) =>
        assessStrategy(definition, {
          frames,
          index: frames.length - 1,
          context,
          settings,
          extras: prepared,
        })
      )
    const chosen =
      rows.find((r) => r.definition.id === settings.selected) ??
      rows.find((r) => r.state === 'confirmed') ??
      rows.find((r) => r.state === 'waiting') ??
      rows[0]
    const reason = context.marketOpen
      ? 'Verified completed candles'
      : 'Last-session / historical references; not a current entry instruction'
    const result: Strategy51Result = {
      scope,
      rows,
      events: events.slice(-200),
      plan,
      lastPlan,
      readiness: context.marketOpen ? 'ready' : 'last-session',
      viewMode: extras.historical ? 'history' : context.marketOpen ? 'live' : 'closed-session',
      tickSize: context.tickSize,
      reason,
      next: plan
        ? `Monitor ${plan.target != null ? 'frozen SL/target' : 'SL and source conditional exit'}; ${plan.exitRule}`
        : (chosen?.next ?? 'Wait for a qualified strategy'),
      expected: plan?.expected ?? 'Wait for a source-qualified setup',
      trend: frames.at(-1)?.trend ?? 'unavailable',
      completedAt: lastClose,
      forming: forming ? { time: forming.time, price: forming.close } : undefined,
      trendLines: settings.showTrendLines ? trends(frames.at(-1), frames) : [],
      processed: bars.length,
      frames,
    }
    this.cache = { key, result }
    return result
  }
}
