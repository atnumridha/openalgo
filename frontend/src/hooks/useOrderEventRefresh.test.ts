import {act,renderHook} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
const io=vi.hoisted(()=>({handlers:new Map<string,()=>void>(),on:vi.fn((event:string,fn:()=>void)=>io.handlers.set(event,fn)),off:vi.fn((event:string)=>io.handlers.delete(event))}))
vi.mock('@/components/socket/SocketProvider',()=>({useSocketContext:()=>({socket:io})}))
import {useOrderEventRefresh} from './useOrderEventRefresh'
beforeEach(()=>{vi.useFakeTimers();io.handlers.clear();vi.clearAllMocks()})
afterEach(()=>vi.useRealTimers())
it('refreshes immediately in zero-delay mode and coalesces an event burst',()=>{
 const refresh=vi.fn();renderHook(()=>useOrderEventRefresh(refresh,{delay:0}))
 act(()=>{for(let i=0;i<100;i++)io.handlers.get('order_event')?.()})
 expect(refresh).toHaveBeenCalledTimes(1)
})
it('cancels pending refresh on unmount',()=>{
 const refresh=vi.fn();const view=renderHook(()=>useOrderEventRefresh(refresh,{delay:500}))
 act(()=>io.handlers.get('order_event')?.());view.unmount()
 act(()=>vi.advanceTimersByTime(1000))
 expect(refresh).not.toHaveBeenCalled()
})
it('bounds burst refreshes without extending the original wait',()=>{
 const refresh=vi.fn();renderHook(()=>useOrderEventRefresh(refresh,{delay:100}))
 act(()=>{io.handlers.get('order_event')?.();vi.advanceTimersByTime(80);io.handlers.get('order_event')?.();vi.advanceTimersByTime(20)})
 expect(refresh).toHaveBeenCalledTimes(1)
})
