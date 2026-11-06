import type { EmaBackfill } from './emaBackfill'
import type { TrendReading } from './trendAnalysis'
export interface EmaCrossEvent { time: number; value: number; side: 'up' | 'down' }
/** Compare server-computed averages only; never recalculate the historical averages here. */
export function emaCrossEvents(data: EmaBackfill, closedThrough: number): EmaCrossEvent[] {
  return data.algorithm === 'sma-seeded-ema-9-15-v1'
    ? (data.crosses ?? []).filter(p=>p.time<=closedThrough && Number.isFinite(p.time) && Number.isFinite(p.value) && ['up','down'].includes(p.side)) : []
}
/** X markers require independent server confirmation involving all three averages. */
export function emaAlignmentEvents(data: EmaBackfill, closedThrough: number): EmaCrossEvent[] {
  if (data.alignment_algorithm !== 'ema-9-15-21-alignment-v1' || !Array.isArray(data.alignment_crosses)) return []
  return data.alignment_crosses.filter(p => p && Number.isFinite(p.time) && p.time <= closedThrough && Number.isFinite(p.value) && p.value > 0 && (p.side === 'up' || p.side === 'down'))
}
export function readEmaCrossTrend(data: EmaBackfill | null | undefined, time: number | null, count: number): TrendReading {
  const unavailable: TrendReading = {direction:'unavailable',label:'Checking EMA 9/15',reason:'Waiting for matching backend EMA 9/15 values on completed candles.',time,emaFast:null,emaSlow:null}
  if (!data || data.algorithm !== 'sma-seeded-ema-9-15-v1' || !['up','down','sideways'].includes(data.direction ?? '') || time === null || count < 16) return unavailable
  for (const period of ['9','15'] as const) {
    const d=data[period],last=d?.points.at(-1)
    if (!d || d.count!==count || last?.time!==time || d.value!==last.value || !Number.isFinite(d.value) || d.value!<=0) return unavailable
  }
  const fast=data['9'].value!,slow=data['15'].value!
  const sign = data.direction === 'up' ? 1 : data.direction === 'down' ? -1 : 0
  return {direction:sign>0?'up':sign<0?'down':'sideways',label:sign>0?'Uptrend':sign<0?'Downtrend':'Sideways',time,emaFast:fast,emaSlow:slow,
    reason:sign ? `EMA9 is ${sign>0?'above':'below'} EMA15 on completed candles. Direction stays ${sign>0?'up':'down'} until the opposite crossover.` : 'EMA9 and EMA15 are equal. No crossover direction yet.'}
}

/** A missing candle restarts crypto EMA evidence; no average bridges the gap. */
export function contiguousEmaBars<T extends {time:number;close:number}>(bars: readonly T[], seconds: number): T[] {
  const result:T[]=[]
  for(let i=bars.length-1;i>=0;i--){const b=bars[i],next=result.at(-1)
    if(!Number.isFinite(b.time)||!Number.isFinite(b.close)||b.close<=0||(next&&next.time-b.time!==seconds))break
    result.push(b)
  }
  return result.reverse()
}
