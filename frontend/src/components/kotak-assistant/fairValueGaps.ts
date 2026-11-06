export interface FvgCandle {
  time: number
  open: number
  high: number
  low: number
  close: number
}

export interface FairValueGap {
  id: string
  direction: 'bullish' | 'bearish'
  lower: number
  upper: number
  startTime: number
  confirmedAt: number
  touched: boolean
}

/** Keep the three unfilled zones nearest the displayed price. */
export function nearbyFairValueGaps(gaps: FairValueGap[], price: number, limit = 3) {
  const distance = (gap: FairValueGap) =>
    price >= gap.lower && price <= gap.upper
      ? 0
      : Math.min(Math.abs(price - gap.lower), Math.abs(price - gap.upper))
  return [...gaps]
    .sort((a, b) => distance(a) - distance(b) || b.confirmedAt - a.confirmedAt)
    .slice(0, limit)
}
const IST_AXIS_OFFSET_SECONDS = 19800
const SECONDS_PER_DAY = 86400
const MAX_CANDLES = 600

function validCandle(bar: FvgCandle): boolean {
  return (
    [bar.time, bar.open, bar.high, bar.low, bar.close].every(Number.isFinite) &&
    bar.low <= bar.open &&
    bar.low <= bar.close &&
    bar.high >= bar.open &&
    bar.high >= bar.close
  )
}

/** Finds active three-candle wick gaps; candle times use the chart's IST axis. */
export function fairValueGaps(
  input: readonly FvgCandle[],
  intervalSeconds: number,
  nowUtc: number,
  continuous = false
): FairValueGap[] {
  if (!Number.isFinite(intervalSeconds) || intervalSeconds <= 0 || !Number.isFinite(nowUtc))
    return []

  const nowAxis = nowUtc + IST_AXIS_OFFSET_SECONDS
  const observed = input
    .filter((bar) => Number.isFinite(bar.time) && bar.time <= nowAxis)
    .sort((left, right) => left.time - right.time)
    .slice(-MAX_CANDLES)
    .filter(validCandle)
  let gaps: FairValueGap[] = []
  for (let index = 0; index < observed.length; index++) {
    const third = observed[index]
    if (continuous && index > 0 && third.time - observed[index - 1].time !== intervalSeconds)
      gaps = []
    gaps = gaps.filter((gap) => {
      const filled = gap.direction === 'bullish' ? third.low <= gap.lower : third.high >= gap.upper
      if (filled) return false
      if (gap.direction === 'bullish' ? third.low < gap.upper : third.high > gap.lower) {
        gap.touched = true
      }
      return true
    })

    if (index < 2 || third.time + intervalSeconds > nowAxis) continue
    const first = observed[index - 2]
    const middle = observed[index - 1]
    if (
      middle.time - first.time !== intervalSeconds ||
      third.time - middle.time !== intervalSeconds ||
      (!continuous &&
        Math.floor(first.time / SECONDS_PER_DAY) !== Math.floor(third.time / SECONDS_PER_DAY))
    ) {
      continue
    }

    const direction = third.low > first.high ? 'bullish' : third.high < first.low ? 'bearish' : null
    if (direction) {
      gaps.push({
        id: `${direction}:${first.time}:${third.time}`,
        direction,
        lower: direction === 'bullish' ? first.high : third.high,
        upper: direction === 'bullish' ? third.low : first.low,
        startTime: middle.time,
        confirmedAt: third.time + intervalSeconds,
        touched: false,
      })
    }
  }
  return gaps
}
