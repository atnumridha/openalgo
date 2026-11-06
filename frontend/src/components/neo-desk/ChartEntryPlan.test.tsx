import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { ChartEntryPlan } from './ChartEntryPlan'
import type { PlanBar } from './chartTradePlan'
const bars: PlanBar[] = Array.from({ length: 35 }, (_, i) => ({
  time: 1793332800 + i * 300,
  open: 100,
  high: 102,
  low: 98,
  close: 100,
}))
bars[25] = { ...bars[25], open: 98, high: 100, low: 94, close: 98 }
bars[29] = { ...bars[29], open: 104, high: 108, low: 102, close: 104 }
const wrap = (node: React.ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {node}
  </QueryClientProvider>
)
it('plots a user-provided outside entry with automatic SL and exact 2R; recalculates on explicit request', async () => {
  const onLevels = vi.fn()
  const content = (source: PlanBar[], ready = true) => (
    <ChartEntryPlan
      symbol="BTCUSD"
      exchange="DELTA"
      interval="5m"
      scope="test"
      bars={source}
      ready={ready}
      tickSize={0.5}
      onLevels={onLevels}
    />
  )
  const view = render(wrap(content(bars)))
  fireEvent.click(screen.getByRole('button', { name: /Entry.*SL.*Target/ }))
  fireEvent.change(screen.getByLabelText('Your entry price'), { target: { value: '100' } })
  await waitFor(() =>
    expect(onLevels).toHaveBeenLastCalledWith(expect.objectContaining({ entry: 100 }))
  )
  const initial = onLevels.mock.lastCall![0]
  expect(initial.stop).toBeLessThan(94)
  expect(initial.target - 100).toBeCloseTo(2 * (100 - initial.stop), 8)
  const changed = bars.map((b, i) => (i === 25 ? { ...b, low: 90 } : b))
  view.rerender(wrap(content(changed)))
  expect(onLevels).toHaveBeenLastCalledWith(initial)
  fireEvent.click(screen.getByRole('button', { name: 'Recalculate SL and target' }))
  await waitFor(() => expect(onLevels.mock.lastCall![0].stop).toBeLessThan(initial.stop))
  view.rerender(wrap(content(changed, false)))
  await waitFor(() => expect(onLevels).toHaveBeenLastCalledWith(null))
})
it('reverses BTC short geometry and rejects off-tick fills instead of silently changing entry', async () => {
  const onLevels = vi.fn()
  render(
    wrap(
      <ChartEntryPlan
        symbol="BTCUSD"
        exchange="DELTA"
        interval="5m"
        scope="test2"
        bars={bars}
        ready
        tickSize={0.5}
        onLevels={onLevels}
      />
    )
  )
  fireEvent.click(screen.getByRole('button', { name: /Entry.*SL.*Target/ }))
  fireEvent.change(screen.getByLabelText('Position direction'), { target: { value: 'short' } })
  fireEvent.change(screen.getByLabelText('Your entry price'), { target: { value: '100' } })
  await waitFor(() => expect(onLevels.mock.lastCall?.[0]?.stop).toBeGreaterThan(108))
  expect(onLevels.mock.lastCall![0].target).toBeLessThan(100)
  fireEvent.change(screen.getByLabelText('Your entry price'), { target: { value: '100.25' } })
  await waitFor(() => expect(onLevels).toHaveBeenLastCalledWith(null))
  expect(screen.getByRole('status')).toHaveTextContent(/price increment/)
})

it.each([
  ['RELIANCE', 'NSE'],
  ['GOLD30NOV26100000PE', 'MCX'],
])('freezes %s automatic plans through corrected history and uses bullish premium trend for a bought PE', async (symbol, exchange) => {
  const start = bars[0].time,
    source = Array.from({ length: 26 }, (_, i) => ({ ...bars[0], time: start + i * 300 }))
  source[20].high = 104
  source[24] = { time: start + 24 * 300, open: 102, high: 107, low: 101, close: 106 }
  source[25] = { time: start + 25 * 300, open: 105, high: 106, low: 103.5, close: 105.5 }
  const trend = Array.from({ length: 25 }, (_, i) => ({
    ...bars[0],
    time: start - 30000 + i * 900,
  }))
  trend[3].high = 110
  trend[9].high = 115
  trend[6].low = 90
  trend[12].low = 95
  const onLevels = vi.fn(),
    loadTrend = vi.fn(async () => trend)
  const content = (data: PlanBar[]) => (
    <ChartEntryPlan
      symbol={symbol}
      exchange={exchange}
      interval="5m"
      scope="auto"
      bars={data}
      ready
      tickSize={0.05}
      trendSource={{ symbol, exchange }}
      loadTrend={loadTrend}
      onLevels={onLevels}
    />
  )
  const view = render(wrap(content(source)))
  fireEvent.click(screen.getByRole('button', { name: /Entry.*SL.*Target/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Automatic setup' }))
  await waitFor(() => expect(onLevels.mock.lastCall?.[0]?.entry).toBe(106.05))
  const frozen = onLevels.mock.lastCall![0]
  const after = [
    ...source,
    { time: start + 26 * 300, open: 106, high: 107, low: 104, close: 106.5 },
  ]
  view.rerender(wrap(content(after)))
  expect(screen.getByRole('status')).toHaveTextContent('Entry touched')
  view.rerender(wrap(content(after.map((b, i) => (i === 18 ? { ...b, low: 90 } : b)))))
  expect(onLevels).toHaveBeenLastCalledWith(frozen)
})
