import type { ResearchBar } from './piyushResearchEngine.js'
import type { PlanSession } from './chartTradePlan'
const joined = (parts: readonly (readonly ResearchBar[])[]) =>
  [...new Map(parts.flatMap((part) => [...part]).map((b) => [b.time, b])).values()].sort(
    (a, b) => a.time - b.time
  )
/** Request old sessions only for setups that require them; the caller caches each date. */
export async function loadResearchSessions(
  base: readonly ResearchBar[],
  previous: boolean,
  continuous: boolean,
  session: PlanSession | undefined,
  loadDay: (date: string) => Promise<ResearchBar[]>
) {
  if (!previous || !base.length) return [...base]
  const offset = continuous ? 0 : (session?.offset ?? 19800)
  const day = Math.floor((base.at(-1)!.time + offset) / 86400)
  const date = (d: number) => new Date(d * 86400000).toISOString().slice(0, 10)
  const parts: ResearchBar[][] = []
  if (continuous) {
    for (const delta of [0, 1, 2]) {
      try {
        parts.push(await loadDay(date(day - delta)))
      } catch {
        /* Retried on the next history refresh. */
      }
    }
  } else if (session) {
    for (let delta = 1; delta <= 7; delta++) {
      const d = day - delta
      if ([0, 6].includes(new Date(d * 86400000).getUTCDay())) continue
      let bars: ResearchBar[] = []
      try {
        bars = await loadDay(date(d))
        parts.push(bars)
      } catch {
        /* Retry the required session; an older weekday is not a substitute. */
      }
      // Without an exchange holiday record, an empty weekday is unavailable.
      // Never turn a delayed/failed prior-day request into an older day's range.
      break
    }
  }
  return joined([...parts, [...base]])
}
