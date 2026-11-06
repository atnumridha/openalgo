import { expect, it, vi } from 'vitest'
import type { ISeriesApi } from 'lightweight-charts'
import { EmaLiveLayer } from './EmaLiveLayer'
import { loadEmaBackfill, type EmaBackfill } from './emaBackfill'
vi.mock('./emaBackfill', () => ({ loadEmaBackfill: vi.fn() }))
const series = () => ({ setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() })
const bar = (time: number, close: number) => ({
  time,
  open: close,
  high: close,
  low: close,
  close,
  volume: 1,
})
const result = (): EmaBackfill => ({
  '9': { points: [{ time: 60, value: 100 }], count: 20, sum: 900, value: 100 },
  '15': { points: [{ time: 60, value: 100 }], count: 20, sum: 1500, value: 100 },
})
it('backfills on the server once and revises the live candle from a fixed seed without a redraw timer', async () => {
  vi.mocked(loadEmaBackfill).mockReset().mockResolvedValue(result())
  const a = series(),
    b = series(),
    layer = new EmaLiveLayer(a as unknown as ISeriesApi<'Line'>, b as unknown as ISeriesApi<'Line'>)
  layer.update([bar(60, 100), bar(120, 110)], true, 60, 120)
  await Promise.resolve()
  await Promise.resolve()
  expect(a.setData.mock.calls.at(-1)?.[0].at(-1)?.value).toBe(102)
  layer.update([bar(60, 100), bar(120, 120)], true, 60, 120)
  expect(a.update).toHaveBeenLastCalledWith({ time: 120, value: 104 })
  expect(b.update).toHaveBeenLastCalledWith({ time: 120, value: 102.5 })
  expect(loadEmaBackfill).toHaveBeenCalledTimes(1)
  layer.update([], false, 0, 0)
  expect(a.setData).toHaveBeenLastCalledWith([])
})
it('ignores an old server calculation after source history changes', async () => {
  let old!: (r: EmaBackfill) => void
  vi.mocked(loadEmaBackfill)
    .mockReset()
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          old = resolve
        })
    )
    .mockResolvedValue(result())
  const a = series(),
    b = series(),
    layer = new EmaLiveLayer(a as unknown as ISeriesApi<'Line'>, b as unknown as ISeriesApi<'Line'>)
  layer.update([bar(60, 100), bar(120, 110)], true, 60, 120)
  layer.update([bar(180, 100), bar(240, 120)], true, 180, 240)
  await Promise.resolve()
  await Promise.resolve()
  old(result())
  await Promise.resolve()
  expect(a.setData.mock.calls.at(-1)?.[0].at(-1)?.time).toBe(240)
  layer.destroy()
})

it('draws green and red crosses only after the exact observed candle closes and clears on disable', async () => {
  const data = { algorithm:'sma-seeded-ema-9-15-v1',alignment_algorithm:'ema-9-15-21-alignment-v1',direction:'down' as const,alignment_crosses:[{time:120,value:100.5,side:'up' as const},{time:180,value:99.5,side:'down' as const},{time:240,value:105,side:'up' as const}], '9':{points:[{time:60,value:99},{time:120,value:101},{time:180,value:99}],count:18,sum:900,value:99},
    '15':{points:[{time:60,value:100},{time:120,value:100},{time:180,value:100}],count:18,sum:1500,value:100} }
  vi.mocked(loadEmaBackfill).mockReset().mockResolvedValue(data)
  const a=series(),b=series(),markers=vi.fn()
  const layer=new EmaLiveLayer(a as unknown as ISeriesApi<'Line'>,b as unknown as ISeriesApi<'Line'>,markers)
  layer.update([bar(60,100),bar(120,100),bar(180,100),bar(240,140)],true,60,240,180)
  await Promise.resolve();await Promise.resolve()
  expect(markers).toHaveBeenLastCalledWith([
    expect.objectContaining({time:120,text:'×',color:'#22c55e',size:0}),
    expect.objectContaining({time:180,text:'×',color:'#ef4444',size:0}),
  ])
  layer.update([bar(60,100),bar(120,100),bar(180,100),bar(240,140)],true,60,240,180)
  expect(markers.mock.calls.at(-1)![0]).toHaveLength(2)
  layer.update([],false,0,0,0)
  expect(markers).toHaveBeenLastCalledWith([])
})

