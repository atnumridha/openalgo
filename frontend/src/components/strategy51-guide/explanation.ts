import type { Strategy51Result, Strategy51Settings, StrategyPlan } from './types'

/** Plain descriptions of implemented conditions; full source/local exceptions remain in All 51. */
export const STRATEGY51_EXPLANATIONS: Record<string, string> = {
  '1.1':
    'A session gap reached a Bollinger band, a reversal candle formed, then price confirmed the reversal beyond that candle.',
  '1.2':
    'Williams %R pulled back towards its middle level and turned again, with price on the matching side of its 14-candle average.',
  '1.3':
    'Price retraced a confirmed upswing towards a Fibonacci level, with a bullish MACD crossover and a later close above the green signal close.',
  '1.4':
    'A rally was followed by a contracting triangle; a completed candle broke above the upper line with the required volume.',
  '1.5':
    'Price returned to a supplied old gap zone for its first retracement, then a fresh reversal gap and candle break confirmed the direction.',
  '1.6':
    'Bollinger bands contracted, then a completed candle broke outside the band as its width expanded.',
  '1.7':
    'Price and the Ichimoku lines satisfied the cloud direction rules, followed by the required candle confirmation.',
  '2.1':
    'Price retraced a confirmed impulse towards a Fibonacci level while remaining on the required side of the 200-candle average.',
  '2.2':
    'Price reacted at a previous-session pivot level with matching Supertrend direction and a confirmed signal-candle break.',
  '2.3':
    'A candle closed outside the VWAP band, an opposite candle followed, then a later candle closed beyond the reversal candle.',
  '2.4':
    'RSI reached the pullback extreme while the volume oscillator was near its required extreme; a later candle confirmed the reversal in the trend direction.',
  '2.5':
    'Price tested a previous-session pivot support or resistance, formed a reversal candle, then confirmed beyond that candle.',
  '2.6':
    'Completed hourly and 5-minute RSI readings agreed with the source direction, followed by the chart entry confirmation.',
  '2.7':
    'Price reacted at the central pivot range from the completed prior session and confirmed the required candle break.',
  '3.1':
    'Confirmed swing highs and lows established the direction, then a completed candle broke the relevant swing level.',
  '3.2':
    'Price retraced into a supplied or disclosed local value zone and then confirmed a directional candle break.',
  '3.3':
    'A supplied Elliott-wave interpretation qualified the context; the chart then confirmed the annotated entry level.',
  '3.4':
    'Price broke a previously confirmed fractal in the direction allowed by the 50-candle average.',
  '3.5':
    'A supplied Renko interpretation qualified this setup; standard chart candles alone do not establish its brick sequence.',
  '3.6':
    'Price touched a prior Donchian channel boundary, made a pullback, then broke that boundary again with a later candle confirmation.',
  '3.7':
    'Price confirmed an entry level from a supplied Gann interpretation; the geometric context was supplied rather than inferred from candles.',
  '4.1':
    'Price reacted to pivot levels derived from a fully completed prior month and confirmed the directional entry condition.',
  '4.2':
    'RSI momentum and Supertrend agreed, followed by a completed candle confirming the entry direction.',
  '4.3':
    'Supplied sector-relative-strength context qualified the direction, followed by the required chart entry confirmation.',
  '4.4':
    'Two confirmed oscillator turns formed an RSI M or W, then RSI crossed back through its threshold and price confirmed the candle break.',
  '5.1':
    'Heikin-Ashi direction, Parabolic SAR and RSI agreed before a completed chart candle confirmed the entry.',
  '5.2':
    'Price and RSI diverged at confirmed swings near a Bollinger band, then a completed candle confirmed the reversal.',
  '5.3':
    'RSI momentum and price relative to session VWAP satisfied the directional rules before entry confirmation.',
  '5.4':
    'Price consolidated for five candles on the 1-minute chart, then confirmed a trend-aligned breakout. A maximum 10-minute holding rule applies.',
  '5.5':
    'During the first Indian trading hour, price confirmed the short-side condition relative to the 5-candle EMA.',
  '5.6':
    'Price stretched away from the 14-candle EMA and then confirmed a reversal towards that moving average.',
  '6.1':
    'This calendar setup requires the complete dated near-expiry and next-expiry option legs; one premium chart cannot confirm it.',
  '6.2':
    'A dated near-40-premium contract selection met the scheduled selling condition; this is a premium short reference.',
  '6.3':
    'A dated highest-open-interest contract selection was supplied or verified, then its premium confirmed the momentum entry.',
  '6.4':
    'Underlying Supertrend established an option-direction bias; a complete option plan still requires its own contract and premium evidence.',
  '6.5':
    'The source compares the combined call-and-put premium with its combined VWAP; both legs and verified volume are required.',
  '6.6':
    'A dated at-the-money selection at 09:30 qualified the contract, then its premium rose through the required momentum level.',
  '6.7':
    'This expiry-decay setup requires its dated option legs and missing selection or trigger context before it can confirm.',
  '6.8':
    'The combined-premium selling setup requires both dated legs; the source stop is measured on their combined premium.',
  '6.9':
    'A dated qualifying option selection met the source schedule for selling time value; the stop and timed exit remain separate.',
  '6.10':
    'A chosen call at 11:00 gained the required 20% premium; next-session exit timing must be supplied, and the VIX condition remains unverified.',
  '6.11':
    'The selected near-150 premium at 15:00 fell by the required 5%, qualifying the source premium-short condition.',
  '6.12':
    'A dated at-the-money contract at 10:00 fell by the required 10%, qualifying the source premium-short condition.',
  '6.13':
    'A weekly straddle requires both dated at-the-money call and put legs; a single premium chart cannot confirm the full position.',
  '7.1':
    'Price consolidated with the required 9/21 EMA relationship, then a completed candle broke the consolidation range.',
  '7.2':
    'A daily rally of at least 20% was followed by a base with drying volume, then a completed candle confirmed the breakout.',
  '7.3':
    'Price revisited a qualifying range boundary, formed a pin rejection and then confirmed beyond the signal candle.',
  '7.4':
    'Price broke a confirmed level, returned to retest it and then confirmed continuation beyond the retest candle.',
  '7.5':
    'A supplied, dated RBI repo-rate event qualifies this context; the source does not define an automatic protective stop.',
  '7.6':
    'Three successively smaller price contractions formed a disclosed local VCP structure, then price confirmed a volume-backed breakout.',
  '7.7':
    'Price completed a two-leg pullback within the qualified trend and then confirmed continuation beyond the signal candle.',
}

