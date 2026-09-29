/**
 * Completed-bar overlays for strategy charts.
 *
 * EMA / SMA / Bollinger match the pandas formulas used by the engine:
 * EMA is ewm(span, adjust=False); SMA and Bollinger use rolling windows with
 * sample std (ddof=1) on Bollinger. Values before min_periods stay null so
 * the chart never invents a signal on incomplete history.
 */

export interface OverlayBar {
  time: number
  open: number
  high: number
  low: number
  close: number
}

export type OverlayPoint = { time: number; value: number }

function ema(closes: number[], span: number, minPeriods: number): Array<number | null> {
  const alpha = 2 / (span + 1)
  const out: Array<number | null> = []
  let prev = 0
  for (let i = 0; i < closes.length; i++) {
    prev = i === 0 ? closes[i] : alpha * closes[i] + (1 - alpha) * prev
    out.push(i + 1 >= minPeriods ? prev : null)
  }
  return out
}

function sma(closes: number[], window: number): Array<number | null> {
  const out: Array<number | null> = []
  let sum = 0
  for (let i = 0; i < closes.length; i++) {
    sum += closes[i]
    if (i >= window) sum -= closes[i - window]
    out.push(i + 1 >= window ? sum / window : null)
  }
  return out
}

function rollingStd(closes: number[], window: number): Array<number | null> {
  const out: Array<number | null> = []
  for (let i = 0; i < closes.length; i++) {
    if (i + 1 < window) {
      out.push(null)
      continue
    }
    const slice = closes.slice(i + 1 - window, i + 1)
    const mean = slice.reduce((a, b) => a + b, 0) / window
    const variance = slice.reduce((a, b) => a + (b - mean) ** 2, 0) / (window - 1)
    out.push(Math.sqrt(variance))
  }
  return out
}

function series(bars: OverlayBar[], values: Array<number | null>): OverlayPoint[] {
  const points: OverlayPoint[] = []
  for (let i = 0; i < bars.length; i++) {
    const value = values[i]
    if (value == null || !Number.isFinite(value)) continue
    points.push({ time: bars[i].time, value })
  }
  return points
}

export function emaSeries(bars: OverlayBar[], span: number, minPeriods = span): OverlayPoint[] {
  return series(
    bars,
    ema(
      bars.map((b) => b.close),
      span,
      minPeriods
    )
  )
}

export function smaSeries(bars: OverlayBar[], window: number): OverlayPoint[] {
  return series(
    bars,
    sma(
      bars.map((b) => b.close),
      window
    )
  )
}

export function bollingerSeries(bars: OverlayBar[], window = 20, width = 2) {
  const closes = bars.map((b) => b.close)
  const mean = sma(closes, window)
  const std = rollingStd(closes, window)
  const middle: OverlayPoint[] = []
  const upper: OverlayPoint[] = []
  const lower: OverlayPoint[] = []
  for (let i = 0; i < bars.length; i++) {
    if (mean[i] == null || std[i] == null) continue
    const mid = mean[i] as number
    const band = width * (std[i] as number)
    middle.push({ time: bars[i].time, value: mid })
    upper.push({ time: bars[i].time, value: mid + band })
    lower.push({ time: bars[i].time, value: mid - band })
  }
  return { middle, upper, lower }
}

export function macdSeries(bars: OverlayBar[]) {
  const closes = bars.map((b) => b.close)
  const fast = ema(closes, 12, 12)
  const slow = ema(closes, 26, 26)
  const macdLine: Array<number | null> = closes.map((_, i) =>
    fast[i] == null || slow[i] == null ? null : (fast[i] as number) - (slow[i] as number)
  )
  const macdForSignal: number[] = []
  for (const value of macdLine) {
    if (value == null) continue
    macdForSignal.push(value)
  }
  const signalEma = ema(macdForSignal, 9, 9)
  let signalIndex = 0
  const signalLine: Array<number | null> = macdLine.map((value) => {
    if (value == null) return null
    const point = signalEma[signalIndex]
    signalIndex += 1
    return point
  })
  return {
    macd: series(bars, macdLine),
    signal: series(bars, signalLine),
  }
}

