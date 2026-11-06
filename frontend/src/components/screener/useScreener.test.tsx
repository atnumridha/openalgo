import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useScreener } from './useScreener'
import { makePresets } from './presets'
const api = vi.hoisted(() => ({ data: vi.fn(), poll: vi.fn(), cancel: vi.fn() }))
vi.mock('@/api/screener', () => ({ screenerApi: api }))
const instances: FakeWorker[] = []
class FakeWorker {
  onmessage: ((e: MessageEvent) => void) | null = null
  onerror: unknown
  postMessage = vi.fn()
  terminate = vi.fn()
  constructor() {
    instances.push(this)
  }
}
afterEach(() => {
  vi.unstubAllGlobals()
  instances.length = 0
  vi.clearAllMocks()
})
it('rejects replaced workers and clears old rows while the next source is loading', async () => {
  vi.stubGlobal('Worker', FakeWorker)
  api.data.mockResolvedValue({ status: 'complete', datasets: [] })
  const first = makePresets()[0],
    items = [{ symbol: 'ABC', exchange: 'NSE' }]
  const { result, rerender, unmount } = renderHook(
    ({ definition }) => useScreener({ definition, items, owner: 'u', mode: 'live', visible: true }),
    { initialProps: { definition: first } }
  )
  await waitFor(() => expect(instances[0]?.postMessage).toHaveBeenCalled())
  const worker = instances[0],
    revision = worker.postMessage.mock.calls[0][0].revision
  const row = { symbol: 'ABC', exchange: 'NSE', state: 'match', fresh: true, values: {} }
  act(() => worker.onmessage?.({ data: { revision, rows: [row] } } as MessageEvent))
  expect(result.current.rows).toHaveLength(1)
  rerender({ definition: { ...first, interval: '5m' } })
  expect(result.current.rows).toHaveLength(0)
  act(() => worker.onmessage?.({ data: { revision, rows: [row] } } as MessageEvent))
  expect(result.current.rows).toHaveLength(0)
  expect(worker.terminate).toHaveBeenCalled()
  unmount()
})
it('reports missing worker support without evaluating on the UI thread', async () => {
  vi.stubGlobal('Worker', undefined)
  const definition = makePresets()[0]
  const { result } = renderHook(() =>
    useScreener({ definition, items: [], owner: 'u', mode: 'live', visible: true })
  )
  await waitFor(() => expect(result.current.error).toMatch(/worker/i))
  expect(api.data).not.toHaveBeenCalled()
})
it('does not transfer an explicit broker refresh to another mode', async () => {
  vi.stubGlobal('Worker', FakeWorker)
  api.data.mockResolvedValue({ status: 'complete', datasets: [] })
  const definition = makePresets()[0],
    items = [{ symbol: 'ABC', exchange: 'NSE' }]
  const { result, rerender } = renderHook(
    ({ mode }: { mode: 'live' | 'analyzer' }) =>
      useScreener({ definition, items, owner: 'u', mode, visible: true }),
    { initialProps: { mode: 'live' as 'live' | 'analyzer' } }
  )
  await waitFor(() => expect(api.data).toHaveBeenCalledTimes(1))
  act(() => result.current.run(true))
  await waitFor(() => expect(api.data).toHaveBeenCalledTimes(2))
  expect(api.data.mock.calls[1][2]).toBe(true)
  rerender({ mode: 'analyzer' })
  await waitFor(() => expect(api.data).toHaveBeenCalledTimes(3))
  expect(api.data.mock.calls[2][2]).toBe(false)
  expect(api.data.mock.calls[2][3]).toBe('analyzer')
})
it('cancels a queued data job and rejects its late response', async () => {
  vi.stubGlobal('Worker', FakeWorker)
  api.cancel.mockResolvedValue(undefined)
  api.data.mockResolvedValue({ status: 'queued', datasets: [], job_id: 'job-1' })
  let reply: ((value: unknown) => void) | undefined
  api.poll.mockImplementation(
    () =>
      new Promise((resolve) => {
        reply = resolve
      })
  )
  const definition = makePresets()[0],
    items = [{ symbol: 'ABC', exchange: 'NSE' }]
  const { result } = renderHook(() =>
    useScreener({ definition, items, owner: 'u', mode: 'live', visible: true })
  )
  await waitFor(() => expect(api.poll).toHaveBeenCalled(), { timeout: 2000 })
  act(() => result.current.cancel())
  expect(result.current.status).toBe('cancelled')
  expect(api.cancel).toHaveBeenCalledWith('job-1')
  await act(async () => reply?.({ status: 'complete', datasets: [] }))
  expect(instances[0].postMessage).not.toHaveBeenCalled()
  expect(result.current.rows).toEqual([])
})
it('cancels a job whose creation response arrives after leaving the scan', async () => {
  vi.stubGlobal('Worker', FakeWorker)
  api.cancel.mockResolvedValue(undefined)
  let reply: ((value: unknown) => void) | undefined
  api.data.mockImplementation(
    () =>
      new Promise((resolve) => {
        reply = resolve
      })
  )
  const definition = makePresets()[0],
    items = [{ symbol: 'ABC', exchange: 'NSE' }]
  const { result } = renderHook(() =>
    useScreener({ definition, items, owner: 'u', mode: 'live', visible: true })
  )
  await waitFor(() => expect(api.data).toHaveBeenCalled())
  act(() => result.current.cancel())
  await act(async () => reply?.({ status: 'queued', datasets: [], job_id: 'late-job' }))
  expect(api.cancel).toHaveBeenCalledWith('late-job')
})
