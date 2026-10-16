import type { IndicatorCandle } from './tradeIndicatorsModel'

export const REPLAY_IST_OFFSET = 19800
export type ReplayCandle = IndicatorCandle
export const replaySeconds = (interval: string) => {
  const parts = /^(\d+)(s|m|h|d)$/.exec(interval)
  return parts ? Number(parts[1]) * ({ s: 1, m: 60, h: 3600, d: 86400 }[parts[2]] || 0) : 0
}
export interface ReplaySnapshot {
  seconds: number
  timeline: number[]
  series: Record<string, ReplayCandle[]>
}
export interface ReplayFrame extends ReplaySnapshot {
  scope: string
  until: number
}
export interface ChartReplay {
  bars: ReplayCandle[]
  until: number
  seconds: number
}

/** Snapshots use the chart's IST-shifted axis and completed candles only. */
export function freezeReplay(
  inputs: { key: string; bars: readonly ReplayCandle[] }[],
  interval: string,
  nowUtc: number,
  sessionDate?: string,
  sessionEndDate = sessionDate
): ReplaySnapshot | null {
  const seconds = replaySeconds(interval)
  const bounds = sessionDate
    ? chartRangeBounds(sessionDate, sessionEndDate!, REPLAY_IST_OFFSET)
    : null
  if (sessionDate && !bounds) return null
  if (!seconds || !inputs.length || !Number.isFinite(nowUtc)) return null
  const series: Record<string, ReplayCandle[]> = {}
  for (const { key, bars } of inputs) {
    series[key] = [...new Map(bars.map((bar) => [bar.time, bar])).values()]
      .filter(
        (bar) =>
          [bar.time, bar.open, bar.high, bar.low, bar.close].every(Number.isFinite) &&
          bar.low > 0 &&
          bar.low <= Math.min(bar.open, bar.close) &&
          bar.high >= Math.max(bar.open, bar.close) &&
          bar.time + seconds <= nowUtc + REPLAY_IST_OFFSET &&
          (!bounds || bar.time < bounds.end)
      )
      .sort((a, b) => a.time - b.time)
      .map((bar) => ({ ...bar }))
    if (!series[key].length) return null
  }
  let timeline = series[inputs[0].key]
    .filter((bar) => !bounds || (bar.time >= bounds.start && bar.time < bounds.end))
    .map((bar) => bar.time + seconds)
  for (const { key } of inputs.slice(1)) {
    const ends = new Set(series[key].map((bar) => bar.time + seconds))
    timeline = timeline.filter((time) => ends.has(time))
  }
  return timeline.length < 2 ? null : { seconds, series, timeline }
}

export const replayBars = (bars: ReplayCandle[], seconds: number, until: number) =>
  bars.filter((bar) => bar.time + seconds <= until)

export const replayInput = (axisTime: number) =>
  new Date(axisTime * 1000).toISOString().slice(0, 16)
export function parseReplayInput(value: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null
  const time = Date.parse(`${value}:00Z`) / 1000
  return Number.isFinite(time) && replayInput(time) === value ? time : null
}
export function replayIndex(timeline: number[], requested: number) {
  for (let i = timeline.length - 1; i >= 0; i--) if (timeline[i] <= requested) return i
  return -1
}
export const replayStamp = (axisTime: number) =>
  `${new Date(axisTime * 1000).toLocaleString('en-GB', {
    timeZone: 'UTC',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })} IST`

/** Calendar dates always use IST, independently of the browser or machine timezone. */
export const istSessionDate = (nowUtc = Date.now() / 1000) =>
  new Date((nowUtc + REPLAY_IST_OFFSET) * 1000).toISOString().slice(0, 10)

/** Bounds for true UTC candles, or the shared cache's shifted axis when offset is 19800. */
export function sessionBounds(date: string, axisOffset = 0) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null
  const midnight = Date.parse(`${date}T00:00:00Z`) / 1000
  if (!Number.isFinite(midnight) || new Date(midnight * 1000).toISOString().slice(0, 10) !== date)
    return null
  const start = midnight - REPLAY_IST_OFFSET + axisOffset
  return { start, end: start + 86400 }
}

export function sessionBars<T extends { time: number }>(
  bars: readonly T[],
  date: string,
  axisOffset = 0
): T[] {
  const bounds = sessionBounds(date, axisOffset)
  return bounds ? bars.filter((b) => b.time >= bounds.start && b.time < bounds.end) : []
}

export interface ChartDateRange {
  start: string
  end: string
}
export function chartRangeBounds(start: string, end = start, axisOffset = 0) {
  const first = sessionBounds(start, axisOffset),
    last = sessionBounds(end, axisOffset)
  return first && last && first.start <= last.start ? { start: first.start, end: last.end } : null
}
export function chartRangeBars<T extends { time: number }>(
  bars: readonly T[],
  start: string,
  end = start,
  axisOffset = 0
): T[] {
  const bounds = chartRangeBounds(start, end, axisOffset)
  return bounds ? bars.filter((b) => b.time >= bounds.start && b.time < bounds.end) : []
}
