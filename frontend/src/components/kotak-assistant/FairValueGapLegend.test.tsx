import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { FairValueGapLegend } from './FairValueGapLegend'
it('keeps price ranges in an expandable legend and explains partial fills', () => {
  render(
    <FairValueGapLegend gaps={[{ direction: 'bullish', lower: 100, upper: 105, touched: true }]} />
  )
  const summary = screen.getByText('FVG ↑1 ↓0')
  expect(summary.parentElement).not.toHaveAttribute('open')
  fireEvent.click(summary)
  expect(summary.parentElement).toHaveAttribute('open')
  expect(screen.getByText('100.00–105.00')).toBeVisible()
  expect(screen.getByText('Partly filled')).toBeVisible()
})
