import type { EvaluationInput, OptionEvidence, StrategyDefinition, StrategyRow } from './types'
import { breakout, candidate, present, row, waiting } from './ruleHelpers'
const minute = (t: number) => ((((t + 19800) % 86400) + 86400) % 86400) / 60
const day = (t: number) => Math.floor((t + 19800) / 86400)
export function optionRule(d: StrategyDefinition, a: EvaluationInput): StrategyRow {
  const x = a.frames[a.index],
    q = a.frames[a.index - 1],
    opt = a.extras.option,
    ctx = a.context,
    b = x.bar
  if (d.id === '6.4') {
    if (
      ctx.intervalSeconds !== 300 ||
      !ctx.symbol.startsWith('BANKNIFTY') ||
      ['NFO', 'BFO'].includes(ctx.exchange ?? '')
    )
      return row(
        d,
        'needs-data',
        'Use the5m Bank Nifty UNDERLYING chart',
        'Supertrend on underlying chooses SELL ATM PE when bullish / SELL ATM CE when bearish; option levels require premium data'
      )
    if (!present(x.st10)) return waiting(d, 'Wait for Supertrend10/3 warm-up')
    return row(
      d,
      'needs-data',
      `${x.st10Side === 'long' ? 'Bullish chart → source sells ATM PE' : 'Bearish chart → source sells ATM CE'}`,
      'Verify weekly ATM contract/premium and leg state; exit sold option on opposite Supertrend flip by15:15'
    )
  }
  if (d.id === '6.1')
    return row(
      d,
      'needs-context',
      'Weekly calendar requires VIX and four verified legs',
      'Supply VIX, current/next expiries, four premiums and max-loss model; adjustment buy/sell instructions conflict'
    )
  if (d.id === '6.5')
    return row(
      d,
      'needs-data',
      'Needs verified fixed-strike CE+PE premium/VWAP series',
      'Use matched5m Bank Nifty ATM legs and validated combined volume; S≤.97×VWAP, stop at VWAP, max3/day, no new entry after15:00'
    )
  if (d.id === '6.8')
    return row(
      d,
      'needs-data',
      'Needs both OTM entry premiums and live combined series',
      'At09:30 source sells both; combined stop is entry CE+PE sum +40 points, exit15:15; never a single-option stop'
    )
  if (
    !['NFO', 'BFO'].includes(ctx.exchange ?? '') ||
    !/(CE|PE)$/.test(ctx.symbol) ||
    !opt ||
    opt.symbol !== ctx.symbol ||
    opt.exchange !== ctx.exchange
  )
    return row(
      d,
      'needs-data',
      'Actual option-premium chart and contract metadata required',
      d.id === '6.3'
        ? 'Load the09:20 highest-OI CE/PE identities and their premium histories'
        : 'Open the exact option contract; underlying movement is not an option premium trigger'
    )
  if (!opt.expiry || !(opt.strike > 0))
    return row(
      d,
      'needs-data',
      'Contract expiry/strike is not verified',
      'Wait for matching contract metadata; do not use a guessed expiry'
    )
  if (ctx.intervalSeconds > 900)
    return row(
      d,
      'timeframe',
      'Intraday premium baseline needs intraday bars',
      'Use1m/5m/15m premium candles with an exact baseline timestamp'
    )
  const spec: Record<
    string,
    {
      slot: number
      kind: NonNullable<OptionEvidence['selection']>['kind']
      factor: number
      side: 'long' | 'short'
      stop: number
      target?: number
      cutoff?: number
      timer?: number
    }
  > = {
    '6.3': {
      slot: 560,
      kind: 'highest-oi',
      factor: 1.1,
      side: 'long',
      stop: 0.8,
      target: 1.4,
      timer: 1800,
    },
    '6.6': {
      slot: 570,
      kind: 'atm',
      factor: 1.15,
      side: 'long',
      stop: 0.75,
      target: 2,
      cutoff: 915,
    },
    '6.9': { slot: 570, kind: 'atm', factor: 1, side: 'short', stop: 1.25, cutoff: 915 },
    '6.10': { slot: 660, kind: 'chosen-call', factor: 1.2, side: 'long', stop: 0.7 },
    '6.11': { slot: 900, kind: 'near150', factor: 0.95, side: 'short', stop: 1.09, cutoff: 929 },
    '6.12': { slot: 600, kind: 'atm', factor: 0.9, side: 'short', stop: 1.4 },
  }
  if (d.id === '6.7')
    return row(
      d,
      'needs-context',
      'Expiry-decay selection/calendar and VIX filter required',
      'Verify actual expiry−2-day10:00, spot±100 OTM legs and high-VIX policy; per-leg stop1.9E, exit expiry09:55'
    )
  if (d.id === '6.13')
    return row(
      d,
      'needs-context',
      'Weekly ATM straddle requires both legs and VIX',
      'Source Thursday-close BUY CE+PE, each stop.5E; verify expiry survives2–3 days and VIX≤40; source final cutoff is unspecified'
    )
  if (d.id === '6.2') {
    const slots = [556, 616, 676, 736],
      slot = slots.find((t) => Math.abs(x.minute - t) < 0.01)
    if (ctx.intervalSeconds !== 60)
      return row(
        d,
        'timeframe',
        'Fixed09:16/10:16/11:16/12:16 slots need1m candles',
        'Use1m premium chart to avoid guessing a slot inside a larger candle'
      )
    if (slot == null)
      return waiting(d, 'Wait for09:16,10:16,11:16 or12:16 IST; all source exits15:15')
    const selection = [...(opt.selections ?? []), ...(opt.selection ? [opt.selection] : [])].find(
      (z) => z.kind === 'near40' && day(z.time) === x.day && minute(z.time) === slot
    )
    if (!selection)
      return row(
        d,
        'needs-data',
        'Dated OTM near₹40 selection missing',
        'Verify this slot’s OTM CE/PE identity; current premium alone does not prove historical selection'
      )
    if (Math.abs(b.open - 40) > 2) return waiting(d, 'Local near₹40 tolerance ±₹2 is not met')
    return candidate(d, a, 'short', a.index, 2 * b.close, undefined, {
      cutoffMinute: 915,
      breakevenAtPremiumFraction: 0.5,
      targetMethod: 'Source15:15 exit; no fixed target',
      stopMethod: 'Source short buyback stop2E; reduce to E after a completed candle reaches .5E',
      notes: [
        'Stop reduction becomes effective on the next candle; intrabar adjustment fills are not assumed. Single-leg reference; the paired sale and total exposure require both legs.',
        `Selection: ${selection.source}; ${selection.description}`,
      ],
    })
  }
  const r = spec[d.id]
  if (!r) throw Error(`Missing option handler ${d.id}`)
  if (d.id === '6.10' && opt.optionType !== 'CE')
    return row(
      d,
      'needs-context',
      'Source BTST branch is call-only',
      'Source ITM/above-ATM/ATM contract wording conflicts; choose and disclose the contract interpretation'
    )
  const selection = [...(opt.selections ?? []), ...(opt.selection ? [opt.selection] : [])].find(
    (z) => z.kind === r.kind && day(z.time) === x.day && Math.abs(minute(z.time) - r.slot) < 0.01
  )
  if (
    !selection ||
    selection.kind !== r.kind ||
    day(selection.time) !== x.day ||
    Math.abs(minute(selection.time) - r.slot) > 0.01
  )
    return row(
      d,
      'needs-data',
      d.id === '6.3'
        ? '09:20 highest-OI contract snapshot missing'
        : `Dated${Math.floor(r.slot / 60)}:${String(r.slot % 60).padStart(2, '0')} ${r.kind} selection missing`,
      d.id === '6.3'
        ? 'Highest-OI identity must come from a dated OI chain; candles cannot infer it'
        : 'Wait for verified as-of contract selection, or provide clearly labelled manual context'
    )
  const baseline = a.frames.find((f) => f.day === x.day && Math.abs(f.minute - r.slot) < 0.01)
  if (!baseline || baseline.index > a.index)
    return row(
      d,
      'needs-data',
      'Exact baseline premium candle unavailable',
      `Load the exact${Math.floor(r.slot / 60)}:${String(r.slot % 60).padStart(2, '0')} premium candle; do not interpolate`
    )
  if (r.cutoff != null && x.minute >= r.cutoff)
    return waiting(
      d,
      `Source entry window has ended; exit/monitor by${Math.floor(r.cutoff / 60)}:${String(r.cutoff % 60).padStart(2, '0')}`
    )
  const threshold = baseline.bar.open * r.factor
  const trigger =
    d.id === '6.9' ? a.index === baseline.index : !!q && breakout(a, r.side, threshold)
  if (!trigger)
    return waiting(
      d,
      `Frozen premium baseline${baseline.bar.open.toFixed(2)}; wait ${r.side === 'long' ? 'above' : 'below'}${threshold.toFixed(2)}`
    )
  if (d.id === '6.10') {
    const exit = selection.exitAt,
      close = b.closeTime ?? b.time + ctx.intervalSeconds
    if (
      exit == null ||
      !Number.isFinite(exit) ||
      exit <= close ||
      day(exit) <= x.day ||
      Math.abs(minute(exit) - 570) > 0.01
    )
      return row(
        d,
        'needs-context',
        'Momentum threshold met; overnight calendar is unverified',
        'Supply the verified next trading session’s09:30 IST exit in Details; weekends and holidays are not guessed'
      )
    if (opt.expiryTime == null || !Number.isFinite(opt.expiryTime) || opt.expiryTime <= exit)
      return row(
        d,
        'needs-data',
        'The call does not have verified expiry survival through the next-session exit',
        'Choose a verified expiry surviving the supplied next trading session09:30 exit; no overnight plan is promoted'
      )
  }
  return candidate(
    d,
    a,
    r.side,
    a.index,
    b.close * r.stop,
    r.target ? b.close * r.target : undefined,
    {
      stopMethod: `Source ${r.stop}×entry premium`,
      targetMethod: r.target
        ? `Source ${r.target}×entry premium`
        : 'Source conditional/time exit; no fixed target',
      timeLimitSeconds: r.timer,
      cutoffMinute: r.cutoff,
      exitAt: d.id === '6.10' ? selection.exitAt : undefined,
      notes: [
        `Dated contract selection: ${selection.source}; ${selection.description}.`,
        `Local baseline uses the exact slot candle OPEN, not an assumed tick fill.`,
        `Own-leg premium reference only; paired fills, margin and portfolio exposure are not inferred.`,
        ...(d.id === '6.11'
          ? ['Only near₹150 legs use1.09E stop; source ATM legs have no fixed stop.']
          : []),
        ...(d.id === '6.9'
          ? [
              'One own-leg entry reference. Paired reselection/reentry and ambiguous three-trade counter require actual two-leg state.',
            ]
          : []),
        ...(d.id === '6.10'
          ? [
              'Source strike-selection contradiction remains disclosed; no exact-source contract claim. Next-session exit uses the next observed trading session at09:30, not a guessed holiday calendar. VIX filter is unavailable.',
            ]
          : []),
        ...(d.id === '6.12'
          ? [
              'Partner-driven stop adjustment is unavailable without the other leg’s actual entry/stop state. Source final time exit is unspecified.',
            ]
          : []),
      ],
    }
  )
}
