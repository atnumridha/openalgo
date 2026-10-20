import { useBrokerCurrencyFormatter, useBrokerPriceFormatter } from '@/hooks/useBrokerCurrencyFormatter'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  deltaProfitApi,
  type ProfitProtectionPlan,
  type ProtectionInputs,
} from '@/api/deltaProfitProtection'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { Position } from '@/types/trading'

function message(error: unknown) {
  return (
    (error as { response?: { data?: { message?: string } } })?.response?.data?.message ||
    'Protection could not be confirmed. Check broker orders and refresh the preview.'
  )
}
const countdown = (end: number, now: number) => {
  const seconds = Math.max(0, Math.ceil(end - now / 1000))
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

export function DeltaProfitProtection({
  positions,
  now,
  visible,
  scope,
  onPlans,
}: {
  positions: Position[]
  now: number
  visible: boolean
  scope: string
  onPlans: (plans: ProfitProtectionPlan[]) => void
}) {
  const price = useBrokerPriceFormatter('deltaexchange')
  const amount = useBrokerCurrencyFormatter('deltaexchange')
  const open = positions.filter((p) => Number(p.quantity) !== 0 && p.exchange === 'CRYPTO')
  const [selected, setSelected] = useState('')
  const symbol = open.some((p) => p.symbol === selected) ? selected : open[0]?.symbol || ''
  const [ratio, setRatio] = useState('3')
  const [initial, setInitial] = useState('')
  const [gap, setGap] = useState('')
  const [policy, setPolicy] = useState<'price' | 'net_usd'>('net_usd')
  const [arm, setArm] = useState('2')
  const [lock, setLock] = useState('1.5')
  const [cashGap, setCashGap] = useState('0.5')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState<{ key: string; plan: ProfitProtectionPlan } | null>(null)
  const config: ProtectionInputs = useMemo(
    () => ({
      symbol,
      mode: 'live',
      reward_multiple: Number(ratio),
      ...(initial ? { initial_stop: Number(initial) } : {}),
      trailing_mode: policy,
      ...(policy === 'net_usd'
        ? {
            profit_arm_usd: Number(arm),
            profit_lock_usd: Number(lock),
            profit_gap_usd: Number(cashGap),
          }
        : gap
          ? { gap: Number(gap) }
          : {}),
    }),
    [symbol, ratio, initial, gap, policy, arm, lock, cashGap]
  )
  const key = JSON.stringify(config)
  const currentPosition = open.find((p) => p.symbol === symbol)
  const preview =
    loaded?.key === key &&
    loaded.plan.quantity === Number(currentPosition?.quantity) &&
    loaded.plan.entry === Number(currentPosition?.average_price)
      ? loaded.plan
      : null
  const [statusData, setStatusData] = useState<Awaited<ReturnType<typeof deltaProfitApi.status>>>()
  const [statusError, setStatusError] = useState(false)
  const live = useRef(false)
  const inFlight = useRef(false)
  const refetch = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const data = await deltaProfitApi.status()
      if (live.current) {
        setStatusData(data)
        setStatusError(false)
      }
    } catch {
      if (live.current) setStatusError(true)
    } finally {
      inFlight.current = false
    }
  }, [])
  useEffect(() => {
    live.current = true
    setStatusData(undefined)
    void refetch()
    const timer = visible ? setInterval(() => void refetch(), 1000) : undefined
    return () => {
      live.current = false
      if (timer) clearInterval(timer)
    }
  }, [refetch, visible, scope])
  const status = { data: statusData, isError: statusError, refetch }
  useEffect(() => {
    onPlans(status.data?.plans || [])
  }, [status.data, onPlans])
  const plans = status.data?.plans || []
  const active = plans.find((p) => p.symbol === symbol && p.enabled)
  const heartbeatFresh =
    !!status.data &&
    now / 1000 - status.data.heartbeat >= -2 &&
    now / 1000 - status.data.heartbeat < 5 &&
    !status.isError
  const run = async (action: 'preview' | 'enable' | 'pause', pausedSymbol = symbol) => {
    setBusy(true)
    setError('')
    try {
      if (action === 'preview') setLoaded({ key, plan: await deltaProfitApi.preview(config) })
      if (action === 'enable' && preview) {
        await deltaProfitApi.enable({ ...config, preview_id: preview.preview_id })
        setLoaded(null)
      }
      if (action === 'pause') await deltaProfitApi.pause(pausedSymbol)
      if (action !== 'preview') await status.refetch()
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section
      aria-label="Delta automatic profit protection"
      className="space-y-3 rounded-xl border bg-card p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">Automatic profit protection · Delta</h2>
        <span className="text-xs text-muted-foreground">
          {heartbeatFresh
            ? 'Server monitor ready · 1-second snapshots'
            : 'Waiting for a fresh server heartbeat'}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        Tighten only, with a pullback gap. Adopt an existing reduce-only broker stop; it stays in
        place while the server monitors every second. Default: above US$2 net, lock at least
        US$1.50, then trail US$0.50 behind the highest net profit. Opening and ordinary closing
        fees, funding and one tick of exit slippage are reserved. The original 1:n target stays
        fixed. Small gaps, stale data or broker rejection can prevent the planned floor; actual
        fills can be worse.
      </p>
      {!active && (
        <p className="text-sm font-medium">
          {open.length
            ? 'Automatic trailing is not enabled for this position.'
            : 'No open Delta position to protect.'}
        </p>
      )}
      {open.length > 0 && (
        <div className="flex flex-wrap items-end gap-3">
          <label className="grid gap-1 text-sm">
            Position
            <select
              aria-label="Position to protect"
              value={symbol}
              onChange={(e) => {
                setSelected(e.target.value)
                setInitial('')
                setGap('')
                setLoaded(null)
              }}
              disabled={busy}
              className="h-10 rounded-md border bg-background px-2"
            >
              {open.map((p) => (
                <option key={p.symbol} value={p.symbol}>
                  {p.symbol} · {p.quantity} contracts
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            Reward / original risk
            <select
              aria-label="Protection reward multiple"
              value={ratio}
              onChange={(e) => setRatio(e.target.value)}
              disabled={busy || !!active}
              className="h-10 rounded-md border bg-background px-2"
            >
              {['1.5', '2', '3', '4', '5', '6'].map((r) => (
                <option key={r} value={r}>
                  1:{r}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            Original SL price · USD
            <Input
              aria-label="Original protection stop"
              type="number"
              className="w-40"
              placeholder="Use broker stop"
              value={initial}
              onChange={(e) => setInitial(e.target.value)}
              disabled={busy || !!active}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Trailing policy
            <select
              aria-label="Profit trailing policy"
              className="h-10 rounded-md border bg-background px-2"
              value={policy}
              onChange={(e) => setPolicy(e.target.value as 'price' | 'net_usd')}
              disabled={busy || !!active}
            >
              <option value="net_usd">Total net profit · USD</option>
              <option value="price">BTC price gap · USD points</option>
            </select>
          </label>
          {policy === 'net_usd' && (
            <>
              <label className="grid gap-1 text-sm">
                Activate above · net USD
                <Input
                  aria-label="Net profit activation USD"
                  type="number"
                  min="0.01"
                  step="0.01"
                  className="w-32"
                  value={arm}
                  onChange={(e) => setArm(e.target.value)}
                  disabled={busy || !!active}
                />
              </label>
              <label className="grid gap-1 text-sm">
                Minimum profit lock · net USD
                <Input
                  aria-label="Net profit lock USD"
                  type="number"
                  min="0.01"
                  step="0.01"
                  className="w-32"
                  value={lock}
                  onChange={(e) => setLock(e.target.value)}
                  disabled={busy || !!active}
                />
              </label>
              <label className="grid gap-1 text-sm">
                Gap behind peak · net USD
                <Input
                  aria-label="Net profit trailing gap USD"
                  type="number"
                  min="0.01"
                  step="0.01"
                  className="w-32"
                  value={cashGap}
                  onChange={(e) => setCashGap(e.target.value)}
                  disabled={busy || !!active}
                />
              </label>
            </>
          )}
          {policy === 'price' && (
            <label className="grid gap-1 text-sm">
              Trailing gap · USD points
              <Input
                aria-label="Profit protection gap"
                type="number"
                className="w-40"
                placeholder="Half original risk"
                value={gap}
                onChange={(e) => setGap(e.target.value)}
                disabled={busy || !!active}
              />
            </label>
          )}
          {!active && (
            <Button
              variant="outline"
              disabled={busy || !symbol}
              onClick={() => void run('preview')}
            >
              Preview protection
            </Button>
          )}
        </div>
      )}
      {preview && !active && (
        <div className="space-y-2 rounded-lg border p-3 text-sm">
          <p>
            {preview.side > 0 ? 'LONG' : 'SHORT'} · Entry {price(preview.entry)} · Broker SL{' '}
            {price(preview.stop)} · Target {price(preview.target)} · 1:
            {preview.reward_multiple}
            {preview.trailing_mode === 'net_usd'
              ? ` · Activate above ${amount(preview.profit_arm_usd!)} net · Lock at least ${amount(preview.profit_lock_usd!)} · Trail gap ${amount(preview.profit_gap_usd!)}`
              : ` · Price gap ${price(preview.gap)}`}
          </p>
          <p>
            {preview.eligible
              ? `Profitable timed-exit checks begin in ${countdown(preview.exit_at, now)}; fee window ends in ${countdown(preview.window_end, now)}.`
              : 'No eligible free-close window verified. Stop protection and target still apply.'}
          </p>
          <p>
            Live control: enabling can modify this broker stop and automatically close this
            position. Small profits may not cover fees, slippage and a valid price tick. Fills can
            exceed the planned stop or occur after the fee window.
          </p>
          <Button disabled={busy || !heartbeatFresh} onClick={() => void run('enable')}>
            Enable live profit protection
          </Button>
        </div>
      )}
      {plans.map((p) => (
        <div key={p.symbol} className="space-y-1 rounded-lg border p-3 text-sm">
          <p className="font-medium">
            {p.symbol} · {p.enabled ? p.state : 'Stopped'} · {p.message}
          </p>
          <p>
            Last confirmed SL {price(p.stop)} · Original 1:{p.reward_multiple} target{' '}
            {price(p.target)}
            {p.trailing_mode === 'net_usd'
              ? ` · Net-profit trailing ${p.profit_armed ? 'active' : 'waiting for activation'}`
              : ` · Price gap ${price(p.gap)}`}
          </p>
          {p.trailing_mode === 'net_usd' && (
            <p>
              Activation above {amount(p.profit_arm_usd!)} net · Minimum lock{' '}
              {amount(p.profit_lock_usd!)} · Gap {amount(p.profit_gap_usd!)} · Highest estimated net{' '}
              {amount(p.peak_net_usd ?? 0)} · Planned net floor {amount(p.protected_net_usd ?? 0)}
            </p>
          )}
          <p>
            {p.eligible
              ? `Fee window ${countdown(p.window_end, now)} · timed exit only while estimated net is positive`
              : 'Free-close eligibility unavailable'}{' '}
            ·{' '}
            {p.checked_at
              ? `last check ${Math.max(0, Math.floor(now / 1000 - p.checked_at))}s ago`
              : 'awaiting first check'}
          </p>
          {p.enabled && (
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => void run('pause', p.symbol)}
            >
              Pause automation · keep broker orders
            </Button>
          )}
        </div>
      ))}
      {(error || status.isError) && (
        <p role="alert" className="text-sm text-destructive">
          {error ||
            'Protection status is unavailable. Verify the broker stop; the page cannot confirm automatic monitoring.'}
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        Profitable fee-window exits begin one minute before the configured deadline (29 minutes for
        a 30-minute window). Existing broker profit targets remain active and may close before this
        1:n target. Opening fees still apply; fee waivers depend on your Delta offer settings and
        actual fills. Pausing keeps broker orders in place.
      </p>
    </section>
  )
}
