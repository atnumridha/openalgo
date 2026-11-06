export interface PremiumPriceAlert {id:string;label:string;price:number;enabled:boolean;fired:boolean}
export interface PremiumQuote {price:number;time:number}
/** Repeats on each fresh touch/crossing. Equal-price ticks and leaving a level do not retrigger. */
export class PremiumAlertMonitor {
  private previous=new Map<string,PremiumQuote & {level:number}>()
  reset(id?:string){if(id)this.previous.delete(id);else this.previous.clear()}
  update(rules:PremiumPriceAlert[],quote:PremiumQuote|null,now:number,live:boolean):string[]{
    if(!live||!quote||!Number.isFinite(quote.price)||quote.price<=0||!Number.isFinite(quote.time)||now-quote.time>15000||quote.time>now+2000){this.previous.clear();return []}
    const hits:string[]=[]
    for(const r of rules){
      if(!r.enabled||!Number.isFinite(r.price)||r.price<=0){this.previous.delete(r.id);continue}
      const p=this.previous.get(r.id)
      if(p&&quote.time<=p.time)continue
      this.previous.set(r.id,{...quote,level:r.price})
      if(!p||quote.time-p.time>15000||p.level!==r.price)continue
      if((p.price<r.price&&quote.price>=r.price)||(p.price>r.price&&quote.price<=r.price)){hits.push(r.id)}
    }
    return hits
  }
}
