import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import type { ReplayTrade } from '@/api/neoResearch'
import { ReplayChart, replayBars, replayFrame } from './ReplayChart'

const m = vi.hoisted(() => ({
  series: [] as Array<{ setData: ReturnType<typeof vi.fn> }>,
  lines: vi.fn(() => ({})),
  marks: vi.fn(),
  remove: vi.fn(),
}))
vi.mock('lightweight-charts', () => ({
  CandlestickSeries: 'candle',
  LineSeries: 'line',
  LineStyle: { Dashed: 2 },
  createChart: () => ({
    addSeries: () => {
      const s = { setData: vi.fn(), createPriceLine: m.lines, removePriceLine: vi.fn() }
      m.series.push(s)
      return s
    },
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: m.remove,
  }),
  createSeriesMarkers: () => ({ setMarkers: m.marks }),
}))
const start = Date.parse('2026-10-14T10:00:00+05:30') / 1000
const trade: ReplayTrade = {
  symbol: 'NIFTY19OCT2622200PE',
  direction: 'PE',
  entry_time: '2026-10-14T10:00:12+05:30',
  exit_time: '2026-10-14T10:02:25+05:30',
  quantity: 65,
  entry_price: '50',
  exit_price: '60',
  initial_option_stop: '45',
  initial_index_stop: '22100',
  index_target: '21800',
  index_reference: '22050',
  status: 'closed',
  option_bars: Array.from({ length: 3 }, (_, i) => ({
    time: start + i * 60,
    open: 50,
    high: 62,
    low: 49,
    close: 60,
    volume: 100,
  })),
  index_bars: [{ time: start, open: 22050, high: 22060, low: 22040, close: 22050, volume: 0 }],
  trail: [
    { time: start + 80, option_stop: '52', index_stop: '22080' },
    { time: start + 140, option_stop: '58', index_stop: '22060' },
  ],
}
beforeEach(() => {
  vi.clearAllMocks()
  m.series.length = 0
})
it('plays candles without exposing future exits or trail adjustments', async () => {
  const v = render(<ReplayChart trade={trade} />)
  await waitFor(() =>
    expect(m.marks).toHaveBeenCalledWith(
      expect.arrayContaining([expect.objectContaining({ text: 'EXIT' })])
    )
  )
  fireEvent.click(screen.getByRole('button', { name: 'Replay from start' }))
  expect(screen.getByLabelText('Replay position')).toHaveTextContent('1 / 3')
  expect(m.marks.mock.calls.at(-1)?.[0]).toEqual([
    expect.objectContaining({ text: 'BUY PE', time: start }),
  ])
  expect(m.series[1].setData.mock.calls.at(-1)?.[0]).toEqual([])
  fireEvent.click(screen.getByRole('button', { name: 'Next candle' }))
  expect(m.series[1].setData.mock.calls.at(-1)?.[0]).toEqual([{ time: start + 60, value: 52 }])
  fireEvent.click(screen.getByRole('button', { name: 'Show full trade' }))
  expect(m.marks.mock.calls.at(-1)?.[0]).toHaveLength(2)
  v.unmount()
  expect(m.remove).toHaveBeenCalledOnce()
})
it('keeps index targets on the index scale and omits unrecorded option targets', () => {
  const option = replayFrame(trade, 'option', trade.option_bars, 2)
  expect(option.levels.find((l) => l.title === 'TARGET')).toBeUndefined()
  const index = replayFrame(trade, 'index', trade.index_bars, 0)
  expect(index.levels.find((l) => l.title === 'TARGET')?.price).toBe(21800)
  expect(index.marks).toHaveLength(2)
})
it('does not snap fills across a missing candle or convert missing prices to zero', () => {
  const t = {
    ...trade,
    initial_option_stop: null,
    initial_index_stop: null,
    index_target: null,
    option_target: null,
    trail: [],
    entry_time: '2026-10-14T10:01:12+05:30',
  }
  const frame = replayFrame(t, 'option', [trade.option_bars[0], trade.option_bars[2]], 0)
  expect(frame.marks).toEqual([])
  expect(frame.levels).toEqual([])
  expect(
    replayBars([trade.option_bars[2], trade.option_bars[0], trade.option_bars[0]])
  ).toHaveLength(2)
})
it('plays only when requested and can pause the timeline', async () => {
  vi.useFakeTimers()
  try {
    render(<ReplayChart trade={trade} />)
    fireEvent.click(screen.getByRole('button', { name: 'Replay from start' }))
    fireEvent.click(screen.getByRole('button', { name: 'Play replay' }))
    const { act } = await import('@testing-library/react')
    await act(async () => {
      vi.advanceTimersByTime(600)
    })
    expect(screen.getByLabelText('Replay position')).toHaveTextContent('2 / 3')
    fireEvent.click(screen.getByRole('button', { name: 'Pause replay' }))
    await act(async () => {
      vi.advanceTimersByTime(1800)
    })
    expect(screen.getByLabelText('Replay position')).toHaveTextContent('2 / 3')
  } finally {
    vi.useRealTimers()
  }
})

it('explains unavailable option data, disables playback and retains the saved index view', () => {
  render(<ReplayChart trade={{ ...trade, recorded: true, option_bars: [] }} />)
  expect(screen.getByRole('status')).toHaveTextContent('No saved option candles cover this trade')
  expect(screen.getByRole('status')).toHaveTextContent('NIFTY index')
  for (const name of [
    'Replay from start',
    'Play replay',
    'Previous candle',
    'Next candle',
    'Show full trade',
  ])
    expect(screen.getByRole('button', { name })).toBeDisabled()
  expect(screen.getByRole('slider', { name: 'Replay candle' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'NIFTY index' }))
  expect(screen.getByLabelText('Replay position')).toHaveTextContent('1 / 1')
  expect(screen.getByRole('button', { name: 'Replay from start' })).toBeEnabled()
  expect(screen.getByLabelText('Replay position')).not.toHaveTextContent('No saved')
})

it('keeps unavailable option and index candles explicit without inventing playback', () => {
  render(<ReplayChart trade={{ ...trade, recorded: true, option_bars: [], index_bars: [] }} />)
  expect(screen.getByRole('status')).toHaveTextContent('No saved option candles cover this trade')
  expect(screen.getByRole('button', { name: 'Play replay' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'NIFTY index' })).toBeDisabled()
  expect(m.series[0].setData.mock.calls.at(-1)?.[0]).toEqual([])
})
