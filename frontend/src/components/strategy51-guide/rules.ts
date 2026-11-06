import type { EvaluationInput, StrategyDefinition, StrategyRow } from './types'
import { chartRule } from './chartRules'
import { optionRule } from './optionRules'
import { priceActionRule } from './priceActionRules'
import { row, timeframe } from './ruleHelpers'
export function assessStrategy(d: StrategyDefinition, a: EvaluationInput): StrategyRow {
  const gate = timeframe(d, a)
  if (gate) return gate
  if (a.index < 2)
    return row(
      d,
      'waiting',
      'Waiting for completed candle history',
      'Load completed candles to evaluate the source sequence'
    )
  const result = d.id.startsWith('6.')
    ? optionRule(d, a)
    : d.id.startsWith('7.')
      ? priceActionRule(d, a)
      : chartRule(d, a)
  if (result.candidate?.cutoffMinute != null) {
    const time =
        a.frames[a.index].bar.closeTime ?? a.frames[a.index].bar.time + a.context.intervalSeconds,
      minute = ((time + 19800) % 86400) / 60
    if (minute >= result.candidate.cutoffMinute)
      return row(
        d,
        'waiting',
        'The confirming close is at or after the source exit time',
        'Wait for the next eligible session; no fresh reference is opened at its exit cutoff'
      )
  }
  if (result.candidate?.stop == null && result.candidate)
    return row(
      d,
      'needs-context',
      'Chart conditions fit, but a source risk anchor is missing',
      'Wait for a known valid stop before a bounded plan'
    )
  if (result.candidate?.stop != null) {
    const c = result.candidate,
      bad = c.side === 'long' ? c.stop! >= c.entry : c.stop! <= c.entry
    if (bad || !(c.stop! > 0) || !Number.isFinite(c.stop))
      return row(
        d,
        'needs-context',
        'Source stop is on the wrong side of the confirmed entry',
        'Wait for a valid source risk anchor; no negative-risk plan is created'
      )
  }
  if (result.candidate?.target != null) {
    const c = result.candidate
    if (
      !Number.isFinite(c.target) ||
      !(c.target! > 0) ||
      (c.side === 'long' ? c.target! <= c.entry : c.target! >= c.entry)
    )
      return row(
        d,
        'needs-context',
        'The source target is already behind the confirmed price',
        'Wait for a new setup with a valid target; a local target does not replace an invalid source target'
      )
  }
  return result
}
