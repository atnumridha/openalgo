import { expect, it } from 'vitest'
import { emaAlignmentEvents, emaCrossEvents, readEmaCrossTrend } from './emaCross'
const data = {
  algorithm:'sma-seeded-ema-9-15-v1', direction:'down' as const, crosses:[{time:120,value:100.5,side:'up' as const},{time:240,value:99.5,side:'down' as const}],
  '9': { points:[{time:60,value:99},{time:120,value:101},{time:180,value:103},{time:240,value:99}],count:18,sum:900,value:99 },
  '15': { points:[{time:60,value:100},{time:120,value:100},{time:180,value:100},{time:240,value:100}],count:18,sum:1500,value:100 },
}
it('marks only changes of direction, green up and red down, not every candle', () => {
  expect(emaCrossEvents(data, 240)).toEqual([{time:120,value:100.5,side:'up'},{time:240,value:99.5,side:'down'}])
  expect(emaCrossEvents(data, 180)).toHaveLength(1)
})
it('keeps the latest EMA direction until the opposite crossover, without EMA20/50 swing vetoes', () => {
  expect(readEmaCrossTrend(data,240,18)).toMatchObject({direction:'down',label:'Downtrend',emaFast:99,emaSlow:100})
  expect(readEmaCrossTrend(null,240,18).direction).toBe('unavailable')
  expect(readEmaCrossTrend(data,180,18).direction).toBe('unavailable')
})
it('does not invent a crossover on initial warmup or equal averages', () => {
  const flat={...data,direction:'sideways' as const,crosses:[],'9':{...data['9'],points:data['15'].points,value:100}}
  expect(emaCrossEvents(flat,240)).toEqual([])
  expect(readEmaCrossTrend(flat,240,18).direction).toBe('sideways')
})

it('drops old EMA evidence after a missing candle and recovers from a contiguous prefix', async () => {
  const {contiguousEmaBars}=await import('./emaCross')
  const rows=Array.from({length:60},(_,i)=>({time:i*60,close:100+i}))
  expect(contiguousEmaBars(rows.filter((_,i)=>i!==55),60)).toHaveLength(4)
  expect(contiguousEmaBars(rows.filter((_,i)=>i!==10),60)).toHaveLength(49)
})

it('requires backend triple alignment proof and rejects forming bars and malformed points', () => {
 expect(emaAlignmentEvents(data,240)).toEqual([])
 const triple={...data,alignment_algorithm:'ema-9-15-21-alignment-v1',alignment_crosses:[{time:120,value:100,side:'up' as const},{time:240,value:99,side:'down' as const},{time:300,value:101,side:'up' as const},{time:60,value:NaN,side:'up' as const}]}
 expect(emaAlignmentEvents(triple,240)).toEqual([{time:120,value:100,side:'up'},{time:240,value:99,side:'down'}])
 expect(emaAlignmentEvents({...triple,alignment_algorithm:'unknown'},240)).toEqual([])
})
