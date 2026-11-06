import type { SymbolData } from '@/lib/MarketDataManager'
import { closeTime } from '../chart-toolkit/model'
import { feedTimeMs, nextLiveBar } from './liveBars'
import { replaySeconds } from '../kotak-assistant/chartReplay'
import { chartBars, type PriceBar } from './tradingViewStudies'

export interface StrikeHistory {
  status: string
  symbol: string
  exchange: string
  interval: string
  candles: PriceBar[]
  observedAt?: number
}
export interface StrikeRsiValue { value: number | null; source: 'live' | 'closed' | 'unavailable'; time: number | null }
export interface StrikeRsiSnapshot { scope: string; values: Record<string, StrikeRsiValue>; attempted: number; total: number }
const unavailable = (): StrikeRsiValue => ({ value: null, source: 'unavailable', time: null })
type RsiSeed = {count:number;previous:number;gain:number;loss:number}
const freshSeed = ():RsiSeed => ({count:0,previous:0,gain:0,loss:0})
function advance(seed:RsiSeed,price:number):RsiSeed {
  const delta=seed.count?price-seed.previous:0
  return {count:seed.count+1,previous:price,
    gain:seed.count>14?(seed.gain*13+Math.max(0,delta))/14:seed.gain+Math.max(0,delta)/14,
    loss:seed.count>14?(seed.loss*13+Math.max(0,-delta))/14:seed.loss+Math.max(0,-delta)/14}
}
const oscillator=(seed:RsiSeed)=>seed.count<15?null:seed.loss===0?(seed.gain===0?50:100):100-100/(1+seed.gain/seed.loss)
export class StrikeRsiCalculator {
  private latest: PriceBar|undefined
  private seed=freshSeed()
  private forming:PriceBar|undefined
  private received=0
  private feedTime=0
  private observedAt = 0
  private closed = unavailable()
  private readonly seconds: number
  private readonly symbol: string
  private readonly exchange: string
  private readonly interval: string
  constructor(symbol: string, exchange: string, interval: string) {
    this.symbol = symbol
    this.exchange = exchange
    this.interval = interval
    this.seconds = replaySeconds(interval)
  }
  load(history: StrikeHistory, observedAt: number): boolean {
    if (history.status !== 'success' || history.symbol !== this.symbol || history.exchange !== this.exchange || history.interval !== this.interval || !Array.isArray(history.candles) || !Number.isFinite(observedAt) || observedAt <= 0) {
      this.latest = undefined; this.closed = unavailable(); return false
    }
    this.observedAt = observedAt
    const bars = chartBars(history.candles).filter(b => b.time <= observedAt)
    this.latest=bars.at(-1);this.forming=undefined;this.received=0;this.feedTime=0
    this.seed=freshSeed()
    const closed=bars.filter(b=>closeTime(b,this.seconds,true)<=observedAt)
    for(const bar of closed)this.seed=advance(this.seed,bar.close)
    const value = oscillator(this.seed)
    this.closed = value != null && Number.isFinite(value)
      ? { value, source: 'closed', time: closeTime(closed.at(-1)!, this.seconds, true) }
      : unavailable()
    return true
  }
  value(quote: SymbolData | undefined, now: number, authenticated: boolean, epoch: number): StrikeRsiValue {
    if (!this.latest || now / 1000 < this.observedAt) return unavailable()
    const received=quote?.lastUpdate??0,stamp=feedTimeMs(quote?.data.timestamp)
    if(!authenticated || !quote || quote.symbol!==this.symbol || quote.exchange!==this.exchange ||
       quote.updateSource!=='websocket' || quote.connectionEpoch!==epoch || !Number.isFinite(received) ||
       received>now || now-received>15000 || stamp==null || stamp>now || now-stamp>15000 ||
       received<this.observedAt*1000 || stamp<this.observedAt*1000 || received<this.received || stamp<this.feedTime)
      return this.closed
    const raw=nextLiveBar(this.forming??this.latest,quote.data.ltp??0,stamp,this.interval,now)
    const projected=raw?{...raw,volume:this.latest.volume}:null
    if(!projected || projected.time!==this.latest.time || closeTime(projected,this.seconds,true)<=now/1000 || projected.time>this.observedAt)
      return this.closed
    this.received=received;this.feedTime=stamp;this.forming={...projected,volume:this.latest.volume}
    // The verified prefix is immutable until history refreshes. A quote projects
    // just one Wilder step; it never runs structure/MACD or confirms a new bar.
    const value=oscillator(advance(this.seed,projected.close))
    return value!=null && Number.isFinite(value)?{value,source:'live',time:received/1000}:this.closed
  }
}
export function strikeRsiLabel(value: StrikeRsiValue | undefined): string {
  return value?.value != null && Number.isFinite(value.value)
    ? `RSI ${value.value.toFixed(1)} ${value.source === 'live' ? 'Live' : 'Closed'}` : 'RSI —'
}
