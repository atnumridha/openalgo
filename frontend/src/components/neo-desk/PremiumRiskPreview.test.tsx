import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { PremiumRiskPreview } from './PremiumRiskPreview'
import { optionRiskApi } from './optionRiskApi'
import type { OptionData } from '@/types/option-chain'
vi.mock('./optionRiskApi',()=>({optionRiskApi:{preview:vi.fn(async b=>({...b,quantity:b.lots*65,lot_size:65,
  target:String(Number(b.entry)+2*(Number(b.entry)-Number(b.stop))),net_profit:'1250.25',net_loss:'675.50',
  net_reward_risk:'1.85',profit_fees:'49.75',loss_fees:'25.50',brokerage_per_order:'10.00',
  fee_date:'2026-10-30',fee_source:'Account estimate',profit_fee_breakdown:{brokerage:'20'},loss_fee_breakdown:{brokerage:'20'}}))}}))
const contract = {symbol:'NIFTY03NOV2623050CE',lotsize:65,tick_size:0.05,ltp:99,ask:100} as OptionData
const wrap=(child:React.ReactNode)=><QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}>{child}</QueryClientProvider>
afterEach(()=>vi.clearAllMocks())
it('shows editable long-premium levels and net rupees, using the exact lot quantity',async()=>{
 const onLevels=vi.fn()
 render(wrap(<PremiumRiskPreview symbol={contract.symbol} exchange="NFO" contract={contract} ready
    price={99} stops={[{price:90,source:'Confirmed candle low'}]} onLevels={onLevels}/>))
 await waitFor(()=>expect(optionRiskApi.preview).toHaveBeenCalledWith(expect.objectContaining({symbol:contract.symbol,entry:'100.00',stop:'90.00',lots:1,slippage:'0.05'}),expect.any(AbortSignal)))
 expect(await screen.findByLabelText('Estimated net profit')).toHaveTextContent('₹1,250.25')
 expect(screen.getByLabelText('Estimated net loss')).toHaveTextContent('₹675.50')
 expect(screen.getByLabelText('2R target')).toHaveTextContent('₹120.00')
 expect(onLevels).toHaveBeenLastCalledWith({entry:100,stop:90,target:120})
 fireEvent.change(screen.getByLabelText('Preview lots'),{target:{value:'2'}})
 await waitFor(()=>expect(optionRiskApi.preview).toHaveBeenLastCalledWith(expect.objectContaining({lots:2}),expect.any(AbortSignal)))
 fireEvent.change(screen.getByLabelText('Preview SL'),{target:{value:'105'}})
 await waitFor(()=>expect(screen.queryByLabelText('Estimated net profit')).not.toBeInTheDocument())
 expect(onLevels).toHaveBeenLastCalledWith(null)
})
it('does not fabricate a stop or cash estimate when history, contract size, or SL is missing',async()=>{
 const view=render(wrap(<PremiumRiskPreview symbol={contract.symbol} exchange="NFO" contract={contract} ready={false}
   price={99} stops={[]} onLevels={vi.fn()}/>))
 expect(optionRiskApi.preview).not.toHaveBeenCalled()
 view.rerender(wrap(<PremiumRiskPreview symbol={contract.symbol} exchange="NFO" contract={contract} ready
   price={99} stops={[]} onLevels={vi.fn()}/>))
 expect(screen.getByLabelText('Preview SL')).toHaveValue(null)
 expect(optionRiskApi.preview).not.toHaveBeenCalled()
})
it('clears the displayed plan immediately when the selected contract becomes unavailable',async()=>{
 const onLevels=vi.fn()
 const content=(ready:boolean)=><PremiumRiskPreview symbol={contract.symbol} exchange="NFO" contract={contract} ready={ready}
   price={99} stops={[{price:90,source:'Support'}]} onLevels={onLevels}/>
 const view=render(wrap(content(true)))
 await screen.findByLabelText('Estimated net profit')
 view.rerender(wrap(content(false)))
 await waitFor(()=>expect(screen.queryByLabelText('Estimated net profit')).not.toBeInTheDocument())
 expect(onLevels).toHaveBeenLastCalledWith(null)
})