it('uses an O(1) live revision path but refreshes after an earlier history correction', async()=>{
 vi.mocked(loadEmaBackfill).mockReset().mockResolvedValue(result())
 const a=series(),b=series(),layer=new EmaLiveLayer(a as unknown as ISeriesApi<'Line'>,b as unknown as ISeriesApi<'Line'>)
 layer.update([bar(60,100),bar(120,110)],true,60,120,60,60,1)
 await Promise.resolve();await Promise.resolve()
 layer.update([bar(60,100),bar(120,120)],true,60,120,60,60,1)
 expect(loadEmaBackfill).toHaveBeenCalledTimes(1)
 expect(a.update).toHaveBeenLastCalledWith({time:120,value:104})
 layer.update([bar(60,101),bar(120,120)],true,60,120,60,60,2)
 expect(loadEmaBackfill).toHaveBeenCalledTimes(2)
})

it('paints EMA21 from its server seed, revises the live candle and clears on disable', async () => {
  const data: EmaBackfill = { ...result(), '21': { points: [{ time: 60, value: 100 }], count: 21, sum: 2100, value: 100 } }
  vi.mocked(loadEmaBackfill).mockReset().mockResolvedValue(data)
  const a = series(), b = series(), c = series()
  const layer = new EmaLiveLayer(a as unknown as ISeriesApi<'Line'>, b as unknown as ISeriesApi<'Line'>, undefined, c as unknown as ISeriesApi<'Line'>)
  layer.update([bar(60, 100), bar(120, 111)], true, 60, 120, 60, 60, 1)
  await Promise.resolve(); await Promise.resolve()
  expect(c.setData).toHaveBeenLastCalledWith([{ time: 60, value: 100 }, { time: 120, value: 101 }])
  expect(c.applyOptions).toHaveBeenLastCalledWith(expect.objectContaining({ title: 'EMA 21', visible: true }))
  layer.update([bar(60, 100), bar(120, 122)], true, 60, 120, 60, 60, 1)
  expect(c.update).toHaveBeenLastCalledWith({ time: 120, value: 102 })
  layer.update([], false, 0, 0)
  expect(c.setData).toHaveBeenLastCalledWith([])
  expect(c.applyOptions).toHaveBeenLastCalledWith({ visible: false })
})

it('ignores stale EMA21 backfill and clears EMA21 when an older server omits it', async () => {
  let old!: (data: EmaBackfill) => void
  vi.mocked(loadEmaBackfill).mockReset().mockImplementationOnce(() => new Promise(resolve => { old = resolve }))
    .mockResolvedValueOnce({ ...result(), '21': { points: [], count: 21, sum: 2100, value: 100 } })
    .mockResolvedValue(result())
  const a = series(), b = series(), c = series()
  const layer = new EmaLiveLayer(a as unknown as ISeriesApi<'Line'>, b as unknown as ISeriesApi<'Line'>, undefined, c as unknown as ISeriesApi<'Line'>)
  layer.update([bar(60, 100), bar(120, 111)], true, 60, 120)
  layer.update([bar(180, 100), bar(240, 122)], true, 180, 240)
  await Promise.resolve(); await Promise.resolve()
  old({ ...result(), '21': { points: [], count: 21, sum: 2100, value: 900 } })
  await Promise.resolve()
  expect(c.setData).toHaveBeenLastCalledWith([{ time: 240, value: 102 }])
  layer.update([bar(300, 100), bar(360, 122)], true, 300, 360)
  await Promise.resolve(); await Promise.resolve()
  expect(c.setData).toHaveBeenLastCalledWith([])
  expect(c.applyOptions).toHaveBeenLastCalledWith({ visible: false })
  expect(a.setData.mock.calls.at(-1)?.[0].at(-1)?.time).toBe(360)
})

