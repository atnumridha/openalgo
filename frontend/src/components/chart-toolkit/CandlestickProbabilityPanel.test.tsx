import { render, screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'
import { CandlestickProbabilityPanel } from './CandlestickProbabilityPanel'
import type { CandleSetup, CandleStudy } from './candleProbabilityTypes'

const time = Date.UTC(2026, 9, 29, 5, 0) / 1000
const setup: CandleSetup = {
  time,
  pattern: 'engulfing',
  name: 'Bullish engulfing',
  side: 'CALL',
  context: 'aligned',
  key: 'engulfing:CALL:aligned',
  entry: 100,
  stop: 99,
  target: 102,
  support: 98,
  resistance: 103,
  estimate: { samples: 58, targets: 48, probability: 49 / 60, lower: 0.71, upper: 0.91 },
  qualified: true,
  reason: 'Evidence qualifies',
}
const study = (overrides: Partial<CandleStudy> = {}): CandleStudy => ({
  bars: [],
  setups: [setup],
  outcomes: [],
  signalOutcomes: [],
  latest: setup,
  lastSetup: setup,
  active: setup,
  lastOutcome: null,
  support: 98,
  resistance: 103,
  closedTime: time,
  model: {
    version: 1,
    symbol: 'NIFTY',
    exchange: 'NSE_INDEX',
    seconds: 60,
    indian: true,
    trainedThrough: time - 86400,
    source: 'Audited Kotak history',
    counts: {},
  },
  seedUsed: true,
  ...overrides,
})
const props = { symbol: 'NIFTY', exchange: 'NSE_INDEX', seconds: 60, ready: true, now: time + 65 }

it('shows a qualified index decision with scoped event evidence and price references', () => {
  render(<CandlestickProbabilityPanel {...props} study={study()} />)
  expect(screen.getByRole('status')).toHaveTextContent('BUY CALL')
  expect(screen.getByText('81.7%')).toBeVisible()
  expect(screen.getByText('Prior price context · aligned')).toBeVisible()
  expect(screen.getByText(/48 \/ 58/)).toBeVisible()
  expect(screen.getByText(/71.0%–91.0%/)).toBeVisible()
  expect(screen.getByText(/NIFTY · NSE_INDEX · 1m/)).toBeVisible()
  expect(screen.getByText(/Audited Kotak history/)).toBeVisible()
  expect(screen.getByText(/not option profit/i)).toBeVisible()
  expect(within(screen.getByLabelText('Price references')).getByText('102.00')).toBeVisible()
})

it.each([
  { ready: false, now: time + 65, reason: /waiting for verified/i },
  { ready: true, now: time + 211, reason: /stale/i },
])('suppresses the decision when fresh verified data is unavailable: $reason', ({
  reason,
  ...state
}) => {
  render(<CandlestickProbabilityPanel {...props} {...state} study={study()} />)
  expect(screen.getByRole('status')).toHaveTextContent('WAIT')
  expect(screen.getByText(reason)).toBeVisible()
  expect(screen.queryByText('BUY CALL')).not.toBeInTheDocument()
})

it('labels an older active setup as HOLD instead of suggesting a new entry', () => {
  render(
    <CandlestickProbabilityPanel
      {...props}
      now={time + 125}
      study={study({ closedTime: time + 60, latest: null })}
    />
  )
  expect(screen.getByRole('status')).toHaveTextContent('HOLD CALL')
  expect(screen.getByText(/tracking the qualified setup/i)).toBeVisible()
})

it('keeps insufficient evidence and candidate levels visible while waiting', () => {
  const candidate = {
    ...setup,
    qualified: false,
    estimate: { ...setup.estimate, samples: 8, targets: 7 },
    reason: 'Only 8 of 50 resolved observations',
  }
  render(
    <CandlestickProbabilityPanel
      {...props}
      study={study({ latest: candidate, lastSetup: candidate, active: null })}
    />
  )
  expect(screen.getByRole('status')).toHaveTextContent('WAIT')
  expect(screen.getByText(/Only 8 of 50/)).toBeVisible()
  expect(screen.getByText(/Unqualified reference/i)).toBeVisible()
})

it('does not resurrect a resolved historical setup when the latest candle has no pattern', () => {
  render(
    <CandlestickProbabilityPanel
      {...props}
      study={study({
        latest: null,
        active: null,
        lastOutcome: {
          setup,
          time: time + 60,
          result: 'TIMEOUT',
          ambiguous: false,
          price: 100.5,
          r: 0.5,
        },
      })}
    />
  )
  expect(screen.getByRole('status')).toHaveTextContent('WAIT')
  expect(screen.getByText(/No setup on the latest completed candle/i)).toBeVisible()
  expect(screen.getByText(/TIMEOUT/)).toBeVisible()
  expect(screen.getByText(/did not reach 2R/i)).toBeVisible()
})

it.each([
  'NFO',
  'DELTA',
])('describes price direction without a put recommendation on %s', (exchange) => {
  const bearish = { ...setup, side: 'PUT' as const, name: 'Bearish engulfing' }
  const value = study({ latest: bearish, active: bearish })
  value.model = { ...value.model, exchange }
  render(<CandlestickProbabilityPanel {...props} exchange={exchange} study={value} />)
  expect(screen.getByRole('status')).toHaveTextContent(exchange === 'DELTA' ? 'SHORT' : 'BEAR')
  expect(screen.queryByText(/BUY PUT/)).not.toBeInTheDocument()
  if (exchange === 'NFO') expect(screen.getByText(/premium direction/i)).toBeVisible()
})

it('clears mismatched market evidence during a scope change', () => {
  render(
    <CandlestickProbabilityPanel {...props} symbol="SENSEX" exchange="BSE_INDEX" study={study()} />
  )
  expect(screen.getByRole('status')).toHaveTextContent('WAIT')
  expect(screen.queryByText('81.7%')).not.toBeInTheDocument()
  expect(screen.queryByText(/Audited Kotak/)).not.toBeInTheDocument()
})

it.each([
  'CE',
  'PE',
] as const)('shows AVOID %s without suggesting a short-premium SL or target', (side) => {
  const symbol = `NIFTY03NOV2623000${side}`,
    exchange = 'NFO',
    bearish = { ...setup, side: 'PUT' as const, stop: 101, target: 98 },
    original = study(),
    scoped = {
      ...original,
      model: { ...original.model, symbol, exchange },
      latest: bearish,
      active: bearish,
      lastSetup: bearish,
    }
  render(
    <CandlestickProbabilityPanel {...props} symbol={symbol} exchange={exchange} study={scoped} />
  )
  expect(screen.getByRole('status')).toHaveTextContent(`AVOID ${side}`)
  const levels = within(screen.getByLabelText('Price references'))
  expect(levels.queryByText('101.00')).not.toBeInTheDocument()
  expect(levels.getAllByText('—').length).toBe(3)
})
