import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { SetupResult } from '@/api/kotakAssistant'
import { SetupAssistant } from './SetupAssistant'

const setup = {
  strategy: 'opening_reversal',
  version: '1.0',
  mode: 'literal',
  stage: 'waiting_trigger',
  direction: 'PE',
  reason: 'Waiting for a price below the red candle low',
  evidence: ['Second high was known before the break'],
  setup_id: 'opening-1',
  reference: { price: 22590, time: 100, kind: 'H2' },
  trigger: 22608,
  signal_candle: { time: 200, open: 22620, high: 22625, low: 22608, close: 22610 },
  expires: 500,
  source: 'rest_snapshot',
  eligible: false,
} satisfies SetupResult
const props = {
  strategy: 'opening_reversal' as const,
  mode: 'confirmed' as const,
  onStrategyChange: vi.fn(),
  onModeChange: vi.fn(),
  onUseSetup: vi.fn(),
  now: 300,
}

describe('Chart setup assistant', () => {
  it('keeps index trigger context visible while a reversal is waiting for a later price', () => {
    render(
      <SetupAssistant {...props} setup={setup} executionReadiness={['Account books unavailable']} />
    )
    const panel = within(screen.getByLabelText('Chart setup assistant'))
    expect(panel.getByText('Watching PE below 22,608.00')).toHaveClass('text-red-500')
    expect(panel.getByText(/Waiting for a price below/)).toBeInTheDocument()
    expect(panel.getAllByText('22,608.00')[0]).toBeInTheDocument()
    expect(panel.getByText('22,590.00')).toBeInTheDocument()
    expect(panel.getByText(/3m 20s/)).toBeInTheDocument()
    expect(panel.getByRole('button', { name: 'Use setup' })).toBeDisabled()
    expect(panel.getByText('Account books unavailable')).toBeInTheDocument()
    expect(props.onUseSetup).not.toHaveBeenCalled()
  })
  it('adopts an eligible CE setup once without treating account readiness as chart readiness', () => {
    const use = vi.fn()
    render(
      <SetupAssistant
        {...props}
        setup={{ ...setup, direction: 'CE', stage: 'triggered', eligible: true }}
        onUseSetup={use}
        executionReadiness={['Broker checks run on Buy']}
      />
    )
    expect(screen.getByText('↑ CE TRIGGERED · BUY CALL')).toHaveClass('text-emerald-500')
    fireEvent.click(screen.getByRole('button', { name: 'Use setup' }))
    expect(use).toHaveBeenCalledOnce()
    expect(use.mock.calls[0][0]).toMatchObject({ direction: 'CE', stage: 'triggered' })
  })
  it('prevents replay or expired signals from being adopted into a live ticket', () => {
    const view = render(
      <SetupAssistant {...props} setup={{ ...setup, stage: 'triggered', eligible: true }} replay />
    )
    expect(screen.getByRole('button', { name: 'Use setup' })).toBeDisabled()
    expect(screen.getByText(/Read-only replay/)).toBeInTheDocument()
    view.rerender(
      <SetupAssistant
        {...props}
        setup={{ ...setup, stage: 'triggered', eligible: true, expires: 299 }}
      />
    )
    expect(screen.getByRole('button', { name: 'Use setup' })).toBeDisabled()
  })
})

it('retains the triggered event after its adoption window ends', () => {
  render(
    <SetupAssistant
      {...props}
      now={501}
      setup={{ ...setup, stage: 'triggered', eligible: false }}
    />
  )
  expect(screen.getByText('↓ PE TRIGGERED · BUY PUT')).toBeInTheDocument()
  expect(screen.getByText(/Entry window ended/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Use setup' })).toBeDisabled()
})

it('shows the selected premium plan and keeps index prices separate', () => {
  render(
    <SetupAssistant
      {...props}
      setup={setup}
      selectedContract={{
        symbol: 'NIFTY19OCT2622600PE',
        side: 'PE',
        strike: 22600,
        expiry: '19OCT26',
        quantity: 130,
        entry: 90,
        sl: 86.5,
        target: 102,
        source: 'Ticket values',
        costs: { netSL: -480, netTarget: 1508, chargesSL: 25, chargesTarget: 39 },
      }}
    />
  )
  const plan = within(screen.getByLabelText('Selected strike plan'))
  expect(plan.getByText('NIFTY19OCT2622600PE')).toBeInTheDocument()
  expect(plan.getByText('₹90.00')).toBeInTheDocument()
  expect(plan.getByText('₹86.50')).toBeInTheDocument()
  expect(plan.getByText('₹102.00')).toBeInTheDocument()
  expect(plan.getByText(/130 units/)).toBeInTheDocument()
  expect(plan.getByText(/-₹480.00/)).toBeInTheDocument()
  expect(plan.getByText(/₹1,508.00/)).toBeInTheDocument()
  expect(screen.getByText('22,608.00')).toBeInTheDocument()
})

it('follows the selected opening direction instead of the more advanced opposite sequence', () => {
  render(
    <SetupAssistant
      {...props}
      setup={{
        ...setup,
        stage: 'triggered',
        eligible: true,
        directions: {
          CE: {
            ...setup,
            direction: 'CE',
            stage: 'waiting_break',
            trigger: null,
            reason: 'Waiting for CE reference break',
            eligible: false,
          },
        },
      }}
      selectedContract={{
        symbol: 'NIFTY19OCT2622600CE',
        side: 'CE',
        strike: 22600,
        expiry: '19OCT26',
      }}
    />
  )
  expect(screen.queryByText('↓ PE TRIGGERED · BUY PUT')).not.toBeInTheDocument()
  expect(screen.getAllByText('Waiting for CE reference break').length).toBeGreaterThan(0)
  expect(screen.getByRole('button', { name: 'Use setup' })).toBeDisabled()
})

it('never makes a selected direction eligible while the index feed is stale', () => {
  render(
    <SetupAssistant
      {...props}
      setup={{
        ...setup,
        eligible: false,
        chart_fresh: false,
        reason: 'Fresh index quote unavailable',
        directions: { CE: { ...setup, direction: 'CE', stage: 'triggered', eligible: true } },
      }}
      selectedContract={{
        symbol: 'NIFTY19OCT2622600CE',
        side: 'CE',
        strike: 22600,
        expiry: '19OCT26',
      }}
    />
  )
  expect(screen.getByRole('button', { name: 'Use setup' })).toBeDisabled()
  expect(screen.getByText('Fresh index quote unavailable')).toBeInTheDocument()
})
