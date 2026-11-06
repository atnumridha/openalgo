import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DeltaTradeTimer } from './DeltaTradeTimer'
beforeEach(() => {
  vi.restoreAllMocks()
  sessionStorage.clear()
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-11-01T12:00:00Z'))
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})
it('starts at30:00 paused and supports ticking, pause and reset', async () => {
  render(<DeltaTradeTimer account="a" symbol="BTCUSD" />)
  expect(screen.getByRole('timer')).toHaveTextContent('30:00')
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000)
  })
  expect(screen.getByRole('timer')).toHaveTextContent('30:00')
  fireEvent.click(screen.getByRole('button', { name: 'Start' }))
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000)
  })
  expect(screen.getByRole('timer')).toHaveTextContent('29:58')
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000)
  })
  expect(screen.getByRole('timer')).toHaveTextContent('29:58')
  fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
  expect(screen.getByRole('timer')).toHaveTextContent('30:00')
  expect(screen.getByRole('button', { name: 'Pause' })).toBeDisabled()
})
it('restores a running deadline after remount and isolates account and symbol', async () => {
  const view = render(<DeltaTradeTimer account="a" symbol="BTCUSD" />)
  fireEvent.click(screen.getByRole('button', { name: 'Start' }))
  view.unmount()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(65000)
  })
  const restored = render(<DeltaTradeTimer account="a" symbol="BTCUSD" />)
  expect(screen.getByRole('timer')).toHaveTextContent('28:55')
  restored.rerender(<DeltaTradeTimer account="a" symbol="ETHUSD" />)
  expect(screen.getByRole('timer')).toHaveTextContent('30:00')
  restored.rerender(<DeltaTradeTimer account="b" symbol="BTCUSD" />)
  expect(screen.getByRole('timer')).toHaveTextContent('30:00')
  restored.rerender(<DeltaTradeTimer account="a" symbol="BTCUSD" />)
  expect(screen.getByRole('timer')).toHaveTextContent('28:55')
})
it('restores a paused remaining time without counting time spent away', async () => {
  const view = render(<DeltaTradeTimer account="a" symbol="BTCUSD" />)
  fireEvent.click(screen.getByRole('button', { name: 'Start' }))
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000)
  })
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
  view.unmount()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(60000)
  })
  render(<DeltaTradeTimer account="a" symbol="BTCUSD" />)
  expect(screen.getByRole('timer')).toHaveTextContent('29:55')
})
it('announces expiry at zero without network or financial actions', async () => {
  const network = vi.spyOn(globalThis, 'fetch')
  const view = render(<DeltaTradeTimer account="a" symbol="BTCUSD" />)
  fireEvent.click(screen.getByRole('button', { name: 'Start' }))
  view.unmount()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30 * 60 * 1000)
  })
  render(<DeltaTradeTimer account="a" symbol="BTCUSD" />)
  expect(screen.getByRole('timer')).toHaveTextContent('00:00')
  expect(screen.getByRole('status')).toHaveTextContent("Time's up")
  expect(screen.getByRole('button', { name: 'Start' })).toBeDisabled()
  expect(network).not.toHaveBeenCalled()
})
it('falls back to a paused timer and local warning when storage is unavailable', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  render(<DeltaTradeTimer account="a" symbol="BTCUSD" />)
  expect(screen.getByRole('timer')).toHaveTextContent('30:00')
  expect(screen.getByText(/Timer persistence unavailable/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Start' })).toBeEnabled()
})
it('recovers safely from a malformed saved timer', () => {
  sessionStorage.setItem(
    'delta-chart:timer:v1:a:BTCUSD',
    '{"version":1,"remainingMs":-1,"deadline":null}'
  )
  render(<DeltaTradeTimer account="a" symbol="BTCUSD" />)
  expect(screen.getByRole('timer')).toHaveTextContent('30:00')
  expect(screen.getByText(/Saved timer was invalid/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Start' })).toBeEnabled()
})
it('auto-starts once from entry placement and keeps manual pause/reset until a new entry', async () => {
  const placed = Date.now() / 1000 - 5
  const view = render(
    <DeltaTradeTimer account="a" symbol="BTCUSD" autoStartKey="entry-1" startedAt={placed} />
  )
  expect(screen.getByRole('timer')).toHaveTextContent('29:55')
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000)
  })
  view.rerender(
    <DeltaTradeTimer
      account="a"
      symbol="BTCUSD"
      autoStartKey="entry-1"
      startedAt={Date.now() / 1000}
    />
  )
  expect(screen.getByRole('timer')).toHaveTextContent('29:55')
  expect(screen.getByRole('button', { name: 'Pause' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
  expect(screen.getByRole('timer')).toHaveTextContent('30:00')
  expect(screen.getByRole('button', { name: 'Pause' })).toBeDisabled()
  view.rerender(
    <DeltaTradeTimer
      account="a"
      symbol="BTCUSD"
      autoStartKey="entry-2"
      startedAt={Date.now() / 1000}
    />
  )
  expect(screen.getByRole('button', { name: 'Pause' })).toBeEnabled()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000)
  })
  expect(screen.getByRole('timer')).toHaveTextContent('29:59')
})
it('restores auto-started entry time across reload and backfills an older manually expired timer', async () => {
  sessionStorage.setItem(
    'delta-chart:timer:v1:a:BTCUSD',
    JSON.stringify({ version: 1, remainingMs: 0, deadline: null })
  )
  const placed = Date.now() / 1000 - 300
  const view = render(
    <DeltaTradeTimer account="a" symbol="BTCUSD" autoStartKey="restored-entry" startedAt={placed} />
  )
  expect(screen.getByRole('timer')).toHaveTextContent('25:00')
  view.unmount()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(60000)
  })
  render(
    <DeltaTradeTimer account="a" symbol="BTCUSD" autoStartKey="restored-entry" startedAt={placed} />
  )
  expect(screen.getByRole('timer')).toHaveTextContent('24:00')
})
it('waits for a verified placement time and never resets to30:00 for an already expired entry', () => {
  const view = render(
    <DeltaTradeTimer account="a" symbol="BTCUSD" autoStartKey="unknown" startedAt={null} />
  )
  expect(screen.getByRole('button', { name: 'Pause' })).toBeDisabled()
  view.rerender(
    <DeltaTradeTimer
      account="a"
      symbol="BTCUSD"
      autoStartKey="old-entry"
      startedAt={Date.now() / 1000 - 1900}
    />
  )
  expect(screen.getByRole('timer')).toHaveTextContent('00:00')
  expect(screen.getByRole('status')).toHaveTextContent("Time's up")
})
