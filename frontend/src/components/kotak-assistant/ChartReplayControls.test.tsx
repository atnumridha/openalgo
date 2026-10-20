import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ChartReplayControls } from './ChartReplayControls'
import { publishChartCandles } from './chartCandleStore'

describe('Chart replay controls', () => {
  afterEach(() => vi.useRealTimers())
  it('steps, plays at the chosen speed, pauses at the end and returns live', async () => {
    vi.useFakeTimers()
    const start = Math.floor(Date.now() / 300000) * 300 + 19800 - 10 * 300
    const bars = Array.from({ length: 10 }, (_, i) => ({
      time: start + i * 300,
      open: 100,
      high: 105,
      low: 99,
      close: 102,
      volume: 100,
    }))
    publishChartCandles('replay-a', bars)
    publishChartCandles('replay-b', bars)
    const change = vi.fn()
    const view = render(
      <ChartReplayControls
        scope="a"
        keys={['replay-a', 'replay-b']}
        interval="5m"
        onChange={change}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
    expect(change.mock.lastCall?.[0]?.until).toBe(start + 900)
    fireEvent.click(screen.getByRole('button', { name: 'Next replay candle' }))
    expect(change.mock.lastCall?.[0]?.until).toBe(start + 1200)
    fireEvent.change(screen.getByLabelText('Replay speed'), { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Play replay' }))
    await act(async () => vi.advanceTimersByTimeAsync(250))
    expect(change.mock.lastCall?.[0]?.until).toBe(start + 1500)
    fireEvent.click(screen.getByRole('button', { name: 'Pause replay' }))
    await act(async () => vi.advanceTimersByTimeAsync(500))
    expect(change.mock.lastCall?.[0]?.until).toBe(start + 1500)
    fireEvent.change(screen.getByLabelText('Replay candle'), { target: { value: '8' } })
    fireEvent.click(screen.getByRole('button', { name: 'Play replay' }))
    await act(async () => vi.advanceTimersByTimeAsync(500))
    expect(screen.getByRole('button', { name: 'Play replay' })).toBeDisabled()
    expect(screen.getByText('End of loaded history')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Return to live' }))
    expect(change.mock.lastCall?.[0]).toBeNull()
    expect(screen.getByRole('button', { name: 'Replay charts' })).toBeInTheDocument()
    view.unmount()
  })
  it('explains missing history and validates the replay date', () => {
    const change = vi.fn()
    render(
      <ChartReplayControls
        scope="empty"
        keys={['missing-history']}
        interval="5m"
        onChange={change}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
    expect(screen.getByRole('status')).toHaveTextContent(
      'Load at least two shared completed candles'
    )
    expect(change.mock.lastCall?.[0]).toBeNull()
  })
  it('jumps without revealing the following candle and disposes playback on unmount', async () => {
    vi.useFakeTimers()
    const start = Math.floor(Date.now() / 300000) * 300 + 19800 - 10 * 300
    publishChartCandles(
      'replay-date',
      Array.from({ length: 10 }, (_, i) => ({
        time: start + i * 300,
        open: 100,
        high: 105,
        low: 99,
        close: 102,
        volume: 100,
      }))
    )
    const change = vi.fn()
    const view = render(
      <ChartReplayControls scope="date" keys={['replay-date']} interval="5m" onChange={change} />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
    fireEvent.change(screen.getByLabelText('Replay start time IST'), {
      target: { value: new Date((start + 1260) * 1000).toISOString().slice(0, 16) },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Jump' }))
    expect(change.mock.lastCall?.[0].until).toBe(start + 1200)
    fireEvent.change(screen.getByLabelText('Replay start time IST'), {
      target: { value: '2020-01-01T09:15' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Jump' }))
    expect(screen.getByLabelText('Replay message')).toHaveTextContent(
      'Choose a time within the loaded history'
    )
    fireEvent.click(screen.getByRole('button', { name: 'Play replay' }))
    view.unmount()
    const count = change.mock.calls.length
    await act(async () => vi.advanceTimersByTimeAsync(2000))
    expect(change).toHaveBeenCalledTimes(count)
  })
  it('uses the native date field value when Jump is clicked before a change event', () => {
    const start = Math.floor(Date.now() / 300000) * 300 + 19800 - 10 * 300
    publishChartCandles(
      'native-date',
      Array.from({ length: 10 }, (_, i) => ({
        time: start + i * 300,
        open: 100,
        high: 105,
        low: 99,
        close: 102,
        volume: 100,
      }))
    )
    const change = vi.fn()
    render(
      <ChartReplayControls
        scope="native-date"
        keys={['native-date']}
        interval="5m"
        onChange={change}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
    const input = screen.getByLabelText('Replay start time IST') as HTMLInputElement
    input.value = new Date((start + 1800) * 1000).toISOString().slice(0, 16)
    fireEvent.click(screen.getByRole('button', { name: 'Jump' }))
    expect(change.mock.lastCall?.[0].until).toBe(start + 1800)
  })
})

it('uses the chosen date for replay and starts at its first completed candle', () => {
  const start = Date.UTC(2026, 9, 15, 9, 15) / 1000
  vi.spyOn(Date, 'now').mockReturnValue(Date.UTC(2026, 9, 15, 10))
  const bars = Array.from({ length: 4 }, (_, i) => ({
    time: start + i * 300,
    open: 100,
    high: 105,
    low: 99,
    close: 102,
    volume: 100,
  }))
  publishChartCandles('session-date', [
    ...bars.map((b) => ({ ...b, time: b.time - 86400 })),
    ...bars,
  ])
  const change = vi.fn(),
    sessionChange = vi.fn()
  render(
    <ChartReplayControls
      scope="session"
      keys={['session-date']}
      interval="5m"
      sessionDate="2026-10-15"
      onSessionDateChange={sessionChange}
      onChange={change}
    />
  )
  expect(screen.getByLabelText('Chart date IST')).toHaveValue('2026-10-15')
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(change.mock.lastCall?.[0].until).toBe(start + 300)
  expect(screen.getByLabelText('Replay start time IST')).toHaveAttribute('min', '2026-10-15T09:20')
  expect(screen.getByLabelText('Replay start time IST')).toHaveAttribute('max', '2026-10-15T09:35')
  fireEvent.change(screen.getByLabelText('Replay start time IST'), {
    target: { value: '2026-10-14T09:30' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Jump' }))
  expect(screen.getByLabelText('Replay message')).toHaveTextContent(
    'Choose a time within 2026-10-15'
  )
  expect(change.mock.lastCall?.[0].until).toBe(start + 300)
  fireEvent.input(screen.getByLabelText('Chart date IST'), { target: { value: '2026-10-14' } })
  expect(sessionChange).toHaveBeenCalledWith('2026-10-14')
  expect(change.mock.lastCall?.[0]).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Today' }))
  expect(sessionChange).toHaveBeenLastCalledWith('2026-10-15')
  vi.restoreAllMocks()
})

it('applies an inclusive From/To range and validates reversed and future dates', () => {
  vi.spyOn(Date, 'now').mockReturnValue(Date.UTC(2026, 9, 15, 10))
  const start = Date.UTC(2026, 9, 15, 9, 15) / 1000
  const bars = [-1, 0].flatMap((day) =>
    Array.from({ length: 3 }, (_, i) => ({
      time: start + day * 86400 + i * 300,
      open: 100,
      high: 101,
      low: 99,
      close: 100,
      volume: 10,
    }))
  )
  publishChartCandles('range-control', bars)
  const change = vi.fn(),
    apply = vi.fn()
  render(
    <ChartReplayControls
      scope="range"
      keys={['range-control']}
      interval="5m"
      sessionDate="2026-10-14"
      sessionEndDate="2026-10-15"
      onSessionRangeChange={apply}
      onChange={change}
    />
  )
  expect(screen.getByLabelText('From date IST')).toHaveValue('2026-10-14')
  expect(screen.getByLabelText('To date IST')).toHaveValue('2026-10-15')
  fireEvent.click(screen.getByRole('button', { name: 'Replay charts' }))
  expect(change.mock.lastCall?.[0].timeline).toHaveLength(6)
  expect(change.mock.lastCall?.[0].until).toBe(start - 86400 + 300)
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-15' } })
  fireEvent.input(screen.getByLabelText('To date IST'), { target: { value: '2026-10-14' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  expect(screen.getByLabelText('Replay message')).toHaveTextContent(
    'From date must be on or before To date'
  )
  expect(apply).not.toHaveBeenCalled()
  fireEvent.input(screen.getByLabelText('To date IST'), { target: { value: '2026-10-16' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  expect(screen.getByLabelText('Replay message')).toHaveTextContent('today in IST')
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-13' } })
  fireEvent.input(screen.getByLabelText('To date IST'), { target: { value: '2026-10-15' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }))
  expect(apply).toHaveBeenCalledWith({ start: '2026-10-13', end: '2026-10-15' })
  expect(change.mock.lastCall?.[0]).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Today' }))
  expect(apply).toHaveBeenLastCalledWith({ start: '2026-10-15', end: '2026-10-15' })
  vi.restoreAllMocks()
})

it('requires applying edited dates before starting replay and waits for range history', () => {
  const view = render(
    <ChartReplayControls
      scope="loading-range"
      keys={['missing']}
      interval="15m"
      sessionDate="2026-10-14"
      sessionEndDate="2026-10-15"
      onSessionRangeChange={vi.fn()}
      onChange={vi.fn()}
    />
  )
  fireEvent.input(screen.getByLabelText('From date IST'), { target: { value: '2026-10-13' } })
  expect(screen.getByRole('button', { name: 'Replay charts' })).toBeDisabled()
  expect(screen.getByText('Apply dates to update the chart')).toBeVisible()
  view.rerender(
    <ChartReplayControls
      key="new-range"
      scope="loading-range"
      keys={['missing']}
      interval="15m"
      sessionDate="2026-10-13"
      sessionEndDate="2026-10-15"
      onSessionRangeChange={vi.fn()}
      onChange={vi.fn()}
      loading
    />
  )
  expect(screen.getByRole('button', { name: 'Replay charts' })).toBeDisabled()
  expect(screen.getByText('Loading selected dates…')).toBeVisible()
})
