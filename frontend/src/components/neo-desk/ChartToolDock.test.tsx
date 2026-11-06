import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { ChartToolDock, ChartToolPanel } from './ChartToolDock'
it('opens one detail panel at a time, preserves entered values and closes with Escape', () => {
  render(
    <ChartToolDock floating>
      <ChartToolPanel floating label="Risk" title="Entry / SL / Target">
        <input aria-label="SL draft" defaultValue="90" />
      </ChartToolPanel>
      <ChartToolPanel floating label="History" title="History & replay">
        History content
      </ChartToolPanel>
    </ChartToolDock>
  )
  const risk = screen.getByRole('button', { name: 'Entry / SL / Target' })
  fireEvent.click(risk)
  expect(screen.getByRole('dialog', { name: 'Risk' })).toBeVisible()
  fireEvent.change(screen.getByLabelText('SL draft'), { target: { value: '85' } })
  fireEvent.click(screen.getByRole('button', { name: 'History & replay' }))
  expect(screen.queryByRole('dialog', { name: 'Risk' })).not.toBeInTheDocument()
  expect(screen.getByRole('dialog', { name: 'History' })).toBeVisible()
  fireEvent.keyDown(screen.getByRole('dialog', { name: 'History' }), { key: 'Escape' })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  fireEvent.click(risk)
  expect(screen.getByLabelText('SL draft')).toHaveValue('85')
})
