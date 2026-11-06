import { useEffect, useRef, useState } from 'react'
import { deltaChartApi, type DeltaBackendAutomation } from '@/api/deltaChart'
import { backendProtectionAlerts, publishTradeAlert } from './deltaTradeAlerts'

export interface DeltaBackendAutoProps {
  automation: DeltaBackendAutomation
  account: string
  symbol: string
  valid: boolean
  observedAt?: number
  leverage: number
  balanceFraction: number | null
  manualQuantity: string
  onChanged: (automation: DeltaBackendAutomation) => void
}

type Uncertain = {
  account: string
  generation: string
  checkedAt: number | null
  observedAt?: number
}
function failure(error: unknown) {
  const item = error as {
    message?: string
    response?: { status?: number; data?: { message?: string } }
  }
  const status = item?.response?.status
  return {
    definite: typeof status === 'number' && status >= 400 && status < 500,
    message: item?.response?.data?.message || item?.message || 'Could not confirm the Auto change.',
  }
}
const describe = (value: unknown) => (typeof value === 'string' ? value : JSON.stringify(value))

export function DeltaBackendAuto({
  automation,
  account,
  symbol,
  valid,
  observedAt,
  leverage,
  balanceFraction,
  manualQuantity,
  onChanged,
}: DeltaBackendAutoProps) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [uncertain, setUncertain] = useState<Uncertain | null>(null)
  const busy = useRef(false)
  const mounted = useRef(true)
  const currentAccount = useRef(account)
  currentAccount.current = account
  const changed = useRef(onChanged)
  changed.current = onChanged
  useEffect(() => {
    mounted.current = true
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => {
      mounted.current = false
      window.clearInterval(timer)
    }
  }, [])
  useEffect(() => {
    if (
      uncertain &&
      automation.account === uncertain.account &&
      (automation.generation !== uncertain.generation ||
        (observedAt !== undefined &&
          uncertain.observedAt !== undefined &&
          observedAt > uncertain.observedAt) ||
        (automation.checked_at !== null &&
          automation.checked_at > (uncertain.checkedAt ?? -Infinity)))
    )
      setUncertain(null)
  }, [automation.account, automation.generation, automation.checked_at, observedAt, uncertain])

  useEffect(() => {
    for (const alert of backendProtectionAlerts(automation, account, symbol))
      publishTradeAlert(alert)
  }, [automation, account, symbol])

  const sameAccount = !!account && automation.account === account
  const protectionBlocked = sameAccount && automation.status === 'protection_blocked'
  const protectionPending = sameAccount && automation.status === 'protection_pending'
  const manual = Number(manualQuantity)
  const quantity =
    balanceFraction === null ? manual : Number.isInteger(manual) && manual > 0 ? manual : 1
  const settingsValid =
    Number.isInteger(leverage) &&
    leverage > 0 &&
    (balanceFraction === null
      ? Number.isInteger(quantity) && quantity > 0
      : [0.1, 0.25, 0.5, 0.75, 1].includes(balanceFraction))
  const waiting = uncertain?.account === account
  const disabled =
    pending || !!waiting || !sameAccount || (!automation.enabled && (!valid || !settingsValid))

  async function toggle() {
    if (disabled || busy.current) return
    busy.current = true
    setPending(true)
    setError('')
    const requestedAccount = account
    const enabled = !automation.enabled
    const targetSymbol = enabled ? symbol : automation.symbol
    try {
      const result = await deltaChartApi.automation({
        account,
        symbol: targetSymbol,
        enabled,
        ...(enabled
          ? { leverage, balance_fraction: balanceFraction, manual_quantity: quantity }
          : {}),
      })
      if (!mounted.current || currentAccount.current !== requestedAccount) return
      if (
        result.status !== 'confirmed' ||
        result.automation.owner !== 'backend' ||
        result.automation.account !== account ||
        result.automation.enabled !== enabled ||
        (enabled && result.automation.symbol !== targetSymbol)
      ) {
        throw new Error('Backend acknowledgement did not match this Auto change.')
      }
      changed.current(result.automation)
    } catch (cause) {
      if (!mounted.current || currentAccount.current !== requestedAccount) return
      const failed = failure(cause)
      setError(failed.message)
      if (!failed.definite)
        setUncertain({
          account,
          generation: automation.generation,
          checkedAt: automation.checked_at,
          observedAt,
        })
    } finally {
      busy.current = false
      if (mounted.current) setPending(false)
    }
  }
  const sourceTime = automation.context?.source_time
  const age = typeof sourceTime === 'number' ? Math.max(0, Math.floor(now - sourceTime)) : null
  const next =
    automation.next_check_at === null
      ? null
      : Math.max(0, Math.ceil(automation.next_check_at - now))
  return (
    <section
      aria-label="Backend Auto"
      className="space-y-2 rounded border border-border p-2 text-xs"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">Auto · backend</span>
        <button
          type="button"
          role="switch"
          aria-label="Auto"
          aria-checked={automation.enabled}
          disabled={disabled}
          onClick={() => void toggle()}
          className={`rounded border px-3 py-1 font-medium disabled:opacity-40 ${automation.enabled ? 'border-emerald-600 text-emerald-600' : 'border-border'}`}
        >
          {pending ? 'Confirming…' : automation.enabled ? 'On' : 'Off'}
        </button>
      </div>
      {automation.enabled && (
        <p>
          Running {automation.symbol} · {automation.leverage}× ·{' '}
          {automation.balance_fraction === null
            ? `${automation.manual_quantity} lots`
            : `${automation.balance_fraction * 100}% balance`}
        </p>
      )}
      {protectionBlocked ? (
        <p role="alert" className="font-medium text-rose-500">
          Protection blocked · {automation.message}
        </p>
      ) : (
        <output className={`block ${protectionPending ? 'text-amber-500' : ''}`}>
          {protectionPending ? 'Protection pending' : automation.status} · {automation.message}
        </output>
      )}
      <p className="text-muted-foreground">
        Backend continues while the chart is closed. Keep the Mac awake and the server and network
        running.
      </p>
      {!sameAccount && <p>Waiting for backend status for this account.</p>}
      <p>
        1m: {automation.context?.direction || 'waiting'} · 5m:{' '}
        {automation.context?.higher_direction || 'waiting'}
      </p>
      <p className="text-muted-foreground">
        Candle data: {age === null ? 'waiting' : `${age}s old`} ·{' '}
        {next === null
          ? 'Next check: waiting'
          : next === 0
            ? 'Next check due'
            : `Next check in ${next}s`}
      </p>
      {(error || waiting) && (
        <p role="alert">
          {error}
          {waiting
            ? ' Outcome unknown; waiting for fresh backend status before another change.'
            : ''}
        </p>
      )}
      <details className="border-t border-border pt-1">
        <summary className="cursor-pointer">Trend memory</summary>
        <div className="space-y-1 pt-1">
          {automation.context?.trend_summary && <p>{automation.context.trend_summary}</p>}
          {automation.context?.patterns?.length ? (
            automation.context.patterns.map((pattern, index) => (
              <p key={index}>{describe(pattern)}</p>
            ))
          ) : (
            <p>No pattern observations yet.</p>
          )}
          {automation.events.length ? (
            automation.events
              .slice(-20)
              .reverse()
              .map((event) => (
                <p key={event.id}>
                  {new Date(event.at * 1000).toLocaleTimeString()} · {event.kind} ·{' '}
                  {describe(event.details)}
                </p>
              ))
          ) : (
            <p>No events yet.</p>
          )}
        </div>
      </details>
    </section>
  )
}
