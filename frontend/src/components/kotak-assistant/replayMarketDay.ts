import { sessionBounds } from './chartReplay'

interface DayTimings {
  date: string
  timings: Array<{ exchange: string; start_time: string; end_time: string }>
}
export interface ReplayCalendar {
  date: string
  previousDate: string
  start: number | null
  end: number | null
}
const shiftDay = (date: string, days: number) =>
  new Date(Date.parse(`${date}T00:00:00Z`) + days * 86400000).toISOString().slice(0, 10)

/** Use the application's exchange calendar, including holidays and special sessions. */
export async function loadReplayCalendar(
  date: string,
  exchange: string,
  readDay: (date: string) => Promise<DayTimings>,
  signal?: AbortSignal
): Promise<ReplayCalendar> {
  const read = async (day: string) => {
    signal?.throwIfAborted()
    const result = await readDay(day)
    signal?.throwIfAborted()
    if (result.date !== day || !Array.isArray(result.timings))
      throw Error('Market calendar unavailable')
    return result.timings.find((t) => t.exchange === exchange)
  }
  const today = await read(date)
  const offset = (value: string) => {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) throw Error('Invalid exchange session time')
    const [hour, minute] = value.split(':').map(Number)
    return (hour * 60 + minute) * 60000
  }
  const midnight = sessionBounds(date)!.start * 1000
  const start = today ? midnight + offset(today.start_time) : null
  let end = today ? midnight + offset(today.end_time) : null
  if (start != null && end != null && end <= start) end += 86400000
  for (let days = 1; days <= 31; days++) {
    const previousDate = shiftDay(date, -days)
    if (await read(previousDate)) return { date, previousDate, start, end }
  }
  throw Error('No previous trading session found in the exchange calendar')
}
export function replayDefaultDate(calendar: ReplayCalendar, nowMs: number) {
  return calendar.start != null &&
    calendar.end != null &&
    nowMs >= calendar.start &&
    nowMs < calendar.end
    ? calendar.date
    : calendar.previousDate
}