it('rejects legacy two EMA crosses when the closing bar is confirmed', async () => {
 vi.mocked(loadEmaBackfill).mockReset().mockResolvedValue({...result(),algorithm:'sma-seeded-ema-9-15-v1',direction:'down',crosses:[{time:60,value:100,side:'up'}]})
 const markers=vi.fn(),layer=new EmaLiveLayer(series() as unknown as ISeriesApi<'Line'>,series() as unknown as ISeriesApi<'Line'>,markers)
 layer.update([bar(60,100),bar(120,140)],true,60,120,120,60,1)
 await Promise.resolve();await Promise.resolve()
 expect(markers).toHaveBeenLastCalledWith([])
})
it('requests OHLC at final candle close and never advances a confirmed average twice', async () => {
 const closed={...result(),alignment_algorithm:'ema-9-15-21-alignment-v1',alignment_crosses:[{time:120,value:104,side:'up' as const}],'9':{points:[{time:60,value:100},{time:120,value:104}],count:21,sum:900,value:104}}
 vi.mocked(loadEmaBackfill).mockReset().mockResolvedValueOnce(result()).mockResolvedValueOnce(closed)
 const a=series(),markers=vi.fn(),layer=new EmaLiveLayer(a as unknown as ISeriesApi<'Line'>,series() as unknown as ISeriesApi<'Line'>,markers)
 const bars=[bar(60,100),bar(120,120)]
 layer.update(bars,true,60,120,60,60,1)
 await Promise.resolve();await Promise.resolve()
 layer.update(bars,true,60,120,120,60,1)
 expect(loadEmaBackfill).toHaveBeenLastCalledWith(bars.map(({volume,...b})=>b),expect.any(AbortSignal),{intervalSeconds:60})
 await Promise.resolve();await Promise.resolve()
 expect(a.setData).toHaveBeenLastCalledWith(closed['9'].points)
 expect(markers).toHaveBeenLastCalledWith([expect.objectContaining({time:120,id:'ema-alignment-120',color:'#22c55e'})])
})
it('refreshes earlier OHLC corrections even if every close stays unchanged', async () => {
 vi.mocked(loadEmaBackfill).mockReset().mockResolvedValue(result())
 const layer=new EmaLiveLayer(series() as unknown as ISeriesApi<'Line'>,series() as unknown as ISeriesApi<'Line'>)
 layer.update([bar(60,100),bar(120,110)],true,60,120,60,60,1)
 await Promise.resolve();await Promise.resolve()
 layer.update([{...bar(60,100),high:105},bar(120,110)],true,60,120,60,60,2)
 expect(loadEmaBackfill).toHaveBeenCalledTimes(2)
 expect(vi.mocked(loadEmaBackfill).mock.calls[1][0][0]).toMatchObject({high:105})
})

it('discards stale alignment responses across history generations and disable', async () => {
 let old!: (data:EmaBackfill)=>void, disabled!: (data:EmaBackfill)=>void
 const triple:EmaBackfill={...result(),alignment_algorithm:'ema-9-15-21-alignment-v1',alignment_crosses:[{time:60,value:100,side:'up'}]}
 vi.mocked(loadEmaBackfill).mockReset().mockImplementationOnce(()=>new Promise(resolve=>{old=resolve})).mockResolvedValueOnce({...triple,alignment_crosses:[]}).mockImplementationOnce(()=>new Promise(resolve=>{disabled=resolve}))
 const markers=vi.fn(),layer=new EmaLiveLayer(series() as unknown as ISeriesApi<'Line'>,series() as unknown as ISeriesApi<'Line'>,markers)
 layer.update([bar(60,100),bar(120,110)],true,60,120,60,60,1)
 const oldSignal=vi.mocked(loadEmaBackfill).mock.calls[0][1]
 layer.update([bar(60,101),bar(120,110)],true,60,120,60,60,2)
 await Promise.resolve();await Promise.resolve()
 old(triple)
 await Promise.resolve();await Promise.resolve()
 expect(oldSignal.aborted).toBe(true)
 expect(markers).toHaveBeenLastCalledWith([])
 layer.update([bar(60,102),bar(120,110)],true,60,120,60,60,3)
 layer.update([],false,0,0)
 disabled(triple)
 await Promise.resolve();await Promise.resolve()
 expect(markers).toHaveBeenLastCalledWith([])
 expect(markers.mock.calls.every(([points])=>points.length===0)).toBe(true)
})

it('passes the display interval separately from session continuity for index markers', async () => {
 vi.mocked(loadEmaBackfill).mockReset().mockResolvedValue(result())
 const layer=new EmaLiveLayer(series() as unknown as ISeriesApi<'Line'>,series() as unknown as ISeriesApi<'Line'>)
 layer.update([bar(60,100),bar(86460,110),bar(87360,120)],true,60,87360,86460,0,1,900)
 await Promise.resolve();await Promise.resolve()
 expect(loadEmaBackfill).toHaveBeenLastCalledWith([expect.objectContaining({time:60}),expect.objectContaining({time:86460})],expect.any(AbortSignal),{intervalSeconds:900,allowSessionGaps:true})
})
