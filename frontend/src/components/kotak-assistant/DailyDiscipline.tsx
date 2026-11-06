import { useEffect, useState } from 'react'
import type { DailyDisciplineState } from '@/api/kotakAssistant'
import { Button } from '@/components/ui/button'
import { money } from './model'
import { feeDay } from './feeEstimates'

const HIDDEN_DAY_CHANGED = 'kotak-daily-warning-hidden-change'
function savedHiddenDay(key: string) {
  try {
    return localStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

const REPEAT_OPTIONS = [30, 60, 120, 300, 600]
const intervalLabel = (seconds: number) =>
  seconds < 60 ? `${seconds} seconds` : `${seconds / 60} ${seconds === 60 ? 'minute' : 'minutes'}`
function savedInterval(key: string) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null')?.repeatSeconds
    return REPEAT_OPTIONS.includes(value) ? (value as number) : 120
  } catch {
    return 120
  }
}

export function DailyDiscipline({
  scope,
  discipline: d,
  bookTime,
  now,
  error,
  repeatInterval,
  onIntervalChange,
  brokerLabel = 'Kotak Neo',
}: {
  brokerLabel?: string
  scope: string
  discipline?: DailyDisciplineState
  bookTime?: number
  now: number
  error?: string | null
  repeatInterval?: number
  onIntervalChange?: (seconds: number) => void
}) {
  const [mountedAt] = useState(now)
  const storageKey = `kotak-daily-warning:${scope}`
  const preferenceKey = `kotak-warning-preferences:${scope}`
  const hiddenDayKey = `kotak-warning-hidden-day:${scope}`
  const today = feeDay(now * 1000)
  const [dismissedDay, setDismissedDay] = useState(() => ({
    key: hiddenDayKey,
    day: savedHiddenDay(hiddenDayKey),
  }))
  const hiddenForToday =
    (dismissedDay.key === hiddenDayKey ? dismissedDay.day : savedHiddenDay(hiddenDayKey)) === today
  useEffect(() => {
    const sync = () => setDismissedDay({ key: hiddenDayKey, day: savedHiddenDay(hiddenDayKey) })
    window.addEventListener('storage', sync)
    window.addEventListener(HIDDEN_DAY_CHANGED, sync)
    return () => {
      window.removeEventListener('storage', sync)
      window.removeEventListener(HIDDEN_DAY_CHANGED, sync)
    }
  }, [hiddenDayKey])
  const setHiddenDay = (day: string) => {
    setDismissedDay({ key: hiddenDayKey, day })
    try {
      if (day) localStorage.setItem(hiddenDayKey, day)
      else localStorage.removeItem(hiddenDayKey)
      window.dispatchEvent(new Event(HIDDEN_DAY_CHANGED))
    } catch {
      /* Keep this view's dismissal when browser storage is unavailable. */
    }
  }

  const [repeatSeconds, setRepeatSeconds] = useState(() => repeatInterval ?? savedInterval(preferenceKey))
  useEffect(() => {
    if (repeatInterval != null && Number.isInteger(repeatInterval) && repeatInterval >= 30 && repeatInterval <= 3600) setRepeatSeconds(repeatInterval)
  }, [repeatInterval])
  const [snooze, setSnooze] = useState<{ token: string; until: number }>(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null')
      return typeof saved?.token === 'string' && Number.isFinite(saved.until)
        ? saved
        : { token: '', until: 0 }
    } catch {
      return { token: '', until: 0 }
    }
  })
  const currentDay = d?.date === today
  const fresh =
    currentDay &&
    !error &&
    bookTime != null &&
    now - bookTime >= 0 &&
    now - bookTime <= 15 &&
    Number.isFinite(d.updated_at) &&
    now - d.updated_at >= 0 &&
    now - d.updated_at <= 15
  const used = currentDay ? d.entries : null
  const reasons: string[] = []
  if (currentDay && d.loss_reached)
    reasons.push(
      `₹1,000 daily loss limit reached · first observed net ${money(d.loss_reached_net ?? d.net)}`
    )
  if (currentDay && d.profit_reached)
    reasons.push(
      `₹2,000 profit milestone reached · first observed net ${money(d.profit_reached_net ?? d.net)}`
    )
  if (used != null && used >= 3)
    reasons.push(
      used > 3
        ? `${used} filled entries · ${used - 3} extra ${used - 3 === 1 ? 'entry' : 'entries'} beyond the daily maximum of 3`
        : 'All 3 daily entries used · no further live terminal buys'
    )
  const stop = d?.loss_reached || (used ?? 0) >= 3
  const canContinue = !!d?.profit_reached && !stop && d.count_verified !== false
  const remaining = Math.max(0, 3 - (used ?? 0))
  const headline = stop
    ? 'Stop trading for today'
    : canContinue
      ? 'Profit milestone reached'
      : 'Entry count needs verification'
  const guidance = canContinue
    ? `You may continue with ${remaining} ${remaining === 1 ? 'entry' : 'entries'} remaining; maximum 3 filled entries today.`
    : stop
      ? 'Take a break and protect your capital.'
      : 'Wait for the daily entry count to be verified before another buy.'
  const tone =
    d?.loss_reached || (used ?? 0) > 3
      ? 'loss'
      : stop
        ? 'limit'
        : d?.profit_reached
          ? 'profit'
          : 'limit'
  const token =
    reasons.length && currentDay
      ? `${d.date}:${!!d.loss_reached}:${!!d.profit_reached}:${used != null && used >= 3 ? used : ''}`
      : ''
  const visible = !hiddenForToday && fresh && !!token && (snooze.token !== token || now >= snooze.until)
  const anchor =
    snooze.token === token
      ? snooze.until
      : Math.max(
          d?.loss_reached_at || 0,
          d?.profit_reached_at || 0,
          d?.entry_limit_reached_at || 0,
          mountedAt
        )
  const round = Math.floor(Math.max(0, now - anchor) / repeatSeconds)
  const saveSnooze = (seconds: number) => {
    const next = { token, until: now + seconds }
    setSnooze(next)
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(next))
    } catch {
      /* Keep in-memory snooze. */
    }
  }
  const remind = () => saveSnooze(repeatSeconds)
  const changeInterval = (seconds: number) => {
    if (!REPEAT_OPTIONS.includes(seconds) && seconds !== repeatInterval) return
    setRepeatSeconds(seconds)
    onIntervalChange?.(seconds)
    try {
      localStorage.setItem(preferenceKey, JSON.stringify({ repeatSeconds: seconds }))
    } catch {
      /* Keep this session's preference. */
    }
    if (snooze.token === token && now < snooze.until) saveSnooze(seconds)
  }
  const goToExits = () => {
    remind()
    const heading = document.getElementById('kotak-open-trades')
    heading?.scrollIntoView?.({ block: 'start', behavior: 'auto' })
    heading?.focus({ preventScroll: true })
  }
  useEffect(() => {
    if (!visible) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (
        event.key !== 'Escape' ||
        event.defaultPrevented ||
        (event.target instanceof Element && event.target.closest('select,[role="combobox"]'))
      )
        return
      event.preventDefault()
      remind()
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [visible, token, now, repeatSeconds, storageKey])
  const intervalControl = (label: string) => (
    <label className="flex flex-wrap items-center gap-2 text-sm font-medium">
      {label}
      <select
        aria-label={label}
        value={repeatSeconds}
        onChange={(event) => changeInterval(Number(event.target.value))}
        className="h-11 rounded-md border bg-background px-3 text-foreground focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {[...new Set([...REPEAT_OPTIONS, ...(repeatInterval ? [repeatInterval] : [])])].sort((a, b) => a - b).map((seconds) => (
          <option key={seconds} value={seconds}>
            {intervalLabel(seconds)}
          </option>
        ))}
      </select>
    </label>
  )
  return (
    <>
      <section
        aria-label="Daily trading discipline"
        className="space-y-2 rounded-lg border bg-card p-3"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="font-semibold">Daily trading limits · {brokerLabel}</h3>
          <p className="text-xs text-muted-foreground">
            {fresh ? 'Live account · checked each second' : 'Waiting for fresh account data'}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          {intervalControl('Warning repeat interval')}
          {hiddenForToday ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">Warning hidden until midnight IST.</span>
              <Button className="min-h-11" size="sm" variant="outline" onClick={() => {
                setHiddenDay('')
                saveSnooze(0)
              }}>
                Show warning again
              </Button>
            </div>
          ) : (
            <span className="text-xs text-muted-foreground">
              Full-screen warning · exits remain available
            </span>
          )}
        </div>
        <dl className="grid grid-cols-2 gap-3 text-sm tabular-nums sm:grid-cols-4">
          <div>
            <dt className="text-xs text-muted-foreground">Filled entries</dt>
            <dd aria-label="Daily entry count" className="mt-1 text-lg font-bold">
              {used == null
                ? '— / 3'
                : `${d?.count_verified === false ? 'At least ' : ''}${used} / 3`}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Entries remaining</dt>
            <dd className="mt-1 text-lg font-bold">
              {used == null || d?.count_verified === false ? '—' : Math.max(0, 3 - used)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Estimated daily net</dt>
            <dd className="mt-1 text-lg font-bold">{fresh ? money(d?.net) : '—'}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Profit milestone / loss limit</dt>
            <dd className="mt-1 font-semibold">+₹2,000 / −₹1,000</dd>
          </div>
        </dl>
        {currentDay && reasons.length > 0 && (
          <p className="text-sm font-medium">
            {headline}. {canContinue ? guidance : ''}{' '}
            {used != null && used > 3
              ? `${used - 3} extra ${used - 3 === 1 ? 'entry' : 'entries'} detected.`
              : ''}
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          One filled BUY order = one entry, including additions and re-entries. Split fills count
          once; rejected and unfilled orders do not count. Resets each trading day in IST. {brokerLabel}
          app entries are monitored; external broker apps cannot be blocked here.
        </p>
        {currentDay && d.count_verified === false && (
          <p className="text-xs text-muted-foreground">
            Entry history is incomplete. New live terminal buys stay blocked until the daily count
            can be verified.
          </p>
        )}
        {currentDay && d.pnl_error && (
          <p className="text-xs text-muted-foreground">{d.pnl_error}</p>
        )}
      </section>
      {visible && (
        <aside
          role="alert"
          data-tone={tone}
          aria-label="Daily limit warning"
          className="pointer-events-none fixed inset-0 z-50 grid place-items-center p-4"
        >
          <div
            key={`${token}:${snooze.until}:${repeatSeconds}:${round}`}
            aria-hidden="true"
            className={`kotak-daily-flash pointer-events-none absolute inset-0 border-4 ${tone === 'profit' ? 'border-emerald-600 bg-emerald-500/15 text-emerald-600' : 'border-red-600 bg-red-500/15 text-red-600'}`}
          />
          <div
            className={`pointer-events-auto relative max-h-[85vh] w-full max-w-xl space-y-4 overflow-y-auto rounded-2xl border-2 bg-background p-5 shadow-2xl sm:p-7 ${tone === 'profit' ? 'border-emerald-600 text-emerald-800 dark:text-emerald-300' : 'border-red-600 text-red-800 dark:text-red-300'}`}
          >
            <h3 className="text-2xl font-bold">{headline}</h3>
            <ul className="space-y-2 text-sm sm:text-base">
              {reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            <p className="text-sm text-foreground">
              {guidance} P&L is estimated after charges. Existing positions can still be exited.
            </p>
            {intervalControl('Alert repeat interval')}
            <div className="flex flex-wrap gap-3">
              <Button className="min-h-11" variant="outline" onClick={remind}>
                Close warning
              </Button>
              <Button className="min-h-11" variant="outline" onClick={() => setHiddenDay(today)}>
                Hide for today
              </Button>
              <Button className="min-h-11" variant="secondary" onClick={goToExits}>
                Go to open trades
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Close warning repeats in {intervalLabel(repeatSeconds)}. Hide for today pauses warnings
              until midnight IST. Escape also closes this warning. No exit order is placed by this message.
            </p>
          </div>
        </aside>
      )}
    </>
  )
}
