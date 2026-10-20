import { describe, expect, it } from 'vitest'
import { candleAnalysisFresh, paperDayStart } from './viewData'
describe('Delta observation timing',()=>{
 it('rejects a fresh HTTP response with stale candle analysis',()=>{
  expect(candleAnalysisFresh({market_fresh:true,market:{asof:100,analysis:{fresh:false}}},false,101)).toBe(false)
  expect(candleAnalysisFresh({market_fresh:true,market:{asof:100,analysis:{fresh:true}}},false,101)).toBe(true)
  expect(candleAnalysisFresh({market_fresh:true,market:{asof:100,analysis:{fresh:true}}},true,101)).toBe(false)
 })
 it('uses the paper India day independently of live account snapshots',()=>{
  expect(paperDayStart('2026-10-05')).toBe(Date.parse('2026-10-04T18:30:00Z')/1000)
  expect(paperDayStart(undefined,Date.parse('2026-10-04T18:31:00Z')/1000)).toBe(Date.parse('2026-10-04T18:30:00Z')/1000)
 })
})
