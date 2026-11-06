import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { LivePatternGuide } from './LivePatternGuide'
const time = 1793844000
const bars = [{ time, open: 111, high: 114, low: 110, close: 113, volume: 1 }]
const events = [
  {
    time,
    name: 'Double Bottom',
    pattern: 'double-bottom',
    side: 'CALL' as const,
    confirmed: true,
    extreme: 100,
    entry: 113,
    target: 124,
    boundary: [
      { time: time - 120, price: 110 },
      { time, price: 110 },
    ],
    structure: [
      [
        { time: time - 120, price: 100 },
        { time, price: 110 },
      ],
    ],
  },
]
const props = {
  events,
  bars,
  seconds: 60,
  asOf: time + 60,
  live: true,
  candle: { time: time + 60, open: 113, high: 115, low: 112, close: 114, volume: 1 },
  observedAt: time + 75,
  symbol: 'BTCUSD',
  exchange: 'DELTA',
}
it('shows automatic pattern explanation and live progress without selecting a pattern', () => {
  vi.spyOn(Date, 'now').mockReturnValue((time + 75) * 1000)
  render(<LivePatternGuide {...props} />)
  const guide = screen.getByRole('group', { name: 'Live pattern guide' })
  expect(within(guide).getByText('Double Bottom')).toBeVisible()
  expect(guide).toHaveTextContent(/45s.*close/)
  expect(guide).toHaveTextContent(/upward/i)
  expect(guide).toHaveTextContent('124')
  expect(guide).toHaveTextContent(/retest/)
  vi.restoreAllMocks()
})
it('rerenders with the next candle and does not advertise a stale quote as live', () => {
  vi.spyOn(Date, 'now').mockReturnValue((time + 75) * 1000)
  const view = render(<LivePatternGuide {...props} />)
  view.rerender(<LivePatternGuide {...props} candle={{ ...props.candle, close: 112 }} />)
  expect(screen.getByLabelText('Live candle progress')).toHaveTextContent(/bearish/i)
  view.rerender(<LivePatternGuide {...props} observedAt={time} />)
  expect(screen.getByLabelText('Live candle progress')).toHaveTextContent(/fresh/i)
  expect(screen.queryByText(/45s.*close/)).not.toBeInTheDocument()
  vi.restoreAllMocks()
})
it('explains source coverage without copying a changing ideas feed into trading rules', () => {
  render(<LivePatternGuide {...props} live={false} />)
  fireEvent.click(screen.getByText('Pattern references & rules'))
  expect(screen.getByRole('link', { name: 'Fidelity' })).toHaveAttribute(
    'href',
    expect.stringContaining('fidelity.com')
  )
  expect(screen.getAllByRole('link')).toHaveLength(8)
  expect(screen.getByText(/local numerical/i)).toBeVisible()
})

it.each([
  ['CALL', 100, 110, 113, '115'],
  ['PUT', 120, 110, 107, '105'],
] as const)('projects the %s boundary to the received candle and suppresses stale/history crossings', (side, start, end, close, projected) => {
  vi.spyOn(Date, 'now').mockReturnValue((time + 75) * 1000)
  const sloped = [{ ...events[0], side, extreme: undefined, target: undefined,
    boundary: [{ time: time - 120, price: start }, { time, price: end }] }]
  const candle = { ...props.candle, open: close, low: close - 1, high: close + 1, close }
  const view = render(<LivePatternGuide {...props} events={sloped} candle={candle} />)
  expect(screen.getByLabelText('Pattern reference levels')).toHaveTextContent(projected)
  expect(screen.getByText(/back through.*intrabar/i)).toBeVisible()
  view.rerender(<LivePatternGuide {...props} events={sloped} candle={candle} observedAt={time} />)
  expect(screen.queryByText(/back through.*intrabar/i)).not.toBeInTheDocument()
  expect(screen.getByLabelText('Pattern reference levels')).toHaveTextContent('110')
  view.rerender(<LivePatternGuide {...props} events={sloped} candle={candle} live={false} />)
  expect(screen.queryByText(/back through.*intrabar/i)).not.toBeInTheDocument()
  vi.restoreAllMocks()
})
it('leaves the eleventh chart slot outside the guide when a forming candle is supplied separately', () => {
  vi.spyOn(Date, 'now').mockReturnValue((time + 615) * 1000)
  const source = Array.from({ length: 10 }, (_, i) => ({ ...bars[0], time: time + i * 60 }))
  const oldest = [{ ...events[0], extreme: undefined, target: undefined, boundary: undefined }]
  const view = render(<LivePatternGuide {...props} events={oldest} bars={source}
    asOf={time + 600} candle={{ ...props.candle, time: time + 600 }} observedAt={time + 615} />)
  expect(screen.queryByText('Double Bottom')).not.toBeInTheDocument()
  view.rerender(<LivePatternGuide {...props} events={[{ ...oldest[0], time: time + 60 }]}
    bars={source} asOf={time + 600} candle={{ ...props.candle, time: time + 600 }} observedAt={time + 615} />)
  expect(screen.getByText('Double Bottom')).toBeVisible()
  vi.restoreAllMocks()
})
it('shows at most three additional names and an honest remaining count', () => {
  render(<LivePatternGuide {...props} live={false} events={[events[0],
    ...['Hammer', 'Harami', 'Engulfing', 'Morning Star', 'Piercing'].map((name, i) => ({
      ...events[0], name, pattern: `other-${i}`, structure: undefined,
    }))]} />)
  const other = screen.getByText('Other patterns on this candle (5)')
  fireEvent.click(other)
  expect(within(other.closest('details')!).getAllByRole('listitem')).toHaveLength(3)
  expect(within(other.closest('details')!).getByText(/2 more/i)).toBeVisible()
})

it('accepts a fresh receipt between countdown ticks using the actual render clock', () => {
  const clock = vi.spyOn(Date, 'now').mockReturnValue((time + 75) * 1000)
  const view = render(<LivePatternGuide {...props} />)
  clock.mockReturnValue((time + 75.5) * 1000)
  view.rerender(<LivePatternGuide {...props} observedAt={time + 75.4} />)
  expect(screen.getByLabelText('Live candle progress')).toHaveTextContent(/Forming candle/)
  // A timestamp ahead of the actual render clock still cannot establish freshness.
  view.rerender(<LivePatternGuide {...props} observedAt={time + 75.6} />)
  expect(screen.getByLabelText('Live candle progress')).toHaveTextContent(/fresh live quote/)
  vi.restoreAllMocks()
})
