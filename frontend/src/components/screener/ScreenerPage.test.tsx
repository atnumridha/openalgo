import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { ScreenerWorkspace } from './ScreenerWorkspace'
import { makePresets } from './presets'
import type { ScanRow } from './model'
const mocks = vi.hoisted(() => ({
  screens: vi.fn(),
  universes: vi.fn(),
  save: vi.fn(),
  remove: vi.fn(),
  events: vi.fn(),
  record: vi.fn(),
  run: vi.fn(),
  cancel: vi.fn(),
  sound: vi.fn(),
  scan: { rows: [] as ScanRow[], status: 'complete' },
}))
vi.mock('@/api/screener', () => ({ screenerApi: mocks }))
vi.mock('@/api/watchlist', () => ({ watchlistApi: { list: async () => [], addItem: vi.fn() } }))
vi.mock('./useScreener', () => ({
  useScreener: () => ({
    ...mocks.scan,
    datasets: [],
    pending: 0,
    failed: 0,
    missing: 0,
    error: '',
    run: mocks.run,
    cancel: mocks.cancel,
  }),
}))
vi.mock('@/lib/trading/alertDelivery', () => ({ readySound: vi.fn(), playAlertSound: mocks.sound }))
afterEach(() => {
  vi.clearAllMocks()
  vi.restoreAllMocks()
  mocks.scan = { rows: [], status: 'complete' }
})
it('saves, duplicates, renames and confirms deletion of a persisted screen', async () => {
  mocks.screens.mockResolvedValue([])
  mocks.universes.mockResolvedValue([{ id: 'stored', label: 'Downloaded data', items: [] }])
  mocks.events.mockResolvedValue([])
  mocks.save.mockImplementation(async (d, existing) => ({
    id: existing?.id ?? 7,
    name: d.name,
    revision: (existing?.revision ?? 0) + 1,
    definition: d,
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ScreenerWorkspace />
    </QueryClientProvider>
  )
  await screen.findByText('Downloaded data')
  fireEvent.change(screen.getByLabelText('Screen name'), { target: { value: 'My screen' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save screen' }))
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'My screen' }),
      undefined
    )
  )
  await waitFor(() => expect(screen.getByRole('button', { name: 'Duplicate' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Duplicate' }))
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'My screen copy' }),
      undefined
    )
  )
  fireEvent.change(screen.getByLabelText('Screen name'), { target: { value: 'Renamed' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save screen' }))
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Renamed' }),
      expect.objectContaining({ id: 7 })
    )
  )
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
  expect(mocks.remove).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }))
  await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith(7))
})

