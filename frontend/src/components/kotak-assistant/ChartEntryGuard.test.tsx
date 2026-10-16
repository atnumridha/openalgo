import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import type { Snapshot } from '@/api/kotakAssistant'
import { ChartEntryGuard } from './ChartEntryGuard'

const desk = {
  day: {
    entry_limits: {
      entries: 3,
      losses: 1,
      max_entries: 3,
      max_losses: 2,
      blocked_reason: 'Daily entry limit reached · 3 entries',
    },
  },
  analysis: { action: 'CALL', reason: 'Break and retest' },
} as Snapshot

describe('Chart entry guard', () => {
  it('shows trade-count guidance as caution while leaving manual entry to the user', () => {
    render(
      <ChartEntryGuard
        desk={desk}
        indexFresh
        booksFresh
        mode="analyze"
        selected="NIFTY19OCT2622600CE"
      />
    )
    expect(screen.getByText('CAUTION')).toBeInTheDocument()
    expect(screen.getByText('Entries 3 / 3')).toBeInTheDocument()
    expect(screen.getByText('Losing trades 1 / 2')).toBeInTheDocument()
    expect(screen.getByText(/Guidance only; manual entry is your decision/)).toBeInTheDocument()
  })
  it('shows wait when selected side disagrees with confirmed signal', () => {
    render(
      <ChartEntryGuard
        desk={{ ...desk, day: {} } as never}
        indexFresh
        booksFresh
        mode="analyze"
        selected="NIFTY19OCT2622600PE"
      />
    )
    expect(screen.getByText('WAIT')).toBeInTheDocument()
    expect(screen.getByText('Selected PE · signal CE')).toBeInTheDocument()
  })
  it('never marks stale market data as a checked setup', () => {
    render(
      <ChartEntryGuard
        desk={{ ...desk, day: {} } as never}
        indexFresh={false}
        booksFresh
        mode="live"
        selected="NIFTY19OCT2622600CE"
      />
    )
    expect(screen.getByText('WAIT')).toBeInTheDocument()
    expect(screen.getByText('Waiting for fresh prices and account data')).toBeInTheDocument()
  })
})

it('shows fee-aware reward/risk for a matching checked preview', () => {
  render(
    <ChartEntryGuard
      desk={
        {
          ...desk,
          day: { entry_limits: { entries: 1, losses: 0, max_entries: 3, max_losses: 2 } },
        } as Snapshot
      }
      indexFresh
      booksFresh
      mode="analyze"
      selected="NIFTY19OCT2622600CE"
      plan={{ fits: true, net_rr: 1.75 } as never}
    />
  )
  expect(screen.getByText('SETUP CHECKED')).toBeInTheDocument()
  expect(screen.getByText('1:1.75 · charges included')).toBeInTheDocument()
})

const checkedAt = Date.parse('2026-10-15T10:45:05+05:30') / 1000
const liveChecks = {
  state: 'no_target',
  checked_at: checkedAt,
  history: 'fresh',
  one_closed_at: checkedAt - 5,
  five_closed_at: checkedAt - 5,
  trend: 'CALL',
  pattern_confirmed: true,
  target_available: false,
  reward_risk: null,
} as const

it('explains a missing target and displays actual evaluation and candle times', () => {
  render(
    <ChartEntryGuard
      desk={
        {
          ...desk,
          day: {},
          analysis: {
            action: 'WAIT',
            zones: [],
            reason: 'Uptrend · no confirmed resistance above price for a 2:1 target',
            checks: liveChecks,
          },
        } as Snapshot
      }
      indexFresh
      booksFresh
      mode="analyze"
      selected="NIFTY19OCT2622600CE"
      now={checkedAt}
    />
  )
  expect(screen.queryByText('Unconfirmed')).not.toBeInTheDocument()
  expect(screen.getByText('No target level')).toBeInTheDocument()
  expect(screen.getByLabelText('Setup checks')).toHaveTextContent('Uptrend')
  expect(screen.getByLabelText('Setup checks')).toHaveTextContent('1m trigger: Confirmed')
  expect(screen.getByText(/Checked 10:45:05 IST/)).toHaveTextContent('1m closed 10:45')
  expect(screen.getByRole('status')).toHaveTextContent('no confirmed resistance above')
})

it('updates the check time and prevents old candle analysis appearing checked', () => {
  const props = {
    indexFresh: true,
    booksFresh: true,
    mode: 'analyze' as const,
    selected: 'NIFTY19OCT2622600CE',
    plan: { fits: true, net_rr: 2 } as never,
  }
  const current = {
    ...desk,
    day: { entry_limits: { entries: 1, losses: 0, max_entries: 3, max_losses: 2 } },
    analysis: {
      action: 'CALL',
      zones: [],
      reason: 'Break and retest',
      checks: { ...liveChecks, state: 'confirmed', target_available: true, reward_risk: 3 },
    },
  } as Snapshot
  const { rerender } = render(<ChartEntryGuard {...props} desk={current} now={checkedAt} />)
  expect(screen.getByText('SETUP CHECKED')).toBeInTheDocument()
  rerender(<ChartEntryGuard {...props} desk={current} now={checkedAt + 70} />)
  expect(screen.queryByText('SETUP CHECKED')).not.toBeInTheDocument()
  expect(screen.getByText('Candles stale')).toBeInTheDocument()
  const next = {
    ...current,
    analysis: {
      ...current.analysis,
      checks: {
        ...current.analysis.checks!,
        checked_at: checkedAt + 70,
        one_closed_at: checkedAt + 55,
      },
    },
  }
  rerender(<ChartEntryGuard {...props} desk={next} now={checkedAt + 70} />)
  expect(screen.getByText('SETUP CHECKED')).toBeInTheDocument()
  expect(screen.getByText(/Checked 10:46:15 IST/)).toHaveTextContent('1m closed 10:46')
})
