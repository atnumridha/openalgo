import {expect,it,vi} from 'vitest'
import type {ISeriesApi, SeriesAttachedParameter, Time, IPrimitivePaneRenderer} from 'lightweight-charts'
import {EmaCrossMarks} from './EmaCrossMarks'
it('draws fixed-size outlined crosses above the EMA lines and clears when disabled',()=>{
 const series={attachPrimitive:vi.fn(),detachPrimitive:vi.fn()} as unknown as ISeriesApi<'Line'>
 const layer=new EmaCrossMarks(series,true)
 const update=vi.fn()
 layer.attached({chart:{timeScale:()=>({timeToCoordinate:()=>100})},series:{priceToCoordinate:()=>80},requestUpdate:update} as unknown as SeriesAttachedParameter<Time>)
 layer.setMarkers([{time:60 as never,position:'atPriceMiddle',price:100,shape:'circle',size:0,text:'×',color:'#22c55e'}])
 const widths:number[]=[],colors:string[]=[]
 const ctx={save:vi.fn(),restore:vi.fn(),beginPath:vi.fn(),moveTo:vi.fn(),lineTo:vi.fn(),stroke:vi.fn(),setLineDash:vi.fn(),
   set lineWidth(n:number){widths.push(n)},set strokeStyle(c:string){colors.push(c)},lineCap:''}
 const target={useMediaCoordinateSpace:(fn:(scope:unknown)=>void)=>fn({context:ctx,mediaSize:{width:500,height:300}})} as unknown as Parameters<IPrimitivePaneRenderer['draw']>[0]
 layer.paneViews()[0].renderer().draw(target)
 expect(layer.paneViews()[0].zOrder()).toBe('top')
 expect(ctx.moveTo).toHaveBeenCalledWith(92,72)
 expect(ctx.lineTo).toHaveBeenCalledWith(108,88)
 expect(widths).toEqual([8,4])
 expect(colors).toEqual(['#11151e','#22c55e'])
 expect(ctx.stroke).toHaveBeenCalledTimes(2)
 layer.setMarkers([]);ctx.stroke.mockClear();layer.paneViews()[0].renderer().draw(target)
 expect(ctx.stroke).not.toHaveBeenCalled()
})
