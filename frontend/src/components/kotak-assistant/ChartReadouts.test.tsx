import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { ChartReadouts } from './ChartReadouts'

const now = Date.parse('2026-10-15T09:15:37+05:30') / 1000
const barTime = Date.parse('2026-10-15T09:15:00+05:30') / 1000 + 19800

it('shows a clear RSI value and an independently updating current-bar countdown', () => {
  const view = render(
    <ChartReadouts rsi={52.28} hovered={false} barTime={barTime} interval="1m" now={now} />
  )
  expect(screen.getByLabelText('RSI 14 value')).toHaveTextContent('52.28')
  expect(screen.getByLabelText('Bar close countdown')).toHaveTextContent('00:23')
  view.rerender(<ChartReadouts rsi={43.5} hovered barTime={barTime} interval="1m" now={now + 1} />)
  expect(screen.getByLabelText('RSI 14 value')).toHaveTextContent('43.50')
  expect(screen.getByText('Hovered bar')).toBeInTheDocument()
  expect(screen.getByLabelText('Bar close countdown')).toHaveTextContent('00:22')
})

it('preserves zero RSI and distinguishes missing RSI from a closed historical bar', () => {
  const view = render(<ChartReadouts rsi={0} barTime={barTime} interval="1m" now={now + 86400} />)
  expect(screen.getByLabelText('RSI 14 value')).toHaveTextContent('0.00')
  expect(screen.getByLabelText('Bar close countdown')).toHaveTextContent('Closed')
  view.rerender(<ChartReadouts rsi={null} barTime={null} interval="1m" now={now} />)
  expect(screen.getByLabelText('RSI 14 value')).toHaveTextContent('—')
  expect(screen.getByLabelText('Bar close countdown')).toHaveTextContent('—')
})
