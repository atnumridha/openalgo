import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import type {PropsWithChildren} from 'react'
import {expect,it,vi,beforeEach} from 'vitest'
import {serverEmaFixture} from '../../test/fixtures/serverEma'
import {loadEmaBackfill} from './emaBackfill'
import {useServerEmaTrend} from './useServerEmaTrend'
vi.mock('./emaBackfill',()=>({loadEmaBackfill:vi.fn()}))
beforeEach(()=>{vi.mocked(loadEmaBackfill).mockReset().mockImplementation(async input=>serverEmaFixture(input))})
const rows=Array.from({length:60},(_,i)=>({time:i*60,open:100+i,high:101+i,low:99+i,close:100+i,volume:1}))
function wrapper({children}:PropsWithChildren){const client=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}});return <QueryClientProvider client={client}>{children}</QueryClientProvider>}
it('never asks the backend to bridge a missing recent candle, then recovers on a fresh contiguous prefix',async()=>{
 const {result,rerender}=renderHook(({bars})=>useServerEmaTrend(bars,true,60),{wrapper,initialProps:{bars:rows.filter((_,i)=>i!==55)}})
 expect(result.current.direction).toBe('unavailable');expect(loadEmaBackfill).not.toHaveBeenCalled()
 rerender({bars:rows})
 await waitFor(()=>expect(result.current.direction).toBe('up'))
 expect(vi.mocked(loadEmaBackfill).mock.calls[0][0]).toEqual(rows.map(({time,close})=>({time,close})))
})
it('does not use an old EMA snapshot after source corrections or backend failure',async()=>{
 const {result,rerender}=renderHook(({bars})=>useServerEmaTrend(bars,true,60),{wrapper,initialProps:{bars:rows}})
 await waitFor(()=>expect(result.current.direction).toBe('up'))
 vi.mocked(loadEmaBackfill).mockRejectedValueOnce(new Error('backend unavailable'))
 rerender({bars:rows.map((b,i)=>i===59?{...b,close:90}:b)})
 await waitFor(()=>expect(loadEmaBackfill).toHaveBeenCalledTimes(2))
 expect(result.current.direction).toBe('unavailable')
})
