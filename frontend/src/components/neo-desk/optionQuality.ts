import type { OptionData } from '@/types/option-chain'
import type { SymbolData } from '@/lib/MarketDataManager'
import { feedTimeMs } from './liveBars'

const positive = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n) && n > 0
const size = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n) && n >= 0

/** Neither chain fetch time nor a gateway stream timestamp proves book observation time. */
export function optionQuality(leg: OptionData, exchange: string, quote: SymbolData | undefined,
  now: number, feed: {connected:boolean;epoch:number}) {
  const stamp = feedTimeMs(quote?.data.timestamp)
  const age = stamp == null ? null : (now - stamp)/1000
  const live = !!(feed.connected && quote?.symbol === leg.symbol && quote.exchange === exchange &&
    quote.updateSource === 'websocket' && quote.connectionEpoch === feed.epoch &&
    quote.lastUpdate && now >= quote.lastUpdate && now-quote.lastUpdate <= 15000 &&
    age != null && age >= -2 && age <= 15)
  const data = live ? quote!.data : null
  // The adapter and shared cache may republish old depth with a new LTP timestamp.
  // Use the explicitly-labelled chain snapshot book, never the merged stream book.
  const bid = leg.bid, ask = leg.ask, bidQty = leg.bid_qty, askQty = leg.ask_qty
  const book = positive(bid) && positive(ask) && ask >= bid
  return {
    premium: positive(data?.ltp) ? data.ltp : positive(leg.ltp) ? leg.ltp : null,
    bid: positive(bid) ? bid : null, ask: positive(ask) ? ask : null,
    spread: book ? ask-bid : null,
    spreadPercent: book ? 100*(ask-bid)/((bid+ask)/2) : null,
    bidLots: book && positive(leg.lotsize) && size(bidQty) ? bidQty/leg.lotsize : null,
    askLots: book && positive(leg.lotsize) && size(askQty) ? askQty/leg.lotsize : null,
    source: 'snapshot' as const,
    ageSeconds: null,
    streamAgeSeconds: live ? Math.max(0,age!) : null,
  }
}

export function previewLevels(price: number, tick: number,
  stops: Array<{price:number|null|undefined;source:string}>) {
  if (!positive(price) || !positive(tick)) return {entry:null,stop:null,target:null,source:null}
  const entry = Number((Math.ceil(price/tick-1e-8)*tick).toFixed(2))
  for (const candidate of stops) {
    if (!positive(candidate.price) || candidate.price >= entry) continue
    const stop = Number((Math.floor(candidate.price/tick+1e-8)*tick).toFixed(2))
    if (stop > 0 && stop < entry)
      return {entry,stop,target:Number((entry+2*(entry-stop)).toFixed(2)),source:candidate.source}
  }
  return {entry,stop:null,target:null,source:null}
}
