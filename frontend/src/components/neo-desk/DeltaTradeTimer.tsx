import { useEffect, useState } from 'react'

const DURATION = 30 * 60 * 1000
interface TimerState {
  version: 1
  remainingMs: number
  deadline: number | null
  lastEntryKey: string | null
  lastEntryStartedAt: number
}
const initialTimer = (): TimerState => ({
  version: 1,
  remainingMs: DURATION,
  deadline: null,
  lastEntryKey: null,
  lastEntryStartedAt: 0,
})
function restoreTimer(key: string): { timer: TimerState; warning: string } {
  let raw: string | null
  try {
    raw = sessionStorage.getItem(key)
  } catch {
    return {
      timer: initialTimer(),
      warning: 'Timer persistence unavailable; using this view only.',
    }
  }
  if (raw === null) return { timer: initialTimer(), warning: '' }
  try {
    const saved: unknown = JSON.parse(raw)
    if (!saved || typeof saved !== 'object') throw new Error('Invalid timer')
    const timer = saved as TimerState
    if (
      timer.version !== 1 ||
      !Number.isFinite(timer.remainingMs) ||
      timer.remainingMs < 0 ||
      timer.remainingMs > DURATION ||
      (timer.deadline !== null &&
        (!Number.isFinite(timer.deadline) || timer.deadline > Date.now() + DURATION + 1000))
    )
      throw new Error('Invalid timer')
    return {
      timer: {
        version: 1,
        remainingMs: timer.remainingMs,
        deadline: timer.deadline,
        lastEntryKey: typeof timer.lastEntryKey === 'string' ? timer.lastEntryKey : null,
        lastEntryStartedAt:
          Number.isFinite(timer.lastEntryStartedAt) && timer.lastEntryStartedAt > 0
            ? timer.lastEntryStartedAt
            : 0,
      },
      warning: '',
    }
  } catch {
    return { timer: initialTimer(), warning: 'Saved timer was invalid; reset to 30:00 paused.' }
  }
}
const controlClass = 'rounded border border-border px-2 py-1 text-xs disabled:opacity-40'
interface AutoStart {
  autoStartKey?: string | null
  startedAt?: number | null
}
function Countdown({ storageKey, autoStartKey, startedAt }: { storageKey: string } & AutoStart) {
  const [restored] = useState(() => restoreTimer(storageKey))
  const [timer, setTimer] = useState(restored.timer)
  const [warning, setWarning] = useState(restored.warning)
  const [now, setNow] = useState(Date.now())
  const remaining =
    timer.deadline === null
      ? timer.remainingMs
      : Math.max(0, Math.min(DURATION, timer.deadline - now))
  const seconds = Math.ceil(remaining / 1000)
  const running = timer.deadline !== null && remaining > 0
  useEffect(() => {
    if (
      !autoStartKey ||
      typeof startedAt !== 'number' ||
      !Number.isFinite(startedAt) ||
      startedAt <= 0 ||
      startedAt * 1000 > Date.now() + 1000
    )
      return
    setTimer((previous) => {
      if (previous.lastEntryKey === autoStartKey || startedAt < previous.lastEntryStartedAt)
        return previous
      return {
        version: 1,
        remainingMs: DURATION,
        deadline: startedAt * 1000 + DURATION,
        lastEntryKey: autoStartKey,
        lastEntryStartedAt: startedAt,
      }
    })
    setNow(Date.now())
  }, [autoStartKey, startedAt])
  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(timer))
    } catch {
      setWarning('Timer persistence unavailable; using this view only.')
    }
  }, [timer, storageKey])
  useEffect(() => {
    if (timer.deadline === null) return
    const tick = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(tick)
  }, [timer.deadline])
  useEffect(() => {
    if (timer.deadline !== null && remaining === 0)
      setTimer((previous) => ({ ...previous, remainingMs: 0, deadline: null }))
  }, [timer.deadline, remaining])
  return (
    <section
      aria-label="30-minute reminder timer"
      className="space-y-2 rounded border border-border p-2"
    >
      <div className="flex items-center justify-between gap-2">
        <span>30-minute timer</span>
        <output
          role="timer"
          aria-label="30-minute countdown"
          aria-live="off"
          className="font-mono text-base tabular-nums"
        >
          {String(Math.floor(seconds / 60)).padStart(2, '0')}:
          {String(seconds % 60).padStart(2, '0')}
        </output>
      </div>
      <div className="flex gap-2">
        <button
          className={controlClass}
          disabled={running || remaining === 0}
          onClick={() => {
            const start = Date.now()
            setNow(start)
            setTimer({ ...timer, remainingMs: remaining, deadline: start + remaining })
          }}
        >
          Start
        </button>
        <button
          className={controlClass}
          disabled={!running}
          onClick={() => {
            const paused = Date.now()
            setNow(paused)
            setTimer({
              ...timer,
              remainingMs: Math.max(0, (timer.deadline ?? paused) - paused),
              deadline: null,
            })
          }}
        >
          Pause
        </button>
        <button
          className={controlClass}
          onClick={() => {
            setNow(Date.now())
            setTimer({
              ...initialTimer(),
              lastEntryKey: timer.lastEntryKey,
              lastEntryStartedAt: timer.lastEntryStartedAt,
            })
          }}
        >
          Reset
        </button>
      </div>
      {remaining === 0 && <p role="status">Time&apos;s up</p>}
      <p className="text-muted-foreground">
        Auto-starts on entry · soft exit review near the scalper deadline
      </p>
      {warning && <p className="text-muted-foreground">{warning}</p>}
    </section>
  )
}
export function DeltaTradeTimer({
  account,
  symbol,
  autoStartKey,
  startedAt,
}: { account: string; symbol: string } & AutoStart) {
  const storageKey = `delta-chart:timer:v1:${encodeURIComponent(account)}:${encodeURIComponent(symbol)}`
  return (
    <Countdown
      key={storageKey}
      storageKey={storageKey}
      autoStartKey={autoStartKey}
      startedAt={startedAt}
    />
  )
}
