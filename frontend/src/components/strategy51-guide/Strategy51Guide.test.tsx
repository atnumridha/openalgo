import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { Strategy51Guide } from './Strategy51Guide'
import { DEFAULT_STRATEGY51_SETTINGS } from './settings'
it('keeps the51-strategy catalog out of the default chart area and exposes every source strategy in Details', () => {
  const change = vi.fn()
  render(
    <Strategy51Guide
      result={null}
      settings={DEFAULT_STRATEGY51_SETTINGS}
      onChange={change}
      symbol="NIFTY"
      exchange="NSE_INDEX"
      seconds={300}
    />
  )
  expect(screen.getByRole('region', { name: '51 strategies compact guide' })).toBeTruthy()
  expect(screen.queryByRole('table', { name: 'All 51 strategy readings' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Strategies & details' }))
  const rows = screen.getAllByRole('button', { name: /Focus strategy/ })
  expect(rows).toHaveLength(51)
  fireEvent.change(screen.getByLabelText('Find a strategy'), { target: { value: '7.7' } })
  expect(screen.getAllByRole('button', { name: /Focus strategy/ })).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: /Focus strategy 7.7/ }))
  expect(change).toHaveBeenCalledWith({ selected: '7.7' })
})

import type { Strategy51Result } from './types'
const guideResult = (): Strategy51Result => ({
  rows: [],
  events: [],
  readiness: 'last-session',
  reason: 'Historical reference',
  next: 'Monitor frozen SL/target; complicated source exit explanation',
  expected: 'Bullish',
  trend: 'bull',
  scope: 'NSE_INDEX:NIFTY:900',
  processed: 20,
  trendLines: [],
  plan: {
    id: 'chosen',
    strategyId: '3.1',
    name: '3.1 · Basics of Dow theory',
    side: 'long',
    signalIndex: 17,
    index: 18,
    entry: 100,
    stop: 95,
    target: 115,
    targetOrigin: 'local',
    targetMethod: 'Local 3R',
    stopMethod: 'Swing',
    expected: 'Bullish',
    next: 'Monitor',
    exitRule: 'Source exit',
    notes: [],
    points: [],
    time: 1000,
    signalTime: 900,
    createdAt: 1000,
    createdIndex: 18,
    status: 'active',
  },
})
it('leads with REVIEW for an earlier session and keeps the three prices separate from source details', () => {
  render(
    <Strategy51Guide
      result={guideResult()}
      settings={DEFAULT_STRATEGY51_SETTINGS}
      onChange={() => {}}
      symbol="NIFTY"
      exchange="NSE_INDEX"
      seconds={900}
    />
  )
  expect(screen.getByLabelText('51 strategy action')).toHaveTextContent('REVIEW · Earlier candles')
  expect(screen.getByText('3.1 · Dow swing break')).toBeInTheDocument()
  expect(screen.getByLabelText('Why this setup')).toBeInTheDocument()
  expect(screen.getByLabelText('Next chart action')).toHaveTextContent(
    /review of this existing reference/i
  )
  expect(screen.getByLabelText('51 strategy price references').children).toHaveLength(3)
})
it('explains an already confirmed live plan as a reference rather than a new entry on every update', () => {
  render(
    <Strategy51Guide
      result={{ ...guideResult(), readiness: 'ready' }}
      settings={DEFAULT_STRATEGY51_SETTINGS}
      onChange={() => {}}
      symbol="NIFTY"
      exchange="NSE_INDEX"
      seconds={900}
    />
  )
  expect(screen.getByLabelText('51 strategy action')).toHaveTextContent('LONG SETUP')
  expect(screen.getByLabelText('Next chart action')).toHaveTextContent(
    'Track this existing reference; each update is not a fresh entry.'
  )
})

