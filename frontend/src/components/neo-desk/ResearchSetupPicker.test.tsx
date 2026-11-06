import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { ResearchSetupPicker } from './ResearchSetupPicker'
it('opens all research choices and selects a setup without a native select popup', async () => {
  const change = vi.fn()
  render(<ResearchSetupPicker value="off" onChange={change} />)
  fireEvent.click(screen.getByRole('combobox', { name: 'Setup' }))
  const list = await screen.findByRole('listbox', { name: 'Research setup choices' })
  expect(within(list).getAllByRole('option')).toHaveLength(6)
  fireEvent.click(within(list).getByRole('option', { name: 'EMA 8/33 cross · 5m' }))
  expect(change).toHaveBeenCalledWith('ema_cross_5m')
})
it('includes additional configuration templates without replacing research setups', async () => {
  const change = vi.fn()
  render(
    <ResearchSetupPicker
      value="A-01"
      onChange={change}
      extraChoices={Array.from(
        { length: 7 },
        (_, i) => [`A-0${i + 1}`, `Template ${i + 1}`] as const
      )}
    />
  )
  expect(screen.getByRole('combobox', { name: 'Setup' })).toHaveTextContent('Template 1')
  fireEvent.click(screen.getByRole('combobox', { name: 'Setup' }))
  const list = await screen.findByRole('listbox', { name: 'Research setup choices' })
  expect(within(list).getAllByRole('option')).toHaveLength(13)
  fireEvent.click(within(list).getByRole('option', { name: 'Template 7' }))
  expect(change).toHaveBeenCalledWith('A-07')
})
