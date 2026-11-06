/** Test-only independent EMA fixture standing in for the existing Python endpoint. */
export function serverEmaFixture(candles: readonly {time:number;close:number}[]) {
  const series=(period:number)=>{
    let value:number|null=null,sum=0,count=0
    const points:{time:number;value:number}[]=[]
    for(const c of candles){count++;if(value===null){sum+=c.close;if(count===period)value=sum/period}else value+=(2/(period+1))*(c.close-value)
      if(value!==null)points.push({time:c.time,value})}
    return {value,sum,count,points}
  }
  const fast=series(9), slow=series(15), crosses:{time:number;value:number;side:'up'|'down'}[]=[]
  const slowMap=new Map(slow.points.map(p=>[p.time,p.value]));let direction=0
  for(const f of fast.points){const v=slowMap.get(f.time);if(v===undefined)continue;const sign=Math.sign(f.value-v)
    if(sign && direction && sign!==direction)crosses.push({time:f.time,value:(f.value+v)/2,side:sign>0?'up':'down'})
    if(sign)direction=sign}
  return {'9':fast,'15':slow,'21':series(21),crosses,algorithm:'sma-seeded-ema-9-15-v1',direction:direction>0?'up' as const:direction<0?'down' as const:'sideways' as const}
}
