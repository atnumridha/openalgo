import type { TimedArchiveMatch } from './archiveConfirmations'

/** Display-only ordering shared by the guide and observed formation outlines.
 * Candle-label specificity must not replace observed shape geometry. Stable pattern
 * IDs/name order resolves same-time ties independently of collector/input order. */
export function comparePatternDisplay(a: TimedArchiveMatch, b: TimedArchiveMatch): number {
  const preference =
    b.time - a.time ||
    Number(!!b.structure?.length) - Number(!!a.structure?.length) ||
    Number(b.confirmed === true) - Number(a.confirmed === true)
  if (preference) return preference
  const first = `${a.pattern}:${a.side}:${a.name}`
  const second = `${b.pattern}:${b.side}:${b.name}`
  return first < second ? -1 : first > second ? 1 : 0
}
