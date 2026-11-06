const currency=new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',minimumFractionDigits:2,maximumFractionDigits:2})
const positive=(n:number|null|undefined):n is number=>n!=null && Number.isFinite(n) && n>0
export function premiumMovement(price:number|null|undefined,previousClose:number|null|undefined){
 const change=positive(price) && positive(previousClose)?price-previousClose:null
 const percent=change!=null?100*change/previousClose!:null
 const sign=change!=null && change<0?'−':change!=null && change>0?'+':''
 return {change,percent,label:change==null || percent==null?'—':`${sign}${currency.format(Math.abs(change))} (${sign}${Math.abs(percent).toFixed(2)}%)`,
   percentLabel:percent==null?'':`${sign}${Math.abs(percent).toFixed(2)}%`}
}
export const premiumTone=(change:number|null,dark=false)=>change==null || change===0?'text-muted-foreground':change>0
 ?dark?'text-emerald-400':'text-emerald-700 dark:text-emerald-400'
 :dark?'text-red-400':'text-red-700 dark:text-red-400'
export function PremiumQuote({price,previousClose,dark=false,source}:{price?:number|null;previousClose?:number|null;dark?:boolean;source?:string}){
 const movement=premiumMovement(price,previousClose),tone=premiumTone(movement.change,dark)
 return <span aria-label="Option premium quote" className="inline-flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs tabular-nums">
  <strong aria-label="Premium price" className={`text-sm font-semibold ${tone}`}>{positive(price)?currency.format(price):'—'}</strong>
  <span aria-label="Premium day change" title="Premium day change versus this contract's previous close" className={`font-semibold ${tone}`}>{movement.label}</span>
  {source?<span className="text-[11px] text-muted-foreground">{source}</span>:null}
 </span>
}