it('keeps initial matches silent, sounds only server-accepted new entries and pauses when hidden', async () => {
  const definition = makePresets()[0],
    saved = { id: 3, name: definition.name, revision: 1, definition }
  mocks.screens.mockResolvedValue([saved])
  mocks.universes.mockResolvedValue([
    { id: 'stored', label: 'Downloaded data', items: [{ symbol: 'ABC', exchange: 'NSE' }] },
  ])
  mocks.events.mockResolvedValue([])
  mocks.record.mockResolvedValue([])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    view = () => (
      <QueryClientProvider client={client}>
        <ScreenerWorkspace />
      </QueryClientProvider>
    )
  const { rerender } = render(view())
  await screen.findByRole('option', { name: definition.name })
  fireEvent.change(screen.getByLabelText('Saved screen'), { target: { value: '3' } })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Arm alerts' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Arm alerts' }))
  mocks.scan = { status: 'loading', rows: [] }
  rerender(view())
  const row: ScanRow = {
    symbol: 'ABC',
    exchange: 'NSE',
    time: 100,
    observedAt: Date.now() / 1000,
    state: 'match',
    fresh: true,
    direction: 'MATCH',
    source: 'stored',
    reason: 'Rule',
    values: {},
  }
  mocks.scan = { status: 'complete', rows: [row] }
  rerender(view())
  expect(mocks.record).not.toHaveBeenCalled()
  mocks.scan = { status: 'complete', rows: [{ ...row, state: 'no-match', time: 200 }] }
  rerender(view())
  mocks.scan = { status: 'complete', rows: [{ ...row, time: 300 }] }
  rerender(view())
  await waitFor(() => expect(mocks.record).toHaveBeenCalledTimes(1))
  expect(mocks.sound).not.toHaveBeenCalled()
  mocks.record.mockResolvedValue([{ symbol: 'ABC' }])
  mocks.scan = { status: 'complete', rows: [{ ...row, state: 'no-match', time: 400 }] }
  rerender(view())
  mocks.scan = { status: 'complete', rows: [{ ...row, time: 500 }] }
  rerender(view())
  await waitFor(() => expect(mocks.sound).toHaveBeenCalledTimes(1))
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
  fireEvent(document, new Event('visibilitychange'))
  expect(screen.getByText('Paused: page hidden')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Pause alerts' })).not.toBeInTheDocument()
})
it('does not restore a previous account screen after a slow save response', async () => {
  mocks.screens.mockResolvedValue([])
  mocks.universes.mockResolvedValue([])
  mocks.events.mockResolvedValue([])
  let finish: ((value: unknown) => void) | undefined
  mocks.save.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ScreenerWorkspace />
    </QueryClientProvider>
  )
  fireEvent.change(screen.getByLabelText('Screen name'), {
    target: { value: 'Old account screen' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save screen' }))
  const definition = mocks.save.mock.calls[0][0]
  const { useAuthStore } = await import('@/stores/authStore')
  const original = useAuthStore.getState().user
  const { act } = await import('@testing-library/react')
  act(() =>
    useAuthStore.setState({
      user: { username: 'another-owner', broker: null, isLoggedIn: true, loginTime: null },
    })
  )
  await act(async () => finish?.({ id: 99, name: definition.name, revision: 1, definition }))
  expect(screen.getByLabelText('Screen name')).not.toHaveValue('Old account screen')
  act(() => useAuthStore.setState({ user: original }))
})
it('refreshes an armed hourly screen before its source observation expires', async () => {
  const { act } = await import('@testing-library/react')
  const definition = { ...makePresets()[0], interval: '1h' as const },
    saved = { id: 11, name: definition.name, revision: 1, definition }
  mocks.screens.mockResolvedValue([saved])
  mocks.events.mockResolvedValue([])
  mocks.universes.mockResolvedValue([
    { id: 'stored', label: 'Downloaded data', items: [{ symbol: 'ABC', exchange: 'NSE' }] },
  ])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    view = () => (
      <QueryClientProvider client={client}>
        <ScreenerWorkspace />
      </QueryClientProvider>
    )
  const result = render(view())
  await screen.findByRole('option', { name: definition.name })
  fireEvent.change(screen.getByLabelText('Saved screen'), { target: { value: '11' } })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Arm alerts' })).toBeEnabled())
  vi.useFakeTimers()
  vi.setSystemTime(new Date(Date.now() + 1000))
  try {
    fireEvent.click(screen.getByRole('button', { name: 'Arm alerts' }))
    mocks.scan = { status: 'loading', rows: [] }
    result.rerender(view())
    const row: ScanRow = {
      symbol: 'ABC',
      exchange: 'NSE',
      time: Date.now() / 1000 - 60,
      observedAt: Date.now() / 1000,
      state: 'no-match',
      fresh: true,
      direction: 'MATCH',
      source: 'broker',
      reason: 'Rules',
      values: {},
    }
    mocks.scan = { status: 'complete', rows: [row] }
    result.rerender(view())
    await act(async () => {
      vi.advanceTimersByTime(65000)
    })
    expect(mocks.run).toHaveBeenCalledTimes(2)
    mocks.scan = { status: 'loading', rows: [] }
    result.rerender(view())
    mocks.scan = { status: 'complete', rows: [{ ...row, observedAt: Date.now() / 1000 }] }
    result.rerender(view())
    await act(async () => {
      vi.advanceTimersByTime(65000)
    })
    expect(screen.getByRole('button', { name: 'Pause alerts' })).toBeEnabled()
    expect(mocks.run).toHaveBeenCalledTimes(3)
  } finally {
    result.unmount()
    vi.useRealTimers()
  }
})
