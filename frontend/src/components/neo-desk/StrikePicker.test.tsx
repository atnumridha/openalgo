import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useRef, useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { StrikePicker, type StrikePickerOption } from './StrikePicker'

const options: StrikePickerOption[] = Array.from({length:235}, (_,i) => ({
  value: String(23000 + i*50), moneyness:i === 0 ? 'ATM' : `OTM${i}`,
  premium: i === 0 ? '₹137.70' : '₹49.75', rsi:'RSI 51.7 Live', volume:'33.13L', oi:'7.55Cr',
}))

describe('readable strike picker', () => {
  it('keeps focus on Options when selection hides its strike picker drawer', async () => {
    function Drawer(){
      const [open,setOpen]=useState(true)
      const optionsButton=useRef<HTMLButtonElement>(null)
      return <><button ref={optionsButton}>Options</button><aside hidden={!open}>
        <StrikePicker id="drawer-ce" side="CE" value="23000" options={options.slice(0,2)} disabled={false}
          onValueChange={()=>{optionsButton.current?.focus();setOpen(false)}}/>
      </aside></>
    }
    render(<Drawer/> )
    fireEvent.click(screen.getByRole('combobox',{name:'CE strike'}))
    const search=await screen.findByRole('combobox',{name:'Search CE strikes'})
    await act(async()=>{
      fireEvent.keyDown(search,{key:'Enter'})
      await new Promise(resolve=>setTimeout(resolve,10))
    })
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.getByRole('button',{name:'Options'})).toHaveFocus()
  })
  it('mounts the full ranked list only while open and shows each metric separately', async () => {
    render(<StrikePicker id="ce" side="CE" value="23000" options={options} disabled={false} onValueChange={vi.fn()}/>)
    const trigger = screen.getByRole('combobox', {name:'CE strike'})
    expect(trigger).toHaveTextContent('23000 · ATM')
    expect(trigger).toHaveTextContent('₹137.70 · RSI 51.7 Live')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(document.querySelectorAll('[cmdk-item]')).toHaveLength(0)
    fireEvent.click(trigger)
    const list = await screen.findByRole('listbox', {name:'CE strike choices'})
    const rows = within(list).getAllByRole('option')
    expect(rows).toHaveLength(235)
    expect(rows.slice(0,3).map(row=>row.getAttribute('data-value'))).toEqual(['23000','23050','23100'])
    const columns = screen.getByLabelText('Strike data columns')
    for (const heading of ['Strike','Premium','RSI 14','Volume','OI']) expect(within(columns).getByText(heading)).toBeVisible()
    for (const metric of ['₹137.70','51.7','Live','33.13L','7.55Cr']) expect(within(rows[0]).getByText(metric)).toBeVisible()
    fireEvent.keyDown(screen.getByRole('combobox',{name:'Search CE strikes'}),{key:'Escape'})
    await waitFor(()=>expect(screen.queryByRole('listbox')).not.toBeInTheDocument())
    expect(document.querySelectorAll('[cmdk-item]')).toHaveLength(0)
  })

  it('keeps search intact during live RSI updates and selects the exact filtered strike', async () => {
    const selected = vi.fn()
    const content = (rows: StrikePickerOption[]) => <StrikePicker id="pe" side="PE" value="23000" options={rows} disabled={false} onValueChange={selected}/>
    const view=render(content(options))
    fireEvent.click(screen.getByRole('combobox',{name:'PE strike'}))
    const search = await screen.findByRole('combobox',{name:'Search PE strikes'})
    fireEvent.change(search,{target:{value:'23100'}})
    await waitFor(()=>expect(within(screen.getByRole('listbox')).getAllByRole('option')).toHaveLength(1))
    view.rerender(content(options.map(option=>({...option,rsi:'RSI 48.6 Closed'}))))
    expect(search).toHaveValue('23100')
    expect(within(screen.getByRole('listbox')).getByText('48.6')).toBeVisible()
    expect(within(screen.getByRole('listbox')).getByText('Closed')).toBeVisible()
    fireEvent.keyDown(search,{key:'Enter'})
    await waitFor(()=>expect(selected).toHaveBeenCalledWith('23100'))
    expect(selected).toHaveBeenCalledTimes(1)
    await waitFor(()=>expect(screen.queryByRole('listbox')).not.toBeInTheDocument())
  })

  it('does not render a menu or allow selection while the chart is busy', () => {
    render(<StrikePicker id="ce" side="CE" value="23000" options={options} disabled onValueChange={vi.fn()}/>)
    const trigger=screen.getByRole('combobox',{name:'CE strike'})
    expect(trigger).toBeDisabled()
    fireEvent.click(trigger)
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })
})
