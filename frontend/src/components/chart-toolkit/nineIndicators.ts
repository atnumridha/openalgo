import type { PlanSession } from '../neo-desk/chartTradePlan'
import { ToolkitEngine, closeTime, type Bar, type Metrics } from './model'

export type IndicatorKey = 'rsi' | 'bb' | 'iv' | 'imi' | 'mfi' | 'pcr' | 'oi' | 'macd' | 'ma'

export const INDICATORS: Array<{ key: IndicatorKey; id: string; label: string; short: string }> = [
  { key: 'rsi', id: 'nine-rsi', label: 'Relative Strength Index', short: 'RSI' },
  { key: 'bb', id: 'nine-bb', label: 'Bollinger Bands', short: 'BB' },
  { key: 'iv', id: 'nine-iv', label: 'Implied Volatility', short: 'IV' },
  { key: 'imi', id: 'nine-imi', label: 'Intraday Momentum Index', short: 'IMI' },
  { key: 'mfi', id: 'nine-mfi', label: 'Money Flow Index', short: 'MFI' },
  { key: 'pcr', id: 'nine-pcr', label: 'Put / Call Ratio', short: 'PCR' },
  { key: 'oi', id: 'nine-oi', label: 'Open Interest', short: 'OI' },
  { key: 'macd', id: 'nine-macd', label: 'MACD', short: 'MACD' },
  { key: 'ma', id: 'nine-ma', label: 'Moving Averages', short: 'MA' },
]

export type TradeSide = 'CALL' | 'PUT' | 'WAIT'

export interface IndicatorState {
  key: IndicatorKey
  value: number | null
  side: TradeSide
  time: number | null
  reason: string
}

export interface IndicatorEvent {
  key: IndicatorKey
  time: number
  side: 'CALL' | 'PUT'
  price: number
}

export interface NineResult {
  states: IndicatorState[]
  events: IndicatorEvent[]
  lastTime: number | null
  bias: TradeSide
}

type PriceKey = Exclude<IndicatorKey, 'iv' | 'pcr' | 'oi'>
interface PricePoint {
  bar: Bar
  metrics: Metrics
  ema20: number | null
  sma50: number | null
  bias: TradeSide
}

const external = new Set<IndicatorKey>(['iv', 'pcr', 'oi'])
const finite = (value: number | null): value is number => value != null && Number.isFinite(value)
const neutral = (
  key: IndicatorKey,
  reason: string,
  value: number | null = null
): IndicatorState => ({
  key,
  value,
  side: 'WAIT',
  time: null,
  reason,
})

function validPrice(bar: Bar): boolean {
  return (
    [bar.time, bar.open, bar.high, bar.low, bar.close].every(Number.isFinite) &&
    Math.min(bar.open, bar.high, bar.low, bar.close) > 0 &&
    bar.high >= Math.max(bar.open, bar.close) &&
    bar.low <= Math.min(bar.open, bar.close)
  )
}

function direction(close: number, ema20: number | null, sma50: number | null): TradeSide {
  if (!finite(ema20) || !finite(sma50)) return 'WAIT'
  if (close > ema20 && close > sma50) return 'CALL'
  if (close < ema20 && close < sma50) return 'PUT'
  return 'WAIT'
}

function crossed(
  previous: number | null,
  current: number | null,
  low: number,
  high: number
): TradeSide {
  if (!finite(previous) || !finite(current)) return 'WAIT'
  if (previous <= low && current > low) return 'CALL'
  if (previous >= high && current < high) return 'PUT'
  return 'WAIT'
}

function valueAt(key: PriceKey, point: PricePoint): number | null {
  // BB displays width in percent; MA displays the close's percent distance from SMA50.
  if (key === 'bb') return point.metrics.bbWidth
  if (key === 'ma') return finite(point.sma50) ? 100 * (point.bar.close / point.sma50 - 1) : null
  return point.metrics[key]
}

function ready(key: PriceKey, point: PricePoint): boolean {
  if (key === 'bb') return finite(point.metrics.bbHigh) && finite(point.metrics.bbLow)
  if (key === 'macd') return finite(point.metrics.macd) && finite(point.metrics.signal)
  if (key === 'ma') return finite(point.ema20) && finite(point.sma50)
  return finite(point.metrics[key])
}

