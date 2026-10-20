import type { Quote } from '@/api/kotakAssistant'
import { chartIndicators } from './chartIndicators'
import { type ChartSessionWindow, chartSessionOpen, chartTickEpoch } from './chartSession'

export type IndicatorCandle = Parameters<typeof chartIndicators>[0][number]
const IST_OFFSET = 19800
const SECONDS: Record<string, number> = { '1m': 60, '5m': 300, '15m': 900 }

export function tradeIndicators(
  candles: IndicatorCandle[],
  quote: Quote | undefined,
  interval: string,
  now: number,
  session: ChartSessionWindow | null = null
) {
  const sec = SECONDS[interval]
  const bucket = sec ? Math.floor((now + IST_OFFSET) / sec) * sec : NaN
  const marketOpen = chartSessionOpen(session, now)
  const tick = chartTickEpoch(
    session,
    quote?.timestamp ?? quote?.observed_time,
    now,
    quote?.source === 'Live feed' ? 'websocket' : undefined
  )
  const age = tick == null ? NaN : now - tick
  const tickBucket = tick == null || !sec ? NaN : Math.floor((tick + IST_OFFSET) / sec) * sec
  const priceFresh =
    !!quote &&
    Number.isFinite(quote.ltp) &&
    quote.ltp! > 0 &&
    age >= 0 &&
    age <= 5 &&
    tickBucket === bucket
  const bars = [...new Map(candles.map((bar) => [bar.time, bar])).values()]
    .filter((bar) => bar.time <= bucket)
    .sort((a, b) => a.time - b.time)
  const invalid = bars.some(
    (bar) =>
      ![bar.time, bar.open, bar.high, bar.low, bar.close].every(Number.isFinite) ||
      bar.close <= 0 ||
      bar.low <= 0 ||
      bar.high < bar.low
  )
  const latest = bars.at(-1)
  const historyRecent = !!latest && latest.time >= bucket - sec && !invalid
  // Only extend an adjacent candle. A fresh tick cannot repair missing history.
  if (priceFresh && historyRecent) {
    const ltp = quote.ltp!
    if (latest.time === bucket) {
      bars[bars.length - 1] = {
        ...latest,
        close: ltp,
        high: Math.max(latest.high, ltp),
        low: Math.min(latest.low, ltp),
      }
    } else {
      bars.push({ time: bucket, open: ltp, high: ltp, low: ltp, close: ltp, volume: NaN })
    }
  }
  const rsi = invalid ? null : (chartIndicators(bars).at(-1)?.rsi14 ?? null)
  const closed = [...bars].reverse().find((bar) => bar.time < bucket)
  const sessionStart = session?.start == null ? NaN : session.start + IST_OFFSET
  const sessionClosed = bars.filter((bar) => bar.time >= sessionStart && bar.time < bucket)
  const completeSession =
    bucket >= sessionStart &&
    sessionClosed.length === (bucket - sessionStart) / sec &&
    sessionClosed.every(
      (bar, i) =>
        bar.time === sessionStart + i * sec && Number.isFinite(bar.volume) && bar.volume >= 0
    )
  const completedVolume = sessionClosed.reduce((total, bar) => total + bar.volume, 0)
  const counterCurrent =
    priceFresh &&
    historyRecent &&
    completeSession &&
    quote?.volume != null &&
    Number.isFinite(quote.volume) &&
    quote.volume >= completedVolume
      ? quote.volume - completedVolume
      : null
  const current = bars.find((bar) => bar.time === bucket)
  const currentVolume = marketOpen
    ? (counterCurrent ??
      (current && Number.isFinite(current.volume) && current.volume >= 0 ? current.volume : null))
    : null
  return {
    rsi,
    priceFresh,
    live: rsi != null && priceFresh && historyRecent,
    reason: invalid
      ? 'Invalid candle data'
      : !latest
        ? 'Waiting for candles'
        : rsi == null
          ? 'Need 15 candles for RSI 14'
          : !marketOpen
            ? session
              ? 'Market closed'
              : 'Exchange session unverified'
            : !historyRecent
              ? 'Candles delayed'
              : !priceFresh
                ? 'Waiting for fresh price'
                : 'Forming candle',
    barTime: bars.at(-1)?.time ?? null,
    currentVolume,
    currentTime: marketOpen ? bucket : null,
    volumeSource: counterCurrent != null ? 'Live day counter − closed bars' : 'Latest candle feed',
    closedVolume:
      closed && Number.isFinite(closed.volume) && closed.volume >= 0 ? closed.volume : null,
    closedTime: closed?.time ?? null,
  }
}

export function indicatorTime(time: number | null) {
  return time == null || !Number.isFinite(time)
    ? '—'
    : new Date((time - IST_OFFSET) * 1000).toLocaleTimeString('en-GB', {
        timeZone: 'Asia/Kolkata',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
}