import { STRATEGIES_51 } from './catalog'
it('shows a live51-scan heartbeat and lets me inspect matching conditions without enabling every chart label', () => {
  const r = guideResult()
  r.readiness = 'ready'
  r.completedAt = Date.UTC(2026, 10, 6, 4, 30) / 1000
  r.rows = STRATEGIES_51.map((definition, i) => ({
    definition,
    state: i === 0 ? 'confirmed' : i < 8 ? 'waiting' : i < 20 ? 'needs-data' : 'timeframe',
    reason: 'Rule status',
    next: 'Wait for source confirmation',
    notes: [],
  }))
  render(
    <Strategy51Guide
      result={r}
      settings={DEFAULT_STRATEGY51_SETTINGS}
      onChange={() => {}}
      symbol="NIFTY"
      exchange="NSE_INDEX"
      seconds={900}
    />
  )
  expect(screen.getByLabelText('51 strategy scan status')).toHaveTextContent('51/51 checked')
  expect(screen.getByLabelText('51 strategy scan status')).toHaveTextContent('8 watching')
  expect(screen.getByLabelText('51 strategy scan status')).toHaveTextContent('1 match')
  fireEvent.click(screen.getByRole('button', { name: 'Strategies & details' }))
  fireEvent.change(screen.getByLabelText('Reading status'), { target: { value: 'confirmed' } })
  expect(screen.getAllByRole('button', { name: /Focus strategy/ })).toHaveLength(1)
  fireEvent.change(screen.getByLabelText('Reading status'), { target: { value: 'blocked' } })
  expect(screen.getAllByRole('button', { name: /Focus strategy/ })).toHaveLength(12)
})
it('does not advertise51 live detections when chart data is unavailable', () => {
  const r = guideResult()
  r.readiness = 'unavailable'
  r.processed = 0
  r.plan = undefined
  render(
    <Strategy51Guide
      result={r}
      settings={DEFAULT_STRATEGY51_SETTINGS}
      onChange={() => {}}
      symbol="NIFTY"
      exchange="NSE_INDEX"
      seconds={900}
    />
  )
  expect(screen.getByLabelText('51 strategy scan status')).toHaveTextContent('Scanner paused')
  expect(screen.getByLabelText('51 strategy scan status')).not.toHaveTextContent('51/51 checked')
})

import { example } from './explanationFixtures'
it('explains the visible setup by default and keeps rounded price references on complete lines', () => {
  render(
    <Strategy51Guide
      result={example()}
      settings={DEFAULT_STRATEGY51_SETTINGS}
      onChange={() => {}}
      symbol="NIFTY"
      exchange="NSE_INDEX"
      seconds={900}
    />
  )
  expect(screen.getByLabelText('Why this setup')).toHaveTextContent(/pullback/i)
  expect(screen.getByLabelText('Price progress')).toHaveTextContent('156.50')
  expect(screen.getByLabelText('Expected scenario')).toHaveTextContent('256.25')
  expect(screen.getByLabelText('Setup invalidation')).toHaveTextContent('24,667.48')
  expect(screen.getByLabelText('51 strategy action')).toHaveTextContent('MARKET CLOSED')
  expect(screen.getByLabelText('51 strategy price references')).toHaveTextContent('25,286.60')
  expect(screen.getByText('25,286.60')).toHaveClass('whitespace-nowrap')
  expect(
    screen.queryByText('Previous-session levels. Wait for fresh candles before using this setup.')
  ).not.toBeInTheDocument()
})

it('labels selected history as replay review rather than saying that the market is closed', () => {
  const r = example()
  r.viewMode = 'history'
  render(
    <Strategy51Guide
      result={r}
      settings={DEFAULT_STRATEGY51_SETTINGS}
      onChange={() => {}}
      symbol="NIFTY"
      exchange="NSE_INDEX"
      seconds={900}
    />
  )
  expect(screen.getByLabelText('51 strategy action')).toHaveTextContent('REVIEW · History / replay')
  expect(screen.getByLabelText('Next chart action')).not.toHaveTextContent(/market closed/i)
})
