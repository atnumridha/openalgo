import { useCallback, useEffect, useRef, useState } from 'react'
import { readScreenerDelta, screenerApi } from '@/api/screener'
import {
  instrumentKey,
  type Instrument,
  type ScanDataset,
  type ScanRow,
  type ScreenDefinition,
} from './model'
type Status = 'idle' | 'loading' | 'evaluating' | 'complete' | 'cancelled' | 'error'
interface ScanState {
  key: string
  rows: ScanRow[]
  datasets: ScanDataset[]
  status: Status
  error: string
  pending: number
  failed: number
  missing: number
}
const empty = (key: string): ScanState => ({
  key,
  rows: [],
  datasets: [],
  status: 'idle',
  error: '',
  pending: 0,
  failed: 0,
  missing: 0,
})
export function useScreener({
  definition,
  items,
  owner,
  mode,
  visible,
}: {
  definition: ScreenDefinition
  items: Instrument[]
  owner: string | undefined
  mode: 'live' | 'analyzer'
  visible: boolean
}) {
  const key = JSON.stringify([owner, mode, definition, items]),
    revision = useRef(0),
    stop = useRef<() => void>(() => {}),
    [request, setRequest] = useState({ id: 0, refresh: false, key: '' }),
    [state, setState] = useState<ScanState>(() => empty(key))
  const run = useCallback(
    (refresh = false) => setRequest((old) => ({ id: old.id + 1, refresh, key })),
    [key]
  )
  const cancel = useCallback(() => {
    stop.current()
    setState({ ...empty(key), status: 'cancelled' })
  }, [key])
  // biome-ignore lint/correctness/useExhaustiveDependencies: The serialized key includes owner, mode, definition and items; equivalent objects must not restart scans.
  useEffect(() => {
    let active = true,
      worker: Worker | undefined,
      timer: ReturnType<typeof setTimeout> | undefined
    const controller = new AbortController(),
      jobs = new Set<string>(),
      id = ++revision.current,
      refresh = request.key === key && request.refresh
    const valid = () => active && !controller.signal.aborted && revision.current === id
    const cleanup = () => {
      active = false
      controller.abort()
      if (timer) clearTimeout(timer)
      worker?.terminate()
      for (const job of jobs) void screenerApi.cancel(job).catch(() => {})
      jobs.clear()
    }
    stop.current = cleanup
    setState(empty(key))
    if (!visible) return cleanup
    if (typeof Worker === 'undefined') {
      setState({
        ...empty(key),
        status: 'error',
        error: 'This browser does not support Web Workers. Scanning is unavailable.',
      })
      return cleanup
    }
    if (items.length > (refresh ? 25 : 500)) {
      setState({
        ...empty(key),
        status: 'error',
        error: `Choose at most ${refresh ? 25 : 500} instruments for this scan.`,
      })
      return cleanup
    }
    timer = setTimeout(() => {
      void (async () => {
        const datasets: ScanDataset[] = []
        try {
          worker = new Worker(new URL('./scan.worker.ts', import.meta.url), { type: 'module' })
          worker.onmessage = (
            event: MessageEvent<{ revision: number; rows?: ScanRow[]; error?: string }>
          ) => {
            if (!valid() || event.data.revision !== id) return
            if (event.data.error) {
              setState({ ...empty(key), status: 'error', error: event.data.error })
              return
            }
            const rows = event.data.rows ?? []
            setState({
              key,
              rows,
              datasets,
              status: 'complete',
              error: '',
              pending: 0,
              failed: datasets.filter((d) => !!d.error).length,
              missing: rows.filter((r) => r.state === 'unavailable').length,
            })
          }
          worker.onerror = () => {
            if (valid())
              setState({
                ...empty(key),
                status: 'error',
                error: 'The scan worker failed. Run the scan again.',
              })
          }
          setState({ ...empty(key), status: 'loading', pending: items.length })
          const broker = items.filter((i) => i.exchange !== 'DELTA'),
            delta = items.filter((i) => i.exchange === 'DELTA')
          for (let offset = 0; offset < broker.length; offset += 25) {
            let reply = await screenerApi.data(
              broker.slice(offset, offset + 25),
              definition.interval,
              refresh,
              mode,
              controller.signal
            )
            if (!valid()) {
              if (reply.job_id) void screenerApi.cancel(reply.job_id).catch(() => {})
              return
            }
            if (reply.status !== 'complete' && !reply.job_id)
              throw new Error(
                'The data service returned an incomplete scan without a job identity.'
              )
            if (reply.job_id && reply.status !== 'complete') jobs.add(reply.job_id)
            while (valid() && reply.status !== 'complete' && reply.job_id) {
              const job = reply.job_id
              await new Promise<void>((resolve, reject) => {
                const abort = () => {
                    clearTimeout(pollTimer)
                    reject(new DOMException('Aborted', 'AbortError'))
                  },
                  pollTimer = setTimeout(() => {
                    controller.signal.removeEventListener('abort', abort)
                    resolve()
                  }, 750)
                controller.signal.addEventListener('abort', abort, { once: true })
              })
              reply = await screenerApi.poll(job, controller.signal)
              if (reply.status === 'complete') jobs.delete(job)
            }
            if (!valid()) return
            datasets.push(...reply.datasets)
            setState({
              ...empty(key),
              status: 'loading',
              datasets: [...datasets],
              pending: Math.max(0, items.length - datasets.length),
              failed: datasets.filter((d) => !!d.error).length,
            })
          }
          for (const item of delta) {
            datasets.push(await readScreenerDelta(item, definition.interval, controller.signal))
            if (!valid()) return
            setState({
              ...empty(key),
              status: 'loading',
              datasets: [...datasets],
              pending: Math.max(0, items.length - datasets.length),
              failed: datasets.filter((d) => !!d.error).length,
            })
          }
          if (!valid()) return
          // A missing backend row stays explicit missing coverage, never silently disappears.
          const received = new Set(datasets.map(instrumentKey))
          for (const item of items)
            if (!received.has(instrumentKey(item)))
              datasets.push({
                ...item,
                interval: definition.interval,
                source: 'Unavailable',
                observedAt: 0,
                candles: [],
                daily: [],
                error: 'No history returned for this instrument',
              })
          setState({ ...empty(key), status: 'evaluating', datasets, pending: 0 })
          worker.postMessage({ revision: id, definition, datasets, now: Date.now() / 1000 })
        } catch (error) {
          if (valid())
            setState({
              ...empty(key),
              status: 'error',
              error: error instanceof Error ? error.message : 'Scan failed',
            })
        }
      })()
    }, 200)
    return cleanup
  }, [key, request, visible]) // key includes owner, mode, rules, timeframe and exact source identities.
  return { ...(state.key === key ? state : empty(key)), run, cancel }
}
