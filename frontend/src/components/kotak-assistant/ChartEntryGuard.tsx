import type { DeskMode, Plan, Snapshot } from '@/api/kotakAssistant'
import { Badge } from '@/components/ui/badge'

const time = (epoch: number | null | undefined, seconds = false) =>
  epoch == null || !Number.isFinite(epoch)
    ? '—'
    : new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Asia/Kolkata',
        hour: '2-digit',
        minute: '2-digit',
        ...(seconds ? { second: '2-digit' as const } : {}),
        hour12: false,
      }).format(new Date(epoch * 1000))

export function ChartEntryGuard({
  desk,
  indexFresh,
  booksFresh,
  mode,
  selected,
  plan,
  now = Date.now() / 1000,
}: {
  desk?: Snapshot
  indexFresh: boolean
  booksFresh: boolean
  mode: DeskMode
  selected: string
  plan?: Plan | null
  now?: number
}) {
  const limits = desk?.day?.entry_limits
  const blocked = desk?.day?.halt
  const advisory = limits?.blocked_reason
  const checks = desk?.analysis.checks
  const candleFresh =
    !checks ||
    (checks.history === 'fresh' &&
      checks.one_closed_at != null &&
      now >= checks.one_closed_at &&
      now - checks.one_closed_at <= 65 &&
      checks.five_closed_at != null &&
      now >= checks.five_closed_at &&
      now - checks.five_closed_at <= 365 &&
      now >= checks.checked_at &&
      now - checks.checked_at <= 15)
  const pricesFresh = indexFresh && booksFresh && !desk?.error
  const fresh = pricesFresh && candleFresh
  const action = desk?.analysis.action
  const side = selected.endsWith('CE') ? 'CE' : selected.endsWith('PE') ? 'PE' : null
  const signalSide = action === 'CALL' ? 'CE' : action === 'PUT' ? 'PE' : null
  const matches = !!side && !!signalSide && side === signalSide
  const waiting = {
    waiting_history: 'Building history',
    stale_history: 'Candles stale',
    history_gap: 'Candle gap',
    waiting_trend: 'No clear trend',
    waiting_trigger: 'Waiting for trigger',
    no_target: 'No target level',
    low_reward: 'Below 1:2 reward/risk',
    conflict: 'Conflicting setups',
    confirmed: 'Setup paused',
  }
  const signal =
    !candleFresh && checks?.history === 'fresh'
      ? 'Candles stale'
      : !signalSide
        ? checks
          ? waiting[checks.state]
          : 'Waiting for setup'
        : side && !matches
          ? `Selected ${side} · signal ${signalSide}`
          : `${signalSide} confirmed`
  const limitsKnown = typeof limits?.entries === 'number' && typeof limits?.losses === 'number'
  const checked = fresh && matches && limitsKnown && plan?.fits
  const status = blocked
    ? 'NEW ENTRIES BLOCKED'
    : advisory
      ? 'CAUTION'
      : checked
        ? 'SETUP CHECKED'
        : 'WAIT'
  return (
    <section aria-label="Chart entry guard" className="space-y-2 border-t bg-muted/30 px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold">Entry guard</h3>
          <Badge variant={blocked ? 'destructive' : 'secondary'}>{status}</Badge>
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs font-medium tabular-nums">
          <span>
            Entries {limits?.entries ?? '—'} / {limits?.max_entries ?? 3}
          </span>
          <span>
            Losing trades {limits?.losses ?? '—'} / {limits?.max_losses ?? 2}
          </span>
        </div>
      </div>
      <dl className="grid gap-2 text-xs sm:grid-cols-3">
        <div>
          <dt className="text-muted-foreground">Data</dt>
          <dd className="mt-0.5 font-medium">
            {fresh
              ? 'Fresh'
              : pricesFresh && !candleFresh
                ? 'Prices live · candles delayed'
                : 'Stale / unavailable'}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Setup</dt>
          <dd className="mt-0.5 font-medium">{signal}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Net reward / risk</dt>
          <dd className="mt-0.5 font-medium">
            {plan ? `1:${plan.net_rr.toFixed(2)} · charges included` : 'Awaiting preview'}
          </dd>
        </div>
      </dl>
      {checks && (
        <div aria-label="Setup checks" className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <span>
            5m trend:{' '}
            <strong>
              {checks.trend === 'CALL'
                ? 'Uptrend'
                : checks.trend === 'PUT'
                  ? 'Downtrend'
                  : checks.trend === 'NEUTRAL'
                    ? 'Mixed'
                    : 'Unavailable'}
            </strong>
          </span>
          <span>
            1m trigger: <strong>{checks.pattern_confirmed ? 'Confirmed' : 'Waiting'}</strong>
          </span>
          <span>
            Target room:{' '}
            <strong>
              {!checks.target_available
                ? checks.trend === 'CALL'
                  ? 'No resistance above'
                  : checks.trend === 'PUT'
                    ? 'No support below'
                    : 'Unavailable'
                : checks.reward_risk == null
                  ? 'Awaiting trigger'
                  : `1:${checks.reward_risk.toFixed(2)}`}
            </strong>
          </span>
        </div>
      )}
      <p
        role="status"
        aria-atomic="true"
        className={`text-xs ${blocked ? 'text-destructive' : 'text-muted-foreground'}`}
      >
        {blocked
          ? `${blocked}. Exits and protective stops remain available.`
          : advisory
            ? `${advisory}. Guidance only; manual entry is your decision.`
            : !pricesFresh
              ? desk?.analysis.reason?.startsWith('Market closed')
                ? desk.analysis.reason
                : 'Waiting for fresh prices and account data'
              : !candleFresh
                ? checks?.history !== 'fresh'
                  ? desk?.analysis.reason || 'Waiting for completed candle history'
                  : 'Setup candle data is delayed; waiting for a new evaluation'
                : checked
                  ? 'Manual entry · setup checks passed; returns remain unproven.'
                  : !signalSide
                    ? desk?.analysis.reason || 'Waiting for completed-candle confirmation'
                    : 'Wait for a matching confirmed setup and valid broker preview.'}
      </p>
      {checks && (
        <p className="text-xs text-muted-foreground tabular-nums">
          Checked {time(checks.checked_at, true)} IST · 1m closed {time(checks.one_closed_at)} · 5m
          closed {time(checks.five_closed_at)}
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        Server limits · {mode === 'analyze' ? 'Paper validation' : 'Experimental signals'} · Manual
        entries
      </p>
    </section>
  )
}
