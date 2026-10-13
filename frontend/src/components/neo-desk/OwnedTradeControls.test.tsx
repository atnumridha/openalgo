import {QueryClient,QueryClientProvider} from '@tanstack/react-query'
import {render,screen,fireEvent,waitFor} from '@testing-library/react'
import {it,expect,vi} from 'vitest'
import {OwnedTradeControls} from './OwnedTradeControls'
import {neoDeskApi} from '@/api/neoDesk'
vi.mock('@/api/neoDesk',()=>({neoDeskApi:{state:vi.fn().mockResolvedValue({run_id:5,mode:'sandbox',protection:{symbol:'PE',gross_open:'300',net_open_estimate:'270'},owned:{legs:[{qty:20,entry_avg:50}]}}),close:vi.fn().mockResolvedValue({ok:true}),protection:vi.fn().mockRejectedValue(new Error('Stop cannot loosen'))}}))
it('requires explicit owned square-off and keeps premium edits tied to exact trade',async()=>{
vi.stubEnv('VITE_NEO_DESK_ENABLED','true')
render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><OwnedTradeControls/></QueryClientProvider>)
const close=await screen.findByRole('button',{name:'Square off owned trade'})
expect(close).toBeDisabled()
fireEvent.click(screen.getByLabelText('Confirm square-off of this owned trade'))
fireEvent.click(close)
await waitFor(()=>expect(neoDeskApi.close).toHaveBeenCalledWith(5))
fireEvent.change(screen.getByLabelText('Option SL ₹'),{target:{value:'45'}})
fireEvent.click(screen.getByRole('button',{name:'Save protection'}))
expect(await screen.findByRole('alert')).toHaveTextContent('Stop cannot loosen')
expect(neoDeskApi.protection).toHaveBeenCalledWith(5,expect.objectContaining({option_stop:'45'}))
})
