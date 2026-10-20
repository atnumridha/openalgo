import { useEffect, useRef, useState } from 'react'
import { type MlLiveSnapshot, mlSignalsApi } from '@/api/mlSignals'

export const LIVE_POLL_MS = 1000

export interface MlLiveState {
  snapshot: MlLiveSnapshot | null
  /** Seconds the browser clock is ahead of the server's, from the last answer. */
  clockOffset: number
  /** True once a request has failed and none has succeeded since. */
  unreachable: boolean
}

/**
 * Poll the live ML signal about once a second while the tab is visible.
 *
 * The next request starts only after the previous one settles, so a slow
 * server is never sent a pile of overlapping requests.
 */
export function useMlLive(interval: string, symbol = 'BTCUSD', enabled = true): MlLiveState {
  const [state, setState] = useState<MlLiveState>({
    snapshot: null,
    clockOffset: 0,
    unreachable: false,
  })
  const intervalRef = useRef(interval)
  intervalRef.current = interval

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    setState((previous) =>
      previous.snapshot?.interval === interval ? previous : { ...previous, snapshot: null }
    )

    const schedule = (delay: number) => {
      if (!cancelled) timer = setTimeout(poll, delay)
    }

    async function poll() {
      if (document.visibilityState !== 'visible') {
        schedule(LIVE_POLL_MS)
        return
      }
      const started = Date.now()
      try {
        const snapshot = await mlSignalsApi.live(interval, symbol)
        if (cancelled || intervalRef.current !== interval) return
        setState({
          snapshot,
          clockOffset: Date.now() / 1000 - snapshot.server_time,
          unreachable: false,
        })
      } catch {
        if (!cancelled) setState((previous) => ({ ...previous, unreachable: true }))
      }
      schedule(Math.max(0, LIVE_POLL_MS - (Date.now() - started)))
    }

    const resume = () => {
      if (document.visibilityState !== 'visible' || cancelled) return
      if (timer) clearTimeout(timer)
      void poll()
    }

    void poll()
    document.addEventListener('visibilitychange', resume)
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
      document.removeEventListener('visibilitychange', resume)
    }
  }, [interval, symbol, enabled])

  return state
}

/** Re-render once a second so countdowns and ages tick between answers. */
export function useSecondClock(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}
