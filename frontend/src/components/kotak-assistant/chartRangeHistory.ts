import { chartRangeBounds, type ChartDateRange, type ReplayCandle } from './chartReplay'

type DayHistory = { status: string; candles: ReplayCandle[]; message?: string }
/** Read-only range loading, capped at two concurrent day requests. No synthetic candles. */
export async function loadChartRangeHistory(
  range: ChartDateRange,
  fetchDay: (date: string) => Promise<DayHistory>,
  warmup: ReplayCandle[] = [],
  signal?: AbortSignal,
  includeWeekends = false
) {
  const bounds = chartRangeBounds(range.start, range.end, 19800)
  if (!bounds) throw Error('From date must be on or before To date.')
  const dates: string[] = []
  for (let time = bounds.start; time < bounds.end; time += 86400) {
    const date = new Date(time * 1000)
    if (includeWeekends || ![0, 6].includes(date.getUTCDay()))
      dates.push(date.toISOString().slice(0, 10))
  }
  const candles = warmup.filter((b) => b.time < bounds.start),
    emptyDates: string[] = []
  const checkCancelled = () => {
    if (signal?.aborted) throw new DOMException('Date range changed', 'AbortError')
  }
  for (let i = 0; i < dates.length; i += 2) {
    checkCancelled()
    const batch = await Promise.all(
      dates.slice(i, i + 2).map(async (date) => {
        try {
          const result = await fetchDay(date)
          if (result.status !== 'success') throw Error(result.message || 'History unavailable')
          const day = chartRangeBounds(date, date, 19800)!
          return {
            date,
            bars: result.candles.filter((b) => b.time >= day.start && b.time < day.end),
          }
        } catch (error) {
          throw Error(`History unavailable for ${date}: ${(error as Error).message}`)
        }
      })
    )
    checkCancelled()
    for (const { date, bars } of batch) {
      if (!bars.length) emptyDates.push(date)
      candles.push(...bars)
    }
  }
  return {
    candles: [...new Map(candles.map((b) => [b.time, b])).values()].sort((a, b) => a.time - b.time),
    emptyDates,
  }
}