function transition(key: PriceKey, previous: PricePoint, point: PricePoint): TradeSide {
  if (!ready(key, previous) || !ready(key, point)) return 'WAIT'
  const prior = previous.metrics,
    current = point.metrics
  switch (key) {
    case 'rsi':
    case 'imi':
      return crossed(prior[key], current[key], 30, 70)
    case 'mfi':
      return crossed(prior.mfi, current.mfi, 20, 80)
    case 'macd':
      return crossed(prior.macd! - prior.signal!, current.macd! - current.signal!, 0, 0)
    case 'bb':
      if (previous.bar.close <= prior.bbHigh! && point.bar.close > current.bbHigh!) return 'CALL'
      if (previous.bar.close >= prior.bbLow! && point.bar.close < current.bbLow!) return 'PUT'
      return 'WAIT'
    case 'ma':
      return point.bias !== 'WAIT' && point.bias !== previous.bias ? point.bias : 'WAIT'
  }
}

/** Independent historical chart observations; this engine does not combine indicator votes. */
export class NineIndicatorEngine {
  private readonly toolkit = new ToolkitEngine()

  update(
    input: Bar[],
    {
      seconds,
      asOf,
      indian = false,
      continuous = false,
      session,
    }: {
      seconds: number
      asOf: number
      indian?: boolean
      continuous?: boolean
      session?: PlanSession | null
    }
  ): NineResult {
    const validTiming = Number.isFinite(seconds) && seconds > 0 && Number.isFinite(asOf)
    // A broker correction replaces its timestamp. Do not mutate the caller's history.
    const byTime = new Map<number, Bar>()
    if (validTiming)
      for (const bar of input)
        if (Number.isFinite(bar.time) && bar.time <= asOf) byTime.set(bar.time, bar)
    const bars = [...byTime.values()]
      .filter((bar) => validPrice(bar) && closeTime(bar, seconds, indian, session) <= asOf)
      .sort((a, b) => a.time - b.time)
    if (bars.length === 0)
      return {
        states: INDICATORS.map(({ key }) =>
          neutral(
            key,
            external.has(key)
              ? 'Waiting for validated market context'
              : 'Waiting for closed candles'
          )
        ),
        events: [],
        lastTime: null,
        bias: 'WAIT',
      }

    // Only the closed prefix is supplied, so shared live-preview metrics cannot leak into signals.
    const shared = this.toolkit.update(bars, { seconds, asOf, indian, continuous, session })
    const events: IndicatorEvent[] = []
    const lastEvents = new Map<IndicatorKey, IndicatorEvent>()
    let ema20: number | null = null
    let rolling50 = 0
    let previous: PricePoint | undefined
    let latest: PricePoint | undefined
    let segmentCount = 0
    for (let i = 0; i < bars.length; i++) {
      const bar = bars[i]
      if (continuous && i > 0 && bar.time - bars[i - 1].time !== seconds) {
        ema20 = null
        rolling50 = 0
        previous = undefined
        segmentCount = 0
        lastEvents.clear()
      }
      segmentCount++
      ema20 = ema20 == null ? bar.close : ema20 + (2 / 21) * (bar.close - ema20)
      rolling50 += bar.close
      if (segmentCount > 50) rolling50 -= bars[i - 50].close
      const sma50 = segmentCount >= 50 ? rolling50 / 50 : null
      const point: PricePoint = {
        bar,
        metrics: shared.points[i].metrics,
        ema20: segmentCount >= 20 ? ema20 : null,
        sma50,
        bias: direction(bar.close, segmentCount >= 20 ? ema20 : null, sma50),
      }
      // Keep numeric history across sessions; a missing/invalid interval cannot create an entry.
      if (previous && bar.time === previous.bar.time + seconds)
        for (const { key } of INDICATORS) {
          if (external.has(key)) continue
          const side = transition(key as PriceKey, previous, point)
          if (side === 'WAIT') continue
          const event: IndicatorEvent = {
            key,
            time: bar.time,
            side,
            price: side === 'CALL' ? bar.low : bar.high,
          }
          events.push(event)
          lastEvents.set(key, event)
        }
      previous = point
      latest = point
    }
    const current = latest!
    const states = INDICATORS.map(({ key, short }): IndicatorState => {
      if (external.has(key)) return neutral(key, 'Waiting for validated market context')
      const priceKey = key as PriceKey
      const value = valueAt(priceKey, current)
      if (key === 'mfi' && !finite(current.metrics.mfi) && bars.length >= 15)
        return neutral(
          key,
          'MFI unavailable: genuine positive volume is required for every flow candle'
        )
      if (!ready(priceKey, current)) return neutral(key, `${short} warming up`, value)
      const event = lastEvents.get(key)
      if (!event) return neutral(key, `${short}: no confirmed event`, value)
      const detail =
        key === 'bb'
          ? '; value is band width %'
          : key === 'ma'
            ? '; value is close vs SMA50 %, using EMA20 / SMA50'
            : ''
      return {
        key,
        value,
        side: event.side,
        time: event.time,
        reason: `Last confirmed event: BUY ${event.side}${detail}`,
      }
    })
    return { states, events, lastTime: current.bar.time, bias: current.bias }
  }
}
