import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { BookPatternGuide } from './BookPatternGuide'
import { analyzeBookGuide, DEFAULT_BOOK_SETTINGS } from './engine'
import { TEST_CONTEXT } from './fixtures'
it('shows direct expected/next/invalidation and missing-risk explanations, without making an entry', () => {
  const r = analyzeBookGuide([], TEST_CONTEXT)
  r.explanation = 'No confirmed price trigger'
  r.nextCondition = 'Wait for completed close'
  render(
    <BookPatternGuide
      result={r}
      settings={DEFAULT_BOOK_SETTINGS}
      context={TEST_CONTEXT}
      instrument={{}}
      onSettingsChange={vi.fn()}
      onInstrumentChange={vi.fn()}
    />
  )
  expect(screen.getByText('No confirmed price trigger')).toBeInTheDocument()
  expect(screen.getByText('Wait for completed close')).toBeInTheDocument()
  expect(screen.getByText(/Capital and validated instrument units/)).toBeInTheDocument()
  expect(screen.getByLabelText('Account equity')).toHaveValue(0)
  expect(screen.queryByRole('button', { name: /buy|sell|place order/i })).not.toBeInTheDocument()
})
it('shows frozen plan and one selected Entry/SL/Target with reference meaning beyond color', () => {
  const r = analyzeBookGuide([], TEST_CONTEXT)
  r.readiness = 'last-session'
  r.activePlan = {
    id: 'frozen',
    eventId: 'e',
    name: 'Hammer',
    side: 'long',
    createdAt: 1,
    createdIndex: 0,
    entry: 100,
    stop: 99,
    target: 103,
    rr: 3,
    targetMethod: 'r-fallback',
    stopMethod: 'Pattern low + buffer',
    status: 'active',
    notes: ['Local 3R fallback'],
  }
  const props = {
    result: r,
    settings: DEFAULT_BOOK_SETTINGS,
    context: TEST_CONTEXT,
    instrument: {},
    onSettingsChange: vi.fn(),
    onInstrumentChange: vi.fn(),
  }
  const { rerender } = render(<BookPatternGuide {...props} />)
  expect(screen.getByText(/Last-session references/)).toBeInTheDocument()
  expect(screen.getByText('Entry · white')).toBeInTheDocument()
  expect(screen.getByText('SL · red')).toBeInTheDocument()
  expect(screen.getByText('Target · green')).toBeInTheDocument()
  expect(screen.getByText('Price risk')).toBeInTheDocument()
  expect(screen.getByText('Price reward')).toBeInTheDocument()
  rerender(<BookPatternGuide {...props} result={{ ...r, provisional: { time: 2, price: 102 } }} />)
  expect(screen.getAllByText('100')).toHaveLength(1)
  expect(screen.getAllByText(/Pattern low \+ buffer/).length).toBeGreaterThan(0)
})
it('offers independent accessible display, filter and explicit risk-unit settings', () => {
  const change = vi.fn(),
    units = vi.fn()
  render(
    <BookPatternGuide
      result={null}
      settings={DEFAULT_BOOK_SETTINGS}
      context={TEST_CONTEXT}
      instrument={{}}
      onSettingsChange={change}
      onInstrumentChange={units}
    />
  )
  fireEvent.click(screen.getByLabelText('Show pending formations'))
  expect(change).toHaveBeenCalledWith({ showPending: true })
  fireEvent.change(screen.getByLabelText('Risk per plan (%)'), { target: { value: '0.5' } })
  expect(change).toHaveBeenCalledWith({ riskPercent: 0.5 })
  fireEvent.change(screen.getByLabelText('Product type'), { target: { value: 'linear' } })
  expect(units).toHaveBeenCalledWith({ kind: 'linear' })
  expect(screen.getByLabelText('Full retained history')).not.toBeChecked()
  expect(screen.getByLabelText('Volume filter')).not.toBeChecked()
})

it('keeps fresh confirmed notices through later forming updates and exposes context observations', () => {
  const r = analyzeBookGuide([], TEST_CONTEXT)
  r.alerts = [
    {
      id: 'close1',
      type: 'confirmed-pattern',
      time: 1,
      eventId: 'e',
      patternId: 'hammer',
      side: 'long',
      text: 'Hammer confirmed on close',
    },
  ]
  r.observations = [
    {
      id: 'cross',
      type: 'ma-cross',
      time: 1,
      side: 'long',
      text: 'Fast average crossed above slow average',
      sourcePhotos: [5],
    },
  ]
  const props = {
    settings: DEFAULT_BOOK_SETTINGS,
    context: TEST_CONTEXT,
    instrument: {},
    onSettingsChange: vi.fn(),
    onInstrumentChange: vi.fn(),
  }
  const { rerender } = render(<BookPatternGuide {...props} result={r} />)
  if (!screen.getByText('Details').closest('details')!.open)
    fireEvent.click(screen.getByText('Details'))
  expect(screen.getByRole('status')).toHaveTextContent('Hammer confirmed on close')
  expect(screen.getByText('Fast average crossed above slow average')).toBeInTheDocument()
  rerender(
    <BookPatternGuide
      {...props}
      result={{ ...r, alerts: [], provisional: { time: 2, price: 100 } }}
    />
  )
  if (!screen.getByText('Details').closest('details')!.open)
    fireEvent.click(screen.getByText('Details'))
  expect(screen.getByRole('status')).toHaveTextContent('Hammer confirmed on close')
})
