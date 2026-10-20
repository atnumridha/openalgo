export function candleAnalysisFresh(view: {market_fresh?: boolean; market?: {asof:number;analysis:{fresh?:boolean}} | null} | undefined, failed: boolean, now=Date.now()/1000) {
  return !!(view?.market_fresh && !failed && view.market?.analysis.fresh && now-view.market.asof>=0 && now-view.market.asof<=45)
}
export function paperDayStart(day?: string, now=Date.now()/1000) {
  const indiaDay=day || new Date((now+19800)*1000).toISOString().slice(0,10)
  return Date.parse(`${indiaDay}T00:00:00+05:30`)/1000
}
