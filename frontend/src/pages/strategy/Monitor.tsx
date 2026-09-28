import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  ArrowLeft,
  Check,
  CircleHelp,
  Pause,
  Radio,
  RefreshCw,
  ShieldAlert,
  Square,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import {
  type AutomationMonitor,
  emergencyStopAutomation,
  getAutomationLogs,
  getAutomationMonitor,
  type LogStream,
  type MonitorStrategy,
  type StopResult,
} from '@/api/automation_monitor'
import { disableStrategyAutomation } from '@/api/strategy_module'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

const labels: Record<string, string> = {
  watching: 'Checking signals',
  in_trade: 'Run active',
  waiting_window: 'Waiting for entry window',
  outside_session: 'Outside entry hours',
  checking: 'Check in progress',
  stale: 'Checks stale',
  error: 'Check failed',
  close_failed: 'Closure failed',
  closing: 'Closing · not yet confirmed',
  disabled: 'Disabled',
  waiting_check: 'Waiting for check',
  scheduled: 'Scheduled',
  outside_setup: 'Setup window ended',
  signal_expired: 'Signal expired',
  unmanaged_run: 'Open run needs attention',
  unknown: 'Unknown automation state',
  link_error: 'Flow link problem',
  flow_inactive: 'Flow inactive',
  scheduler_unavailable: 'Scheduler unavailable',
  schedule_missing: 'Schedule missing',
  live_blocked: 'Live setup blocked',
}
const attention = new Set([
  'stale',
  'error',
  'close_failed',
  'link_error',
  'flow_inactive',
  'scheduler_unavailable',
  'schedule_missing',
  'data_unavailable',
  'risk_blocked',
  'unmanaged_run',
  'unknown',
  'live_blocked',
])
function needsAttention(row: MonitorStrategy) {
  return (
    attention.has(row.monitor_status) ||
    (row.activity_status !== undefined && attention.has(row.activity_status)) ||
    (row.mode === 'live' && row.automation_state === 'armed' && row.live_readiness?.blocked)
  )
}
function stamp(value: string | null | undefined) {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Unknown time'
    : new Intl.DateTimeFormat('en-IN', {
        timeZone: 'Asia/Kolkata',
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      }).format(date) + ' IST'
}
function pretty(value: string) {
  return value.replaceAll('_', ' ')
}
function Json({ value }: { value: unknown }) {
  return (
    <pre className="max-h-96 overflow-auto rounded-md bg-muted/50 p-3 text-xs leading-relaxed whitespace-pre-wrap break-all">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}
function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-sm font-medium tabular-nums">{children}</dd>
    </div>
  )
}

