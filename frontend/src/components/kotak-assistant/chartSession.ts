import type { TodayTiming } from '@/types/admin'
import { sessionBounds } from './chartReplay'
import { recentTickEpoch } from './chartViewport'

export interface ChartSessionWindow {
  date: string
  exchange: string
  start: number | null
  end: number | null
}

/** Calendar times are IST; the window and tick timestamps use true UTC seconds. */
export function chartSessionWindow(
  day: { date: string; timings: TodayTiming[] },
  date: string,
  exchange: string
): ChartSessionWindow | null {
  const bounds = sessionBounds(date)
  if (!bounds || day.date !== date || !Array.isArray(day.timings)) return null
  const calendarExchange = exchange.toUpperCase().replace(/_INDEX$/, '')
  const timing = day.timings.find((entry) => entry?.exchange === calendarExchange)
  if (!timing) return { date, exchange: calendarExchange, start: null, end: null }
  const offset = (value: string) => {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) return NaN
    const [hour, minute] = value.split(':').map(Number)
    return hour * 3600 + minute * 60
  }
  const start = bounds.start + offset(timing.start_time)
  let end = bounds.start + offset(timing.end_time)
  if (!Number.isFinite(start) || !Number.isFinite(end) || start === end) return null
  if (end < start) end += 86400
  return { date, exchange: calendarExchange, start, end }
}

export const chartSessionOpen = (window: ChartSessionWindow | null, now: number) =>
  window?.start != null && window.end != null && now >= window.start && now < window.end

/** A REST receipt can inherit an old websocket timestamp, so it cannot form a bar. */
export function chartTickEpoch(
  window: ChartSessionWindow | null,
  timestamp: string | number | undefined,
  now: number,
  source: 'websocket' | 'rest' | undefined
): number | null {
  if (source !== 'websocket' || !chartSessionOpen(window, now)) return null
  const epoch = recentTickEpoch(timestamp, now)
  return epoch != null && epoch >= window!.start! && epoch < window!.end! ? epoch : null
}
