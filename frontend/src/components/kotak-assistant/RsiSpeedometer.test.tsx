import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { RsiSpeedometer } from './RsiSpeedometer'

it.each([
  { value: 0, zone: 'Oversold', angle: -135 },
  { value: 50, zone: 'Mid-range', angle: 0 },
  { value: 100, zone: 'Overbought', angle: 135 },
])('shows $value with an accurate needle and text zone', ({ value, zone, angle }) => {
  render(<RsiSpeedometer value={value} live interval="5m" note="Forming candle" />)
  expect(screen.getByRole('img')).toHaveAccessibleName(
    `RSI 14 speedometer: ${value.toFixed(2)}, ${zone}`
  )
  expect(screen.getByTestId('rsi-needle')).toHaveAttribute('transform', `rotate(${angle} 120 110)`)
  expect(screen.getByText(/30 · Oversold/)).toBeInTheDocument()
})
it('shows unavailable data without a fake needle, then marks stale readings', () => {
  const view = render(
    <RsiSpeedometer value={null} live={false} interval="5m" note="Waiting for candles" />
  )
  expect(screen.queryByTestId('rsi-needle')).not.toBeInTheDocument()
  view.rerender(<RsiSpeedometer value={60} live={false} interval="5m" note="Candles delayed" />)
  expect(screen.getByRole('img')).toHaveAccessibleName(/60.00.*not live/)
  expect(screen.getByText('Candles delayed')).toBeInTheDocument()
})
