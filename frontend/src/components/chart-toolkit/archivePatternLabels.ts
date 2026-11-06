import type { ArchiveMatch } from './archiveConfirmations'

/** Names identify formations; detector prefixes and confirmation stages are provenance.
 * Preserve side and candle time: neither opposite signals nor later candles are duplicates. */
function formationName(match: ArchiveMatch): string {
  return match.name
    .replace(/^(Bullish|Bearish|Bull|Bear)\s+/i, '')
    .replace(/\s+\(operational(?: re-entry)?\)/gi, '')
    .replace(/\s+confirmed(?:\s+at\s+(?:demand|supply))?$/i, '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .replace(/^broadening wedge$/, 'megaphone')
}
function rank(match: ArchiveMatch): number {
  if (match.confirmed !== true) return 0
  if (match.entry !== undefined && match.target !== undefined) return 400
  if (match.pattern.startsWith('zone-')) return 300
  if (match.pattern.startsWith('institutional_')) return 200
  return 100
}
const timeKey = (match: ArchiveMatch) => (match as ArchiveMatch & { time?: number }).time ?? ''
export function deduplicateArchiveMatches<T extends ArchiveMatch>(matches: readonly T[]): T[] {
  const unique = new Map<string, T>()
  for (const match of matches) {
    const key = `${timeKey(match)}:${match.side}:${formationName(match)}`
    const previous = unique.get(key)
    if (!previous || rank(match) > rank(previous)) unique.set(key, match)
  }
  return [...unique.values()]
}
function specificity(match: ArchiveMatch): number {
  const name = formationName(match)
  if (/three|morning|evening|abandoned|island/.test(name)) return 50
  if (/engulf|harami|piercing|dark cloud|tweezer/.test(name)) return 40
  if (/hammer|shooting|hanging|pin bar/.test(name)) return 30
  if (/marubozu/.test(name)) return 20
  if (/belt hold/.test(name)) return 15
  return 10
}
/** Display reduction only. Distinct detections stay available in the event list.
 * At most one label per direction per candle; genuine opposite matches remain separate. */
export function primaryArchiveLabels<T extends ArchiveMatch>(matches: readonly T[]): T[] {
  const primary = new Map<string, T>()
  for (const match of deduplicateArchiveMatches(matches)) {
    const key = `${timeKey(match)}:${match.side}`,
      previous = primary.get(key)
    if (!previous || rank(match) + specificity(match) > rank(previous) + specificity(previous))
      primary.set(key, match)
  }
  return [...primary.values()]
}
