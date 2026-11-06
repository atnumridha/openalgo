import type { SymbolData } from '@/lib/MarketDataManager'
import { feedTimeMs, nextLiveBar } from '../neo-desk/liveBars'
import { closeTime, ToolkitEngine, type Bar } from './model'
import type { IndicatorKey } from './nineIndicators'

interface PreviewOptions {
  symbol: string
  exchange: string
  interval: string
  seconds: number
  now: number
  isAuthenticated: boolean
  connectionEpoch: number
}
export interface LiveValues {
  values: Partial<Record<IndicatorKey, number | null>>
  time: number
}
export class LiveIndicatorPreview {
  private readonly toolkit = new ToolkitEngine()
  private observation = 0
  private received = 0
  private feedTime = 0
  private forming: Bar | undefined

  update(
    bars: Bar[],
    observedAt: number,
    quote: SymbolData | undefined,
    options: PreviewOptions
  ): LiveValues | null {
    const { symbol, exchange, interval, seconds, now, isAuthenticated, connectionEpoch } = options
    const received = quote?.lastUpdate ?? 0
    const feedTime = feedTimeMs(quote?.data.timestamp)
    if (
      !isAuthenticated ||
      !quote ||
      quote.symbol !== symbol ||
      quote.exchange !== exchange ||
      quote.updateSource !== 'websocket' ||
      quote.connectionEpoch !== connectionEpoch ||
      !Number.isFinite(received) ||
      received > now ||
      now - received > 15000 ||
      feedTime == null ||
      feedTime > now ||
      now - feedTime > 15000 ||
      received < observedAt * 1000 ||
      feedTime < observedAt * 1000
    )
      return null
    if (this.observation !== observedAt) {
      this.observation = observedAt
      this.received = 0
      this.feedTime = 0
      this.forming = undefined
    }
    if (received < this.received || feedTime < this.feedTime) return null
    const latest = bars.at(-1)
    const tickBar = nextLiveBar(
      this.forming ?? latest,
      quote.data.ltp ?? 0,
      feedTime,
      interval,
      now
    )
    const projected: Bar | undefined = tickBar
      ? { ...tickBar, volume: latest?.volume ?? 0 }
      : undefined
    // A late subscription cannot reconstruct the open/high/low of a missed candle.
    // Wait for broker history rather than turning its first observed tick into an open.
    if (
      !latest ||
      !projected ||
      projected.time !== latest.time ||
      closeTime(projected, seconds, true) <= now / 1000 ||
      projected.time > observedAt
    )
      return null
    this.received = received
    this.feedTime = feedTime
    this.forming = projected
    const verified = bars.filter(
      (bar) => closeTime(bar, seconds, true) <= observedAt && bar.time < projected.time
    )
    const input = [...verified, projected]
    const { current } = this.toolkit.update(input, { seconds, asOf: now / 1000, indian: true })
    const sma50 =
      input.length >= 50 ? input.slice(-50).reduce((sum, b) => sum + b.close, 0) / 50 : null
    return {
      values: {
        rsi: current.rsi,
        imi: current.imi,
        bb: current.bbWidth,
        macd: current.macd,
        ma: sma50 ? 100 * (projected.close / sma50 - 1) : null,
      },
      time: received / 1000,
    }
  }
}
