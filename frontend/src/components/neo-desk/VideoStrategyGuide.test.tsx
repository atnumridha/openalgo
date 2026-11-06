import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { VideoStrategyGuide } from './VideoStrategyGuide'
import { videoStrategyGuide } from '../chart-toolkit/videoStrategyGuide.js'
import fixtures from '/Users/nmandal/Documents/AlgoTrading/openalgo/scripts/tradingview/validation/video-strategy-fixtures.json'
const c = fixtures.cases[0]
const result = videoStrategyGuide(
  c.bars.map((b, i) => ({ ...b, time: fixtures.start + i * 60 })),
  { seconds: 60, asOf: fixtures.start + c.bars.length * 60, tickSize: 0.5 }
)
const props = {
  result,
  selectedId: 'fvg' as const,
  onSelect: vi.fn(),
  symbol: 'BTCUSD',
  exchange: 'DELTA',
  interval: '1m',
  live: true,
}
it('shows the current evidence, next action and source limitations with all fifteen names', () => {
  vi.spyOn(Date, 'now').mockReturnValue(result.closedTime! * 1000)
  render(<VideoStrategyGuide {...props} />)
  const guide = screen.getByRole('group', { name: 'Video strategy guide' })
  expect(within(guide).getByText('Review Long')).toBeVisible()
  expect(within(guide).getByLabelText('Video setup price levels')).toHaveTextContent('116')
  expect(
    within(guide).getByLabelText('Strategy from video').querySelectorAll('option')
  ).toHaveLength(16)
  expect(within(guide).getByText(/2-left\/2-right/)).toBeInTheDocument()
  fireEvent.change(within(guide).getByLabelText('Strategy from video'), {
    target: { value: 'krm' },
  })
  expect(props.onSelect).toHaveBeenCalledWith('krm')
  vi.restoreAllMocks()
})
it('explains a named-only strategy without fabricated entry levels', () => {
  vi.spyOn(Date, 'now').mockReturnValue(result.closedTime! * 1000)
  render(<VideoStrategyGuide {...props} selectedId="krm" />)
  expect(
    within(
      screen.getByRole('group', { name: 'Video strategy guide' }).querySelector('summary')!
    ).getByText('Rules incomplete')
  ).toBeVisible()
  expect(screen.getAllByText(/precise trigger/).length).toBeGreaterThan(0)
  expect(screen.queryByLabelText('Video setup price levels')).not.toBeInTheDocument()
  vi.restoreAllMocks()
})
it('never presents a historical, option-bearish or stale reference as a fresh short order', () => {
  vi.spyOn(Date, 'now').mockReturnValue((result.closedTime! + 600) * 1000)
  const view = render(
    <VideoStrategyGuide {...props} exchange="NFO" symbol="NIFTY03NOV2623300CE" live={false} />
  )
  expect(screen.queryByText('Review Long')).not.toBeInTheDocument()
  expect(screen.getByText(/History/)).toBeVisible()
  view.rerender(<VideoStrategyGuide {...props} />)
  expect(screen.getByText('Check live data')).toBeVisible()
  vi.restoreAllMocks()
})
it('translates a fresh bearish option-premium condition into avoid-new-buy guidance', () => {
  const bearish = videoStrategyGuide(
    c.bars.map((b, i) => ({
      time: fixtures.start + i * 60,
      open: 300 - b.open,
      high: 300 - b.low,
      low: 300 - b.high,
      close: 300 - b.close,
    })),
    { seconds: 60, asOf: result.asOf, tickSize: 0.5 }
  )
  vi.spyOn(Date, 'now').mockReturnValue(bearish.closedTime! * 1000)
  render(
    <VideoStrategyGuide {...props} result={bearish} symbol="NIFTY03NOV2623300CE" exchange="NFO" />
  )
  expect(screen.getByText('Premium bearish · avoid new buy')).toBeVisible()
  expect(screen.queryByText('Review Short')).not.toBeInTheDocument()
  vi.restoreAllMocks()
})

it('shows automatic scan coverage and confirmed matching methods before opening the catalogue', () => {
  vi.spyOn(Date, 'now').mockReturnValue(result.closedTime! * 1000)
  render(<VideoStrategyGuide {...props} selectedId="" />)
  expect(screen.getByText(/Automatic scan · 14 detectors/)).toBeVisible()
  const matches = screen.getByRole('list', { name: 'Detected strategy matches' })
  expect(matches).toHaveTextContent('Fair Value Gap')
  expect(matches).toHaveTextContent('Bullish')
  expect(screen.getByText('6 recipes use local rules · KRM unavailable')).toBeVisible()
  vi.restoreAllMocks()
})
it('shows an available local recipe rather than a missing-rule placeholder', () => {
  vi.spyOn(Date, 'now').mockReturnValue(result.closedTime! * 1000)
  render(<VideoStrategyGuide {...props} selectedId="supply-demand" />)
  const summary = screen
    .getByRole('group', { name: 'Video strategy guide' })
    .querySelector('summary')!
  expect(summary).toHaveTextContent('Supply / Demand')
  expect(summary).not.toHaveTextContent('Rules incomplete')
  expect(screen.getByText(/Local variant: 1–3/)).toBeVisible()
  vi.restoreAllMocks()
})