/** First 15 one-minute IST bars of the session (09:15–09:29), as used by box15. */
export function lastBarBiasMarker(
  bars: OverlayBar[],
  indicators: string[]
): { time: number; kind: 'signal-buy' | 'signal-sell'; label: string } | null {
  if (!bars.length) return null
  const last = bars[bars.length - 1]
  const lastPoint = (points: OverlayPoint[]) =>
    points.length && points[points.length - 1].time === last.time
      ? points[points.length - 1].value
      : null
  let buy = last.close > last.open
  let sell = last.close < last.open
  if (indicators.includes('ema9') && indicators.includes('ema15')) {
    const fast = lastPoint(emaSeries(bars, 9, 75))
    const slow = lastPoint(emaSeries(bars, 15, 75))
    if (fast == null || slow == null) return null
    buy = fast > slow && last.close > last.open
    sell = fast < slow && last.close < last.open
  } else if (indicators.includes('ema5')) {
    const value = lastPoint(emaSeries(bars, 5, 5))
    if (value == null) return null
    buy = last.close > value
    sell = last.close < value
  } else if (indicators.includes('ema50') && indicators.includes('ema200')) {
    const fast = lastPoint(emaSeries(bars, 50, 50))
    const slow = lastPoint(emaSeries(bars, 200, 200))
    if (fast == null || slow == null) return null
    buy = fast > slow && last.close > last.open
    sell = fast < slow && last.close < last.open
  } else if (indicators.includes('sma5') && indicators.includes('sma34')) {
    const fast = lastPoint(smaSeries(bars, 5))
    const slow = lastPoint(smaSeries(bars, 34))
    if (fast == null || slow == null) return null
    buy = fast > slow && last.close > last.open
    sell = fast < slow && last.close < last.open
  } else if (indicators.includes('bollinger')) {
    const bands = bollingerSeries(bars, 20, 2)
    const lower = lastPoint(bands.lower)
    const upper = lastPoint(bands.upper)
    if (lower == null || upper == null) return null
    buy = last.close < lower
    sell = last.close > upper
  } else if (indicators.includes('macd')) {
    const macd = macdSeries(bars)
    const line = lastPoint(macd.macd)
    const signal = lastPoint(macd.signal)
    if (line == null || signal == null) return null
    buy = line > signal && last.close > last.open
    sell = line < signal && last.close < last.open
  } else if (indicators.includes('openingRange')) {
    const range = openingRange(bars)
    if (!range) return null
    buy = last.close > range.high
    sell = last.close < range.low
  }
  if (!buy && !sell) return null
  return { time: last.time, kind: buy ? 'signal-buy' : 'signal-sell', label: buy ? 'BUY' : 'SELL' }
}

export function emaBiasMarker(bars: OverlayBar[]) {
  return lastBarBiasMarker(bars, ['ema9', 'ema15'])
}

export function isPlausibleLivePrice(
  ltp: number,
  lastClose: number | null,
  maxDeviation = 0.25
): boolean {
  if (!Number.isFinite(ltp) || ltp <= 0) return false
  if (lastClose == null || !Number.isFinite(lastClose) || lastClose <= 0) return true
  return Math.abs(ltp - lastClose) / lastClose <= maxDeviation
}

/** Keep the newest contiguous price regime and discard corrupt/cross-symbol history. */
export function plausibleHistoryTail<T extends OverlayBar>(
  bars: T[],
  maxDeviation = 0.25,
  referencePrice: number | null = null
): T[] {
  const valid = bars.filter(
    (bar) =>
      Number.isFinite(bar.time) &&
      Number.isFinite(bar.open) &&
      Number.isFinite(bar.high) &&
      Number.isFinite(bar.low) &&
      Number.isFinite(bar.close) &&
      bar.open > 0 &&
      bar.high > 0 &&
      bar.low > 0 &&
      bar.close > 0 &&
      bar.high >= Math.max(bar.open, bar.close, bar.low) &&
      bar.low <= Math.min(bar.open, bar.close, bar.high)
  ).sort((a, b) => a.time - b.time)
  if (valid.length < 2) return valid

  let end = valid.length - 1
  if (Number.isFinite(referencePrice) && (referencePrice as number) > 0) {
    while (
      end >= 0 &&
      Math.abs(valid[end].close - (referencePrice as number)) /
        Math.max(valid[end].close, referencePrice as number) >
        maxDeviation
    ) {
      end -= 1
    }
    if (end < 0) return []
  }

  const anchor = Number.isFinite(referencePrice) && (referencePrice as number) > 0
    ? (referencePrice as number)
    : valid[end].close
  return valid.filter(
    (bar) =>
      Math.abs(bar.close - anchor) / Math.max(bar.close, anchor) <= maxDeviation
  )
}

export function openingRange(bars: OverlayBar[], sessionStartHour = 9, sessionStartMinute = 15) {
  if (!bars.length) return null
  const session = sessionStartHour * 60 + sessionStartMinute
  const rangeEnd = session + 15
  let high = Number.NEGATIVE_INFINITY
  let low = Number.POSITIVE_INFINITY
  let found = false
  for (const bar of bars) {
    const minutes = Math.floor((bar.time % 86400) / 60)
    if (minutes < session || minutes >= rangeEnd) continue
    found = true
    high = Math.max(high, bar.high)
    low = Math.min(low, bar.low)
  }
  if (!found) return null
  return { high, low }
}