export default function Monitor() {
  const client = useQueryClient()
  const [selected, setSelected] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [mode, setMode] = useState('all')
  const [panel, setPanel] = useState<'decision' | 'logs'>('decision')
  const [confirm, setConfirm] = useState<'all' | number | null>(null)
  const [confirmation, setConfirmation] = useState('')
  const [result, setResult] = useState<StopResult | null>(null)
  const [controlError, setControlError] = useState<string | null>(null)
  const [clock, setClock] = useState(Date.now())
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const query = useQuery({
    queryKey: ['automation-monitor'],
    queryFn: getAutomationMonitor,
    refetchInterval: 3000,
    retry: 1,
  })
  const data = query.data
  const rows = data?.strategies ?? []
  const current = rows.find((r) => r.id === selected) ?? rows[0]
  const filtered = rows.filter(
    (r) =>
      (mode === 'all' || r.mode === mode) && r.name.toLowerCase().includes(search.toLowerCase())
  )
  const stale = query.isError || (query.dataUpdatedAt > 0 && clock - query.dataUpdatedAt > 12000)
  const stop = useMutation({
    mutationFn: async (target: 'all' | number): Promise<StopResult> => {
      if (target === 'all') return emergencyStopAutomation()
      const row = await disableStrategyAutomation(target)
      return {
        all_stopped: row.state === 'disabled' && !row.close_pending,
        items: [{ ...row, ok: row.outcome !== 'failed' }],
      }
    },
    onSuccess: (value) => {
      setResult(value)
      setConfirm(null)
      client.invalidateQueries({ queryKey: ['automation-monitor'] })
    },
    onError: (error: Error) => {
      setControlError(
        `Stop outcome is not confirmed: ${error.message}. Inspect current statuses and orders before retrying.`
      )
      setConfirm(null)
      client.invalidateQueries({ queryKey: ['automation-monitor'] })
    },
  })
  function ask(target: 'all' | number) {
    setConfirmation('')
    setControlError(null)
    setConfirm(target)
  }
  return (
    <div className="mx-auto max-w-[1600px] space-y-5 pb-10">
      <Link
        to="/strategy"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        Strategies
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-widest text-muted-foreground">
            <Radio className="size-3.5" />
            Operations
          </div>
          <h1 className="text-3xl font-semibold tracking-tight">Automation review</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            See what is being checked, why a trade is waiting, and what can happen next.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => query.refetch()} disabled={query.isFetching}>
            <RefreshCw className={cn('size-4', query.isFetching && 'animate-spin')} />
            Refresh
          </Button>
          <Button variant="destructive" onClick={() => ask('all')} disabled={stop.isPending}>
            <ShieldAlert className="size-4" />
            Emergency stop
          </Button>
        </div>
      </header>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border bg-card px-4 py-3 text-xs">
        <span
          className={cn(
            'inline-flex items-center gap-2 font-medium',
            stale ? 'text-destructive' : 'text-foreground'
          )}
        >
          <span
            className={cn(
              'size-2 rounded-full',
              stale ? 'bg-destructive' : data ? 'bg-emerald-500' : 'bg-muted-foreground'
            )}
          />
          {stale
            ? 'Monitoring unavailable · displayed evidence may be old'
            : data
              ? 'Receiving updates every 3 seconds'
              : 'Connecting to monitor…'}
        </span>
        <span>
          Received {stamp(query.dataUpdatedAt ? new Date(query.dataUpdatedAt).toISOString() : null)}
        </span>
        <span>
          Scheduler: <b>{data?.scheduler.status ?? 'unknown'}</b>
        </span>
      </div>
      {controlError && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm"
        >
          {controlError}
        </div>
      )}
      {result && (
        <output
          className={cn(
            'block rounded-lg border p-4 text-sm',
            result.all_stopped ? 'border-emerald-500/30' : 'border-amber-500/50 bg-amber-500/5'
          )}
        >
          <h2 className="font-semibold">
            {result.all_stopped ? 'All targeted automation stopped' : 'Closure needs attention'}
          </h2>
          <p className="mt-1 text-muted-foreground">
            {result.all_stopped
              ? 'The stop service confirmed closure for the targeted managed runs.'
              : 'Closing is not a confirmed fill. Check each result below and inspect orders; retry failed controls after reconciliation.'}
          </p>
          <ul className="mt-3 space-y-2">
            {result.items.map((r) => (
              <li key={r.strategy_id}>
                <b>{r.name}</b> · {pretty(r.state)}
                {r.close_pending ? ' · closure pending' : ''}
                {r.reason ? ` — ${r.reason}` : ''}
              </li>
            ))}
          </ul>
        </output>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          ['Signal monitors enabled', rows.filter((r) => r.automation_state === 'armed').length],
          ['Managed runs open', rows.reduce((n, r) => n + r.open_run_count, 0)],
          ['Need attention', rows.filter(needsAttention).length],
          [
            'Live / Sandbox',
            `${rows.filter((r) => r.mode === 'live').length} / ${rows.filter((r) => r.mode === 'sandbox').length}`,
          ],
        ].map(([label, value]) => (
          <div key={label} className="rounded-xl border bg-card p-4">
            <div className="text-xs text-muted-foreground">{label}</div>
            <div className="mt-2 text-2xl font-semibold tabular-nums">{data ? value : '—'}</div>
          </div>
        ))}
      </div>
      {query.isPending && (
        <div className="py-12 text-center text-muted-foreground">
          Loading saved strategies and execution evidence…
        </div>
      )}
      {data && rows.length === 0 && (
        <div className="rounded-xl border p-10 text-center">
          No saved strategies.{' '}
          <Link className="underline" to="/strategy">
            Install a strategy to begin.
          </Link>
        </div>
      )}
      {rows.length > 0 && (
        <div className="grid items-start gap-5 lg:grid-cols-[290px_minmax(0,1fr)] xl:grid-cols-[330px_minmax(0,1fr)]">
          <aside className="overflow-hidden rounded-xl border bg-card">
            <div className="space-y-2 border-b p-3">
              <Input
                aria-label="Find a strategy"
                placeholder="Find a strategy…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <select
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                aria-label="Execution mode"
                value={mode}
                onChange={(e) => setMode(e.target.value)}
              >
                <option value="all">All execution modes</option>
                <option value="sandbox">Sandbox only</option>
                <option value="live">Live only</option>
              </select>
            </div>
            <div className="divide-y">
              {filtered.map((row) => (
                <button
                  type="button"
                  key={row.id}
                  aria-label={`Inspect ${row.name}`}
                  aria-pressed={row.id === current?.id}
                  onClick={() => {
                    setSelected(row.id)
                    setPanel('decision')
                  }}
                  className={cn(
                    'w-full border-l-2 border-transparent px-4 py-4 text-left transition-colors hover:bg-muted/50',
                    current?.id === row.id && 'border-l-primary bg-muted/60'
                  )}
                >
                  <div className="mb-2 flex items-center justify-between gap-2 text-[11px] uppercase tracking-wider text-muted-foreground">
                    <span>
                      #{row.id} · {row.mode}
                    </span>
                    <span>
                      {row.automation_state === 'armed'
                        ? 'Monitoring enabled'
                        : pretty(row.automation_state)}
                    </span>
                  </div>
                  <div className="text-sm font-semibold leading-snug">{row.name}</div>
                  <div
                    className={cn(
                      'mt-2 flex items-center gap-1.5 text-xs',
                      needsAttention(row)
                        ? 'text-amber-600 dark:text-amber-400'
                        : 'text-muted-foreground'
                    )}
                  >
                    <Activity className="size-3.5" />
                    {labels[row.monitor_status] ?? pretty(row.monitor_status)}
                  </div>
                  {row.mode === 'live' && row.live_readiness?.blocked && (
                    <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                      {row.live_readiness.blocker_count} setup blockers
                    </p>
                  )}
                </button>
              ))}
            </div>
            {filtered.length === 0 && (
              <p className="p-5 text-sm text-muted-foreground">
                No strategies match these filters.
              </p>
            )}
          </aside>
          {current && (
            <section className="min-w-0 space-y-4">
              <div className="rounded-xl border bg-card p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="mb-2 flex gap-2">
                      <Badge variant={current.mode === 'live' ? 'destructive' : 'secondary'}>
                        {current.mode === 'live'
                          ? current.live_readiness?.blocked
                            ? 'LIVE · new entries blocked'
                            : 'LIVE · configured'
                          : 'SANDBOX · simulated orders'}
                      </Badge>
                      <Badge variant="outline">
                        {current.automation_state === 'armed'
                          ? 'Monitoring enabled'
                          : pretty(current.automation_state)}
                      </Badge>
                    </div>
                    <h2 className="text-xl font-semibold">{current.name}</h2>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={
                      stop.isPending ||
                      (!current.configuration.profile && current.configuration.kind !== 'signal') ||
                      (current.automation_state === 'disabled' &&
                        !current.open_run_count &&
                        !current.workflow_active)
                    }
                    onClick={() => ask(current.id)}
                  >
                    <Square className="size-3.5" />
                    Stop automation & close
                  </Button>
                </div>
                <p className="mt-4 border-l-2 border-primary pl-3 text-sm leading-relaxed">
                  {current.reason}
                </p>
                <dl className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                  <Fact label="Last check">{stamp(current.last_check_at)}</Fact>
                  <Fact label="Next scheduled check">{stamp(current.next_check_at)}</Fact>
                  <Fact label="Entry window">
                    {current.entry_time ?? 'Not set'} – {current.exit_time ?? 'Not set'} IST
                  </Fact>
                  <Fact label="Trading run">
                    {current.open_run_count
                      ? `${current.open_run_count} open · inspect fills`
                      : 'No open managed run'}
                  </Fact>
                </dl>
                {current.last_failure && (
                  <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm">
                    <b>Most recent failed attempt</b>
                    <div className="mt-1">{current.last_failure.message}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {stamp(current.last_failure.at)} · Historical evidence; a later successful
                      check does not erase this record.
                    </div>
                  </div>
                )}
              </div>
              {current.last_risk_rejection && (
                <details className="rounded-lg border border-amber-500/30 p-3 text-sm">
                  <summary className="cursor-pointer font-medium">
                    Latest entry rejection · {stamp(current.last_risk_rejection.at)}
                  </summary>
                  <p className="mt-2">{current.last_risk_rejection.message}</p>
                  <Json value={current.last_risk_rejection.details} />
                </details>
              )}
              <div className="flex flex-wrap gap-2 border-b pb-2">
                <Button
                  variant={panel === 'decision' ? 'secondary' : 'ghost'}
                  onClick={() => setPanel('decision')}
                >
                  Decision & technical detail
                </Button>
                <Button
                  variant={panel === 'logs' ? 'secondary' : 'ghost'}
                  onClick={() => setPanel('logs')}
                >
                  Activity & logs
                </Button>
                <Button variant="ghost" asChild>
                  <Link to={`/strategy/${current.id}`}>Open strategy</Link>
                </Button>
              </div>
              {panel === 'decision' ? (
                <Decision row={current} data={data!} clock={clock} disconnected={stale} />
              ) : (
                <Logs key={current.id} id={current.id} />
              )}
            </section>
          )}
        </div>
      )}
      <Dialog
        open={confirm !== null}
        onOpenChange={(open) => {
          if (!open && !stop.isPending) setConfirm(null)
        }}
      >
        <DialogContent showCloseButton={!stop.isPending}>
          <DialogHeader>
            <DialogTitle>
              {confirm === 'all'
                ? 'Emergency stop managed automation'
                : 'Stop automation and request closure'}
            </DialogTitle>
            <DialogDescription>
              Blocks new entries and requests closure of supported managed scalping and signal
              strategies. Pending exits remain visible until confirmed. Unused disabled drafts are
              left alone; unsupported legacy batch strategies are reported for manual handling.
              Unrelated manual broker positions are outside this control.
            </DialogDescription>
          </DialogHeader>
          {confirm === 'all' ? (
            <div className="space-y-2">
              <label htmlFor="stop-all" className="text-sm font-medium">
                Type STOP ALL
              </label>
              <Input
                id="stop-all"
                value={confirmation}
                onChange={(e) => setConfirmation(e.target.value)}
                autoComplete="off"
              />
            </div>
          ) : (
            <p className="text-sm font-medium">{rows.find((r) => r.id === confirm)?.name}</p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(null)} disabled={stop.isPending}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={stop.isPending || (confirm === 'all' && confirmation !== 'STOP ALL')}
              onClick={() => {
                if (confirm !== null) stop.mutate(confirm)
              }}
            >
              {stop.isPending
                ? 'Blocking entries and requesting exits…'
                : 'Block entries & request closure'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function Decision({
  row,
  data,
  clock,
  disconnected,
}: {
  row: MonitorStrategy
  data: AutomationMonitor
  clock: number
  disconnected: boolean
}) {
  const evaluation = row.evaluation,
    technical = evaluation?.technical
  const recorded = evaluation ? new Date(evaluation.recorded_at).getTime() : 0
  const old =
    disconnected ||
    !recorded ||
    clock - recorded > Math.max(95000, (row.interval_seconds ?? 60) * 2000 + 15000)
  const risk = data.risk?.[row.mode]
  const plan = row.entry_plan?.details?.context?.structure
  return (
    <div className="space-y-4">
      <div className="rounded-xl border bg-card p-5">
        <h3 className="font-semibold">When will it place a real-money order?</h3>
        <p className="mt-2 text-sm leading-relaxed">
          {row.mode !== 'live'
            ? 'Real-money orders will not trigger in Sandbox. An eligible signal can create a simulated order.'
            : row.live_readiness?.blocked
              ? 'New live entries are blocked. Every known setup issue is listed below; resolving one may leave others to complete.'
              : !row.live_enabled
                ? 'Live entry is blocked: this strategy has no live opt-in.'
                : !data.live_authorization.active
                  ? 'Live entry is blocked: session authorization is missing.'
                  : 'Live mode and session authorization are set. Signal, contract, risk checks and any required research qualification must still pass at submission.'}
        </p>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
          <Fact label="Saved execution mode">{row.mode}</Fact>
          <Fact label="Strategy live opt-in">{row.live_enabled ? 'Enabled' : 'Disabled'}</Fact>
          <Fact label="Live session authorization">
            {data.live_authorization.active
              ? `Granted until ${stamp(data.live_authorization.expires_at)}`
              : 'Not granted'}
          </Fact>
        </dl>
        {row.activity_reason && (
          <p className="mt-3 text-sm text-muted-foreground">{row.activity_reason}</p>
        )}
        {row.live_readiness && (
          <div className="mt-5">
            <h4 className="text-sm font-semibold">Live setup checklist</h4>
            <ul className="mt-3 divide-y rounded-lg border px-3">
              {row.live_readiness.checks.map((check) => (
                <li key={check.code} className="flex gap-3 py-3 text-sm">
                  <span
                    className={cn(
                      'mt-0.5 shrink-0',
                      check.status === 'passed'
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : check.status === 'blocked'
                          ? 'text-amber-600 dark:text-amber-400'
                          : 'text-muted-foreground'
                    )}
                  >
                    {check.status === 'passed' ? (
                      <Check className="size-4" aria-label="Passed" />
                    ) : check.status === 'blocked' ? (
                      <X className="size-4" aria-label="Blocked" />
                    ) : (
                      <CircleHelp className="size-4" aria-label="Checked at entry" />
                    )}
                  </span>
                  <div>
                    <p className="font-medium">{check.label}</p>
                    <p className="mt-1 text-muted-foreground">{check.message}</p>
                    {check.action_url && check.status === 'blocked' && (
                      <Link
                        to={check.action_url}
                        className="mt-1 inline-block underline"
                        aria-label={`Review ${check.label}`}
                      >
                        Review settings
                      </Link>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
        <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
          There is no guaranteed trigger time. The next scheduler check is not a promised trade. A
          fresh qualifying closed-candle signal must fit the strategy's entry and holding window,
          and pass duplicate-signal, cooldown, contract, liquidity, executable quote, cash, cost,
          portfolio and any required research-release checks. These checks are revalidated at entry;
          a signal alone is not permission to trade.
        </p>
      </div>
      <div className="rounded-xl border bg-card p-5">
        <div className="flex flex-wrap justify-between gap-2">
          <h3 className="font-semibold">Latest signal evaluation</h3>
          <Badge variant="outline">
            {old ? 'Historical / unavailable evidence' : 'Recent evaluation'}
          </Badge>
        </div>
        {!evaluation ? (
          <p className="mt-3 text-sm text-muted-foreground">
            No technical snapshot recorded yet. The next eligible scheduled check will capture it.
            See the execution log for checks blocked before signal evaluation.
          </p>
        ) : (
          <>
            <p className="mt-3 text-sm">{evaluation.reason}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Recorded {stamp(evaluation.recorded_at)} · stage: {pretty(evaluation.stage)}
              {evaluation.signal_age_seconds !== undefined
                ? ` · signal bar age at evaluation: ${Math.round(evaluation.signal_age_seconds)}s`
                : ''}
            </p>
            {old && (
              <p className="mt-3 text-sm text-amber-600 dark:text-amber-400">
                These values are from an earlier check. They do not confirm current entry
                eligibility.
              </p>
            )}
            {technical && !technical.data_ready && (
              <p className="mt-3 text-sm text-amber-600 dark:text-amber-400">
                Expected completed candle is missing. No current pattern can be confirmed.
              </p>
            )}
            {technical && (
              <>
                <p className="mt-4 text-xs text-muted-foreground">
                  Evaluated candle close: {stamp(technical.bar_at)} · Evaluator result:{' '}
                  {technical.direction || 'No qualifying direction'}
                </p>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  {['Both', 'CE', 'PE'].map((side) => {
                    const checks = technical.checks.filter((c) => c.side === side)
                    return (
                      checks.length > 0 && (
                        <div
                          key={side}
                          className={cn(
                            'rounded-lg border p-3',
                            side === 'Both' && 'md:col-span-2'
                          )}
                        >
                          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                            {side === 'Both'
                              ? 'Shared conditions'
                              : `${side} · buy ${side === 'CE' ? 'call' : 'put'}`}
                          </h4>
                          <ul className="space-y-3">
                            {checks.map((c, i) => (
                              <li key={`${c.label}-${i}`} className="flex gap-2 text-sm">
                                <span
                                  className={cn(
                                    'mt-0.5 shrink-0',
                                    c.passed === true
                                      ? 'text-emerald-600 dark:text-emerald-400'
                                      : c.passed === false
                                        ? 'text-muted-foreground'
                                        : 'text-amber-500'
                                  )}
                                >
                                  {c.passed === true ? (
                                    <Check aria-label="Passed" className="size-4" />
                                  ) : c.passed === false ? (
                                    <X aria-label="Not met" className="size-4" />
                                  ) : (
                                    <CircleHelp aria-label="Unknown" className="size-4" />
                                  )}
                                </span>
                                {c.label}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )
                    )
                  })}
                </div>
                <h4 className="mt-5 text-sm font-medium">Indicator and candle values</h4>
                <dl className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
                  {Object.entries(technical.metrics).map(([key, value]) => (
                    <div key={key} className="min-w-0 rounded-md bg-muted/50 p-3">
                      <dt className="break-words text-xs text-muted-foreground">{pretty(key)}</dt>
                      <dd className="mt-1 break-words font-mono text-sm tabular-nums">
                        {value === null ? 'Unavailable' : String(value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </>
            )}
            {evaluation.technical_error && (
              <p className="mt-3 text-sm text-amber-500">{evaluation.technical_error}</p>
            )}
            {!!evaluation.history?.length && (
              <div className="mt-5">
                <h4 className="mb-2 text-sm font-medium">History actually used</h4>
                <div className="space-y-2 text-xs text-muted-foreground">
                  {evaluation.history.map((h) => (
                    <div key={h.symbol + h.interval}>
                      {h.symbol} · {h.interval} · {h.candles} completed candles · last{' '}
                      {stamp(h.last_bar_at)}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
      {plan && (
        <div className="rounded-xl border bg-card p-5">
          <h3 className="font-semibold">Recorded option entry plan</h3>
          <p className="mt-2 text-xs text-muted-foreground">
            Recorded {stamp(row.entry_plan?.at ?? null)}. Not an admission or a fill. Funding,
            costs, quote freshness and risk checks must still pass. This may describe an older
            signal.
          </p>
          <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
            <Fact label="Option contract">{plan.symbol}</Fact>
            <Fact label="Quoted entry premium">₹{plan.entry_price}</Fact>
            <Fact label="Absolute initial stop">₹{plan.stop_price}</Fact>
            <Fact label="Planned loss before fees and slippage">₹{plan.planned_gross_loss}</Fact>
          </dl>
          <p className="mt-4 text-sm">
            {plan.objective_r}R planning objective · no hard profit ceiling. The governor reserves
            against the executable entry cap and original stop; actual fills and returns may differ.
          </p>
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer">Option candles and complete plan</summary>
            <Json value={row.entry_plan?.details} />
          </details>
        </div>
      )}
      <details className="rounded-xl border bg-card p-5" open>
        <summary className="cursor-pointer font-semibold">Exact implemented entry rules</summary>
        <ol className="mt-4 list-decimal space-y-3 pl-5 text-sm leading-relaxed">
          {row.rules.map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ol>
        <p className="mt-3 text-xs text-muted-foreground">
          The final pattern result comes from the trading evaluator. Component values explain that
          recorded check; they do not predict the next candle.
        </p>
      </details>
      <div className="rounded-xl border bg-card p-5">
        <h3 className="font-semibold">Risk, capital and position protection</h3>
        {risk?.available ? (
          <>
            <dl className="mt-4 grid gap-4 sm:grid-cols-3">
              <Fact label="Saved allocation">₹{risk.capital?.toLocaleString('en-IN')}</Fact>
              <Fact
                label={
                  risk.policy_version === 'fixed-300-v3'
                    ? 'Planned price-stop limit (before charges)'
                    : 'Current per-trade risk cap'
                }
              >
                ₹{String(risk.ledger?.per_trade_limit ?? 'Unknown')}
              </Fact>
              <Fact label="Daily risk remaining">
                ₹{String(risk.ledger?.daily_remaining ?? 'Unknown')}
              </Fact>
              <Fact label="Consecutive losses">
                {String(risk.ledger?.consecutive_losses ?? 'Unknown')} / 3
              </Fact>
              <Fact label="Risk policy">{risk.policy_version}</Fact>
              <Fact label="Cost schedule">
                {risk.costs_configured ? 'Configured · date coverage checked at entry' : 'Missing'}
              </Fact>
            </dl>
            {(risk.pause_reason || risk.daily_stop_reason) && (
              <p className="mt-3 text-sm text-amber-600">
                {risk.pause_reason || risk.daily_stop_reason}
              </p>
            )}
            <details className="mt-4">
              <summary className="cursor-pointer text-sm">Complete saved risk ledger</summary>
              <Json value={risk} />
            </details>
          </>
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">
            {risk?.reason ?? 'Risk evidence unavailable. Entry eligibility is unknown.'}
          </p>
        )}
        <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
          New managed scalp entries place the stop one tick below the lowest low of three completed
          one-minute option candles. The stop stays fixed through a fill and only moves upward as
          profit protection is earned. The system rejects a whole lot that does not fit the account
          risk limit. Profit protection starts at ₹300 gross profit, locks at least ₹100, then
          trails with up to ₹300 planned giveback. Costs and slippage affect the realised result;
          the order and fill logs are authoritative.
        </p>
        {row.checkpoint ? (
          <details className="mt-4" open>
            <summary className="cursor-pointer text-sm font-medium">
              Latest position checkpoint · P&amp;L, stops and legs
            </summary>
            <Json value={row.checkpoint} />
          </details>
        ) : (
          <p className="mt-3 text-xs text-muted-foreground">No open-run checkpoint available.</p>
        )}
      </div>
      <details className="rounded-xl border bg-card p-5">
        <summary className="cursor-pointer font-semibold">
          Configuration, Flow and run evidence
        </summary>
        <div className="mt-3 flex gap-4 text-sm">
          <Link className="underline" to={`/strategy/${row.id}`}>
            Strategy configuration
          </Link>
          {row.workflow_id && (
            <Link className="underline" to={`/flow/${row.workflow_id}`}>
              Linked Flow #{row.workflow_id}
            </Link>
          )}
        </div>
        <Json
          value={{
            configuration: row.configuration,
            flow: {
              id: row.workflow_id,
              active: row.workflow_active,
              schedule: row.schedule_status,
              interval_seconds: row.interval_seconds,
            },
            automation_state: row.automation_state,
            run_status: row.run_status,
            webhook_locked: row.webhook_locked,
            open_runs: row.open_runs,
          }}
        />
      </details>
    </div>
  )
}

function Logs({ id }: { id: number }) {
  const [stream, setStream] = useState<LogStream>('executions'),
    [paused, setPaused] = useState(false),
    [search, setSearch] = useState(''),
    [errorsOnly, setErrorsOnly] = useState(false)
  const query = useInfiniteQuery({
    queryKey: ['automation-logs', id, stream],
    queryFn: ({ pageParam }) => getAutomationLogs(id, stream, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    refetchInterval: (q) => (paused || (q.state.data?.pages.length ?? 0) > 1 ? false : 3000),
    retry: 1,
  })
  const pages = query.data?.pages ?? []
  const records = pages
    .flatMap((p) => p.items)
    .filter(
      (r) =>
        (!errorsOnly ||
          ['failed', 'error', 'critical', 'rejected'].includes(r.status.toLowerCase())) &&
        `${r.message} ${JSON.stringify(r.details)}`.toLowerCase().includes(search.toLowerCase())
    )
  return (
    <div className="rounded-xl border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-semibold">Complete retained history</h3>
        <Button size="sm" variant="outline" onClick={() => setPaused(!paused)}>
          <Pause className="size-3.5" />
          {paused ? 'Resume log updates' : 'Pause log updates'}
        </Button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Full stored records, newest first. Credentials are redacted. Search and error filter apply
        to loaded pages. Opening older pages pauses automatic log updates.
      </p>
      <div className="my-4 flex flex-wrap gap-2">
        <select
          aria-label="Log stream"
          className="rounded-md border bg-background px-3 py-2 text-sm"
          value={stream}
          onChange={(e) => setStream(e.target.value as LogStream)}
        >
          <option value="executions">Flow executions</option>
          <option value="events">Strategy events</option>
          <option value="orders">Orders & fills</option>
        </select>
        <Input
          aria-label="Search loaded logs"
          placeholder="Search loaded logs…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="min-w-40 flex-1"
        />
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={errorsOnly}
            onChange={(e) => setErrorsOnly(e.target.checked)}
          />
          Errors only
        </label>
        <Button
          variant="outline"
          size="sm"
          onClick={() => query.refetch()}
          disabled={query.isFetching}
        >
          Refresh logs
        </Button>
      </div>
      {query.isError && (
        <p role="alert" className="mb-3 text-sm text-destructive">
          Log history unavailable. Displayed records may be old.
        </p>
      )}
      {pages[0]?.notice && <p className="mb-3 text-sm text-amber-500">{pages[0].notice}</p>}
      {query.isPending ? (
        <p className="py-8 text-sm text-muted-foreground">Loading logs…</p>
      ) : records.length === 0 ? (
        <p className="py-8 text-sm text-muted-foreground">
          No matching records in the loaded history.
        </p>
      ) : (
        <div className="divide-y rounded-lg border">
          {records.map((r) => (
            <details key={r.id} className="p-3">
              <summary className="cursor-pointer text-sm">
                <span className="mr-2 inline-block font-mono text-[11px] text-muted-foreground">
                  #{r.id} · {stamp(r.at)}
                </span>
                <Badge variant="outline" className="mr-2">
                  {r.status}
                </Badge>
                <span className="break-words">{r.message}</span>
              </summary>
              <div className="mt-3">
                <Json value={r} />
              </div>
            </details>
          ))}
        </div>
      )}
      <div className="mt-4 flex justify-between gap-3 text-xs text-muted-foreground">
        <span>
          {pages.reduce((n, p) => n + p.items.length, 0)} records loaded
          {paused || pages.length > 1 ? ' · auto-refresh paused' : ''}
        </span>
        {query.hasNextPage && (
          <Button
            variant="outline"
            size="sm"
            disabled={query.isFetchingNextPage}
            onClick={() => query.fetchNextPage()}
          >
            {query.isFetchingNextPage ? 'Loading…' : 'Load older records'}
          </Button>
        )}
      </div>
    </div>
  )
}
