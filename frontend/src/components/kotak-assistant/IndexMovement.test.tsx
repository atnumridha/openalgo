import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { IndexMovement } from './IndexMovement'

const now = 1792036200

it.each([
  undefined,
  0,
  -1,
  NaN,
  Infinity,
])('keeps a missing or invalid previous close (%s) unavailable', (previous) => {
  render(
    <IndexMovement
      index="NIFTY"
      quote={{ ltp: 23000, prev_close: previous, time: now }}
      now={now}
    />
  )
  const movement = screen.getByLabelText('NIFTY day movement')
  expect(movement).toHaveTextContent('Change unavailable')
  expect(movement).toHaveTextContent('Waiting for previous close')
  expect(movement).not.toHaveTextContent('FLAT')
  expect(movement).not.toHaveTextContent('pts')
})

it('accepts the normalized Quote close alias while ignoring an invalid REST previous close', () => {
  render(
    <IndexMovement
      index="NIFTY"
      quote={{ ltp: 23000, prev_close: 0, close: 22800, time: now }}
      now={now}
    />
  )
  expect(screen.getByLabelText('NIFTY day movement')).toHaveTextContent(
    'NIFTY UP+200.00 pts (+0.88%)'
  )
})

it.each([
  undefined,
  0,
  NaN,
])('does not calculate movement from an invalid index price (%s)', (ltp) => {
  render(<IndexMovement index="NIFTY" quote={{ ltp, prev_close: 22800, time: now }} now={now} />)
  expect(screen.getByLabelText('NIFTY day movement')).toHaveTextContent('Change unavailable')
  expect(screen.getByLabelText('NIFTY day movement')).not.toHaveTextContent('pts')
})

it('expires a previously fresh direction at the quote-age boundary and rejects future timestamps', () => {
  const quote = { ltp: 22600, prev_close: 22800, time: now - 5 }
  const view = render(<IndexMovement index="NIFTY" quote={quote} now={now} />)
  expect(screen.getByLabelText('NIFTY day movement')).toHaveTextContent('NIFTY DOWN')
  view.rerender(<IndexMovement index="NIFTY" quote={quote} now={now + 0.01} />)
  expect(screen.getByLabelText('NIFTY day movement')).toHaveTextContent('NIFTY Last DOWN')
  expect(screen.getByLabelText('NIFTY day movement')).toHaveTextContent('Last quote · stale')
  view.rerender(<IndexMovement index="NIFTY" quote={{ ...quote, time: now + 1 }} now={now} />)
  expect(screen.getByLabelText('NIFTY day movement')).toHaveTextContent('NIFTY Last DOWN')
})