export function formatStrategy51Price(value: number | undefined, tickSize?: number): string {
  if (value == null || !Number.isFinite(value)) return '—'
  let digits = 2
  if (tickSize != null && Number.isFinite(tickSize) && tickSize > 0) {
    // Count decimal precision without exposing floating-point calculation tails.
    digits = 0
    while (
      digits < 8 &&
      Math.abs(tickSize * 10 ** digits - Math.round(tickSize * 10 ** digits)) > 1e-7
    )
      digits++
  } else if (value !== 0 && Math.abs(value) < 1) digits = 6
  return value.toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

const date = (time: number) =>
  new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(time * 1000)) + ' IST'

function conditionalExit(p: StrategyPlan): string {
  const rules: Record<NonNullable<StrategyPlan['conditionalExit']>, string> = {
    'bb-mid': 'a completed candle crosses back through the middle Bollinger band',
    supertrend7: 'the completed-candle Supertrend (7) direction reverses',
    supertrend10: 'the completed-candle Supertrend (10) direction reverses',
    rsi70: 'completed-candle RSI reaches 70',
    rsi30: 'completed-candle RSI reaches 30',
    'rsi-return70': 'RSI crosses back below 70 on a completed candle',
    'rsi-return30': 'RSI crosses back above 30 on a completed candle',
    ema14: 'a completed candle reaches the 14-candle EMA',
    vwap: 'a completed candle reaches session VWAP',
  }
  const parts: string[] = []
  if (p.conditionalExit) parts.push(`Exit reference: ${rules[p.conditionalExit]}.`)
  if (p.exitAt) parts.push(`Timed exit: ${date(p.exitAt)}.`)
  if (p.cutoffMinute != null)
    parts.push(
      `Session exit: ${String(Math.floor(p.cutoffMinute / 60)).padStart(2, '0')}:${String(p.cutoffMinute % 60).padStart(2, '0')} local session time.`
    )
  if (p.timeLimitSeconds)
    parts.push(`Maximum duration: ${p.timeLimitSeconds / 3600} hours from confirmation.`)
  return parts.join(' ') || `Exit condition: ${p.exitRule}.`
}

export interface StrategyExplanation {
  why: string
  now: string
  scenario: string
  invalidation: string
  next: string
  confirmed: string
}

