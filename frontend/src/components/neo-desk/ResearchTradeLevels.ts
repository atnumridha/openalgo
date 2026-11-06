import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time, UTCTimestamp } from 'lightweight-charts'
import type { ResearchTrade } from './piyushResearchEngine.js'

/** Trade levels are independent segments, excluded from the candle autoscale. */
export class ResearchTradeLevels implements ISeriesPrimitive<Time> {
 private attachment:SeriesAttachedParameter<Time>|null=null
 private trades:ResearchTrade[]=[]
 private first=0
 private last=0
 attached(a:SeriesAttachedParameter<Time>){this.attachment=a}
 detached(){this.attachment=null}
 set(trades:ResearchTrade[],first:number,last:number){
  this.trades=trades.filter(t=>t.entry_time<=last && (t.exit_time??last)>=first).slice(-12)
  this.first=first;this.last=last;this.attachment?.requestUpdate()
 }
 private renderer:IPrimitivePaneRenderer={draw:target=>{
  const a=this.attachment;if(!a)return
  target.useMediaCoordinateSpace(({context:c,mediaSize:size})=>{
   c.save();c.beginPath();c.rect(0,0,size.width,size.height);c.clip();c.lineWidth=1;c.setLineDash([5,4])
   for(const trade of this.trades){
    const start=a.chart.timeScale().timeToCoordinate(Math.max(trade.entry_time,this.first) as UTCTimestamp)
    const end=a.chart.timeScale().timeToCoordinate(Math.min(trade.exit_time??this.last,this.last) as UTCTimestamp)
    if(start==null||end==null)continue
    for(const [label,price,color] of [['Entry',trade.entry,'#94a3b8'],['SL',trade.stop,'#ef5350'],['Target',trade.target,'#26a69a']] as const){
     const y=a.series.priceToCoordinate(price);if(y==null||y<0||y>size.height)continue
     const left=Math.max(0,start),right=Math.min(size.width,end)
     if(right<left)continue
     c.strokeStyle=color;c.beginPath();c.moveTo(left,y);c.lineTo(Math.max(left+1,right),y);c.stroke()
     if(trade===this.trades.at(-1)&&right-left>55){c.fillStyle=color;c.font='600 11px system-ui';c.fillText(`${label} ${price.toFixed(2)}`,left+4,y-5)}
    }
   }
   c.restore()
  })
 }}
 private view:IPrimitivePaneView={zOrder:()=> 'top',renderer:()=>this.renderer}
 paneViews(){return [this.view]}
}
