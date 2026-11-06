import { useEffect, useRef, useState } from 'react'
import { useMarketDataContextOptional } from '@/contexts/MarketDataContext'
import { MarketDataManager, type SymbolData } from '@/lib/MarketDataManager'
import type { OptionChainResponse, OptionData } from '@/types/option-chain'
import { optionQuality } from './optionQuality'
import { strikeActivity, strikePremium } from './strikeRanking'
import { PremiumQuote } from './PremiumQuote'
const num=(n:number|undefined|null,d=2)=>n!=null && Number.isFinite(n)?n.toFixed(d):'—'

/** Reuse the two selected Quote streams; book metrics stay labelled chain snapshots. */
export function SelectedOptionQuality({data,ce,pe,exchange,receivedAt}: {
 data?:OptionChainResponse;ce?:OptionData;pe?:OptionData;exchange:string;receivedAt:number
}) {
 const [open,setOpen]=useState(false)
 const context=useMarketDataContextOptional()
 const manager=useRef(context?.manager??MarketDataManager.getInstance()).current
 const [snapshot,setSnapshot]=useState(()=>({now:Date.now(),quotes:new Map<string,SymbolData>(),connected:false,epoch:0}))
 useEffect(()=>{
  if(!open)return
  const quotes=new Map<string,SymbolData>()
  const symbols=[...new Set([ce?.symbol,pe?.symbol].filter((s):s is string=>!!s))]
  const cleanup=symbols.map(symbol=>{
    const cached=manager.getCachedData(symbol,exchange);if(cached)quotes.set(symbol,cached)
    return manager.subscribe(symbol,exchange,'Quote',quote=>quotes.set(symbol,quote))
  })
  const publish=()=>{
    const feed=manager.getState()
    setSnapshot({now:Date.now(),quotes:new Map(quotes),connected:!!feed.isConnected && !!feed.isAuthenticated && !feed.isPaused,epoch:feed.connectionEpoch})
  }
  publish();const timer=setInterval(publish,1000)
  return ()=>{clearInterval(timer);cleanup.forEach(stop=>stop())}
 },[open,manager,ce?.symbol,pe?.symbol,exchange])
 const now=(data?.server_ts??receivedAt/1000)+Math.max(0,snapshot.now-receivedAt)/1000
 const expirySeconds=data?.expiry_ts?data.expiry_ts-now:null
 const expiry=expirySeconds==null?'—':expirySeconds<=0?'Expired':`${Math.floor(expirySeconds/86400)}d ${Math.floor(expirySeconds%86400/3600)}h`
 return <details className="mt-2 border-t pt-2 text-xs" open={open}
   onToggle={e=>{if(e.currentTarget.open!==open)setOpen(e.currentTarget.open)}}>
  <summary className="cursor-pointer font-medium focus-visible:outline focus-visible:outline-ring">Spread, depth &amp; Greeks</summary>
  {open?<div className="mt-2 space-y-2">
   <p className="text-muted-foreground">Expiry {data?.expiry_date??'—'} · Time left {expiry}. Compare each leg's own liquidity; ranking remains combined CE + PE activity.</p>
   <div className="grid gap-2 sm:grid-cols-2">
    {([['CE',ce],['PE',pe]] as const).map(([side,leg])=>{
     if(!leg)return <p key={side}>{side} quote unavailable.</p>
     const q=optionQuality(leg,exchange,snapshot.quotes.get(leg.symbol),snapshot.now,snapshot)
     const greek=(value:number|undefined)=>expirySeconds!=null && expirySeconds>0?num(value):'—'
     return <section key={side} aria-label={`${side} contract quality`} className="min-w-0 space-y-2 rounded-md border p-3">
      <p className="break-all font-medium">{leg.symbol}</p>
      <p className="text-muted-foreground">Chain snapshot · quote age unavailable</p>
      {q.streamAgeSeconds!=null?<p className="text-muted-foreground">Stream update {num(q.streamAgeSeconds,0)}s ago · book freshness unverified</p>:null}
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 tabular-nums">
       <div className="col-span-2"><dt className="text-muted-foreground">Premium · day change</dt><dd><PremiumQuote price={q.premium} previousClose={leg.prev_close}/></dd></div>
       {[
        ['Bid / ask',`${strikePremium(q.bid)} / ${strikePremium(q.ask)}`],
        ['Spread %',q.spreadPercent==null?'—':`${num(q.spreadPercent)}%`],['Spread ₹',q.spread==null?'—':`₹${num(q.spread)}`],
        ['Bid / ask depth',`${num(q.bidLots)} / ${num(q.askLots)} lots`],['Own volume / OI',`${strikeActivity(leg.volume)} / ${strikeActivity(leg.oi)}`],
        ['IV',greek(leg.implied_volatility)==='—'?'—':`${greek(leg.implied_volatility)}%`],['Delta',greek(leg.delta)],
        ['Theta / day / unit',greek(leg.theta)],['Vega / IV point / unit',greek(leg.vega)],
       ].map(([label,value])=><div key={label} className="min-w-0"><dt className="text-muted-foreground">{label}</dt><dd className="break-words">{value}</dd></div>)}
      </dl>
     </section>
    })}
   </div>
   <p className="text-muted-foreground">Spread, depth and Greeks use the chain snapshot, refreshed each minute. Depth is the best bid / ask quantity divided by this contract's lot size. Broker quote observation time is unavailable; stream update age measures publication time. Missing values show —. Delta, IV and time decay describe exposure.</p>
  </div>:null}
 </details>
}
