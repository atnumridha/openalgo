import { expect, it, vi } from 'vitest'
import { ResearchTradeLevels } from './ResearchTradeLevels'
it('draws separate horizontal trade levels without connecting different trades or changing autoscale',()=>{
 const p=new ResearchTradeLevels()
 const context={save:vi.fn(),restore:vi.fn(),beginPath:vi.fn(),rect:vi.fn(),clip:vi.fn(),moveTo:vi.fn(),lineTo:vi.fn(),stroke:vi.fn(),setLineDash:vi.fn(),fillText:vi.fn()}
 p.attached({chart:{timeScale:()=>({timeToCoordinate:(n:number)=>n})},series:{priceToCoordinate:(n:number)=>n},requestUpdate:vi.fn()} as never)
 p.set([{entry_time:10,exit_time:30,entry:100,stop:90,target:120,side:1},{entry_time:60,exit_time:90,entry:150,stop:160,target:130,side:-1}],0,100)
 p.paneViews()[0].renderer()!.draw({useMediaCoordinateSpace:(f:(x:unknown)=>void)=>f({context,mediaSize:{width:200,height:200}})} as never)
 expect(context.moveTo.mock.calls.map(c=>c.slice(0,2))).toEqual([[10,100],[10,90],[10,120],[60,150],[60,160],[60,130]])
 expect(context.lineTo.mock.calls.map(c=>c.slice(0,2))).toEqual([[30,100],[30,90],[30,120],[90,150],[90,160],[90,130]])
 expect('autoscaleInfo' in p).toBe(false)
 p.set([],0,100);context.moveTo.mockClear()
 p.paneViews()[0].renderer()!.draw({useMediaCoordinateSpace:(f:(x:unknown)=>void)=>f({context,mediaSize:{width:200,height:200}})} as never)
 expect(context.moveTo).not.toHaveBeenCalled()
})