export function explainStrategy51(
  result: Strategy51Result | null,
  settings: Strategy51Settings
): StrategyExplanation {
  const empty: StrategyExplanation = {
    why: '',
    now: '',
    scenario: '',
    invalidation: '',
    next: '',
    confirmed: '',
  }
  if (!result || result.readiness === 'unavailable')
    return {
      ...empty,
      why: result?.reason ?? 'Matching chart candles have not arrived yet.',
      next: 'Wait for the matching verified candle source to recover before assessing an entry.',
    }
  const p = result.plan
  if (!p) {
    const row = result.rows.find((r) => r.definition.id === settings.selected)
    const ended = result.lastPlan
    const endings: Record<StrategyPlan['status'], string> = {
      active: 'still active',
      'stop-touched': 'stop touched',
      'target-touched': 'target touched',
      ambiguous: 'stop and target touched in the same candle; their order is unknown',
      'conditional-exit': 'source exit condition met',
      'time-exit': 'timed exit reached',
      expired: 'reference expired',
    }
    return {
      ...empty,
      why: ended
        ? `Previous ${ended.side === 'long' ? 'Long' : 'Short'} reference ended: ${endings[ended.status]}.`
        : (row?.reason ?? 'No completed-candle setup currently qualifies for a plan.'),
      next:
        row?.next ??
        'Wait for a new qualifying setup; a forming pattern alone does not create an entry plan.',
      confirmed: ended?.terminalTime ? `Ended ${date(ended.terminalTime)}` : '',
    }
  }
  const fmt = (v: number | undefined) => formatStrategy51Price(v, result.tickSize)
  const long = p.side === 'long'
  // Match immutable bar time, since retained-history indices can move after the 1500-bar cap.
  const signal = result.frames?.find((f) => f.bar.time === p.signalTime)
  let why = STRATEGY51_EXPLANATIONS[p.strategyId] ?? p.expected
  if (p.strategyId === '3.6') {
    const boundary = long ? signal?.donHigh : signal?.donLow
    const threshold = long ? signal?.bar.high : signal?.bar.low
    why = `A ${settings.donchianPeriod}-candle channel ${long ? 'high' : 'low'}${boundary == null ? '' : ` at ${fmt(boundary)}`} was touched, followed by a pullback and a fresh break. A later candle closed ${long ? 'above the signal high' : 'below the signal low'}${threshold == null ? '' : ` ${fmt(threshold)}`}.`
  }
  if (p.supplied && !/supplied/i.test(why)) why = `Supplied context qualified this setup. ${why}`
  const forming =
    result.readiness === 'ready' && result.viewMode !== 'history' ? result.forming : undefined
  const latest = forming?.price ?? result.frames?.at(-1)?.bar.close
  const risk = Math.abs(p.entry - p.stop)
  const delta = latest == null ? undefined : latest - p.entry
  const progress = delta == null ? undefined : delta * (long ? 1 : -1)
  let now =
    latest == null
      ? 'Latest verified price is unavailable.'
      : `${forming ? 'Forming price' : 'Last closed price'} ${fmt(latest)}; ${fmt(Math.abs(delta!))} points ${delta! >= 0 ? 'above' : 'below'} entry${risk > 0 ? ` (${((progress ?? 0) / risk).toFixed(2)}R of initial risk)` : ''}.`
  const conflict = (long && result.trend === 'bear') || (!long && result.trend === 'bull')
  if (conflict) now += ` Current trend opposes this frozen ${long ? 'Long' : 'Short'} reference.`
  const stop = p.currentStop ?? p.stop
  const origin =
    p.targetOrigin === 'local'
      ? 'Local target'
      : p.targetOrigin === 'supplied'
        ? 'Supplied target'
        : 'Target'
  const distance =
    latest == null || p.target == null ? undefined : (p.target - latest) * (long ? 1 : -1)
  let scenario =
    p.target == null
      ? conditionalExit(p)
      : `${long ? 'Upward' : 'Downward'} continuation towards ${fmt(p.target)}${distance == null ? '' : distance > 0 ? `; ${fmt(distance)} points to go` : '; the observed price is at or beyond this reference'}. ${origin}${p.rr == null ? '' : ` ${p.rr.toFixed(1)}R`}; this is a scenario, not a forecast.`
  if (
    p.target != null &&
    (p.conditionalExit || p.exitAt || p.cutoffMinute != null || p.timeLimitSeconds)
  )
    scenario += ` ${conditionalExit(p)}`
  const invalidation = `Price ${long ? 'at or below' : 'at or above'} ${fmt(stop)} touches the ${p.currentStop != null && p.currentStop !== p.stop ? 'adjusted' : 'frozen'} stop reference. ${p.stopMethod}.`
  let next =
    result.viewMode === 'history'
      ? 'History/replay review only. Return to Latest candles for current guidance.'
      : result.readiness === 'last-session'
        ? result.viewMode === 'closed-session'
          ? 'Market closed: review this existing reference. Wait for fresh session candles before assessing a new entry.'
          : 'Earlier-candle review of this existing reference. Wait for fresh verified candles before assessing a new entry.'
        : 'Track this existing reference; each update is not a fresh entry.'
  const provisionalTouch =
    forming &&
    ((long ? forming.price <= stop : forming.price >= stop) ||
      (p.target != null && (long ? forming.price >= p.target : forming.price <= p.target)))
  if (provisionalTouch)
    next += ' Forming price has reached a reference level; candle confirmation is pending.'
  if (p.partialTime) next += ' Partial-exit reference already reached; remaining levels are shown.'
  return { why, now, scenario, invalidation, next, confirmed: `Confirmed ${date(p.time)}` }
}
