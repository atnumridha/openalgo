import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { ResearchSetupPicker } from './ResearchSetupPicker'
it('opens all research choices and selects a setup without a native select popup',async()=>{
 const change=vi.fn()
 render(<ResearchSetupPicker value="off" onChange={change}/> )
 fireEvent.click(screen.getByRole('combobox',{name:'Setup'}))
 const list=await screen.findByRole('listbox',{name:'Research setup choices'})
 expect(within(list).getAllByRole('option')).toHaveLength(6)
 fireEvent.click(within(list).getByRole('option',{name:'EMA 8/33 cross · 5m'}))
 expect(change).toHaveBeenCalledWith('ema_cross_5m')
})
