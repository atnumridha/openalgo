import type { UTCTimestamp } from 'lightweight-charts'

export interface PriceBar {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}
export interface GapZone {
  time: number
  end: number
  low: number
  high: number
  bullish: boolean
}
const day = (t: number) => Math.floor((t + 19800) / 86400)
export function chartBars(input: PriceBar[]): PriceBar[] {
  const unique = new Map<number, PriceBar>()
  for (const raw of input) {
    const b = { ...raw, time: raw.time - 19800 }
    if (
      [b.time, b.open, b.high, b.low, b.close, b.volume].every(Number.isFinite) &&
      b.time > 0 &&
      b.low > 0 &&
      b.low <= Math.min(b.open, b.close) &&
      b.high >= Math.max(b.open, b.close)
    )
      unique.set(b.time, b)
  }
  return [...unique.values()].sort((a, b) => a.time - b.time)
}
export function formatIST(t: number, withDate = false) {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    ...(withDate ? ({ day: '2-digit', month: 'short' } as const) : {}),
  }).format(new Date(t * 1000))
}
export function computeStudies(bars: PriceBar[]) {
  const upper: Array<{ time: UTCTimestamp; value: number }> = [],
    lower: typeof upper = [],
    ema: typeof upper = [],
    rsi: typeof upper = []
  let seed = 0,
    gain = 0,
    loss = 0
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i],
      time = b.time as UTCTimestamp
    seed = i === 0 ? b.close : seed + (2 / 201) * (b.close - seed)
    ema.push({ time, value: seed })
    if (i >= 20) {
      const prior = bars.slice(i - 20, i)
      upper.push({ time, value: Math.max(...prior.map((p) => p.high)) })
      lower.push({ time, value: Math.min(...prior.map((p) => p.low)) })
    }
    if (i > 0) {
      const d = b.close - bars[i - 1].close
      if (i <= 14) {
        gain += Math.max(0, d) / 14
        loss += Math.max(0, -d) / 14
      } else {
        gain = (gain * 13 + Math.max(0, d)) / 14
        loss = (loss * 13 + Math.max(0, -d)) / 14
      }
      if (i >= 14)
        rsi.push({
          time,
          value: loss === 0 ? (gain === 0 ? 50 : 100) : 100 - 100 / (1 + gain / loss),
        })
    }
  }
  const zones: GapZone[] = [],
    last = bars.length - 1,
    close = bars[last]?.close ?? 0
  const supports: number[] = [],
    resistances: number[] = []
  for (let i = Math.max(3, bars.length - 120); i + 3 < last; i++) {
    const window = bars.slice(i - 3, i + 4),
      b = bars[i]
    if (window.every((p, j) => j === 3 || p.high < b.high) && b.high >= close)
      resistances.push(b.high)
    if (window.every((p, j) => j === 3 || p.low > b.low) && b.low <= close) supports.push(b.low)
  }
  for (let i = Math.max(2, bars.length - 120); i < last; i++) {
    const b = bars[i],
      prev = bars[i - 2]
    if (day(b.time) !== day(prev.time)) continue
    const bullish = b.low > prev.high,
      bearish = b.high < prev.low
    if (!bullish && !bearish) continue
    const low = bullish ? prev.high : b.high,
      high = bullish ? b.low : prev.low
    if (bars.slice(i + 1).some((p) => (bullish ? p.low <= low : p.high >= high))) continue
    zones.push({ time: b.time, end: bars[last].time, low, high, bullish })
  }
  zones.sort(
    (a, b) =>
      Math.min(Math.abs(close - a.low), Math.abs(close - a.high)) -
      Math.min(Math.abs(close - b.low), Math.abs(close - b.high))
  )
  return {
    upper,
    lower,
    ema,
    rsi,
    zones: zones.slice(0, 3),
    support: supports.length ? Math.max(...supports) : null,
    resistance: resistances.length ? Math.min(...resistances) : null,
  }
}
export function openingRange(bars: PriceBar[]) {
  const last = bars.at(-1)
  if (!last) return null
  const today = bars.filter((b) => day(b.time) === day(last.time))
  const minutes = (t: number) => Math.floor(((t + 19800) % 86400) / 60)
  if (minutes(last.time) < 570) return null
  const opening = today.filter((b) => minutes(b.time) >= 555 && minutes(b.time) < 570)
  return opening.length && minutes(opening[0].time) === 555
    ? { high: Math.max(...opening.map((b) => b.high)), low: Math.min(...opening.map((b) => b.low)) }
    : null
}

export function reconcileHistory(history: PriceBar[], live: PriceBar | null) {
  const merged = [...history],
    last = merged.at(-1)
  if (!live || !last || live.time < last.time) return merged
  if (live.time > last.time) merged.push(live)
  else
    merged[merged.length - 1] = {
      ...last,
      high: Math.max(last.high, live.high),
      low: Math.min(last.low, live.low),
      close: live.close,
      volume: Math.max(last.volume, live.volume),
    }
  return merged
}
