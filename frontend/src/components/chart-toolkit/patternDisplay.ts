import type { TimedArchiveMatch } from './archiveConfirmations'

/** Display bounds count actual chart candles, including a forming last candle.
 * Full verified history remains available to every calculation and trade rule. */
export function patternDisplayRange(
  bars: readonly { time: number }[],
  showAll = false
): { first: number; last: number } {
  return {
    first: bars[showAll ? 0 : Math.max(0, bars.length - 10)]?.time ?? 0,
    last: bars.at(-1)?.time ?? 0,
  }
}

/** Optional previews are explicitly named and never feed the final reading. */
export function patternDisplayEvents(
  events: readonly TimedArchiveMatch[],
  showUnconfirmed = false
): TimedArchiveMatch[] {
  return events
    .filter(event => showUnconfirmed || event.confirmed === true || event.side === 'NEUTRAL')
    .map(event => event.side !== 'NEUTRAL' && event.confirmed !== true
      ? { ...event, name: `${event.name} · unconfirmed` }
      : event)
}
