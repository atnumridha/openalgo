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

it('opens on a new selection token without remounting the editor draft', () => {
  const view = (token: string) => (
    <ChartToolDock floating>
      <ChartToolPanel floating label="Setup" title="Setup" openToken={token}>
        <input aria-label="Entry draft" defaultValue="" />
      </ChartToolPanel>
    </ChartToolDock>
  )
  const result = render(view('A-01:1'))
  expect(screen.getByRole('dialog', { name: 'Setup' })).toBeVisible()
  fireEvent.change(screen.getByLabelText('Entry draft'), { target: { value: '24000' } })
  fireEvent.click(screen.getByRole('button', { name: 'Close Setup' }))
  expect(screen.queryByRole('dialog', { name: 'Setup' })).not.toBeInTheDocument()
  result.rerender(view('A-01:2'))
  expect(screen.getByRole('dialog', { name: 'Setup' })).toBeVisible()
  expect(screen.getByLabelText('Entry draft')).toHaveValue('24000')
})
it('anchors an automatic setup overlay without adding the editor to a non-fitted chart layout', () => {
  render(
    <ChartToolDock floating={false}>
      <ChartToolPanel floating label="Setup preview" title="Setup preview" openToken="A-01">
        <p>Editable legs</p>
      </ChartToolPanel>
    </ChartToolDock>
  )
  expect(screen.getByLabelText('Chart tools')).toHaveClass('relative')
  expect(screen.getByRole('dialog', { name: 'Setup preview' })).toHaveClass(
    'absolute',
    'bottom-full'
  )
})
