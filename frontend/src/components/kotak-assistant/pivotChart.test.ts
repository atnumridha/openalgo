import { expect, it } from 'vitest'
import { pivotChartLevels } from './pivotChart'
const latest=Date.UTC(2026,9,23,9,15)/1000
const overlay={underlying:'NIFTY',session_date:'2026-10-23',reference_date:'2026-10-22',previous:{high:110,low:90,close:100},levels:{P:100,R1:110,R2:120,R3:130,S1:90,S2:80,S3:70}}
it('shows three fixed labelled pivots only on their own index and session, without leaking into replay',()=>{
 expect(pivotChartLevels(overlay,'NIFTY','2026-10-23','2026-10-23',false,latest).map(x=>x.price)).toEqual([100,90,110])
 expect(pivotChartLevels(overlay,'SENSEX','2026-10-23','2026-10-23',false,latest)).toEqual([])
 expect(pivotChartLevels(overlay,'NIFTY','2026-10-22','2026-10-22',false,latest)).toEqual([])
 expect(pivotChartLevels(overlay,'NIFTY','2026-10-22','2026-10-23',false,latest)).toEqual([])
 expect(pivotChartLevels(overlay,'NIFTY','2026-10-23','2026-10-23',true,latest)).toEqual([])
})

it('does not put current pivots on yesterday candles even if Today was selected',()=>{
 expect(pivotChartLevels(overlay,'NIFTY','2026-10-23','2026-10-23',false,latest-86400)).toEqual([])
 expect(pivotChartLevels(overlay,'NIFTY','2026-10-23','2026-10-23',false,undefined)).toEqual([])
})
