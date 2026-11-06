import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  kotakAssistantApi,
  type EntryDecisions,
  type EntryDecisionSignal,
  type Plan,
  type PivotOverlay,
  type SetupDirection,
} from '@/api/kotakAssistant'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { money, errorMessage } from './model'

interface Props {
  symbol: string
  side?: SetupDirection
  underlying: string
  lots: string
  onLotsChange: (value: string) => void
  onUse: (plan: Plan) => void
  now: number
  scope: string
  replay: boolean
  onPivotOverlay?: (value: PivotOverlay | null) => void
}
const number = (value?: number | null) =>
  value == null
    ? '—'
    : value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
type Strategy = 'breakout_retest' | 'daily_pivots' | 'daily_sweep'
const strategies: Array<{ key: Strategy; title: string }> = [
  { key: 'breakout_retest', title: 'Breakout + Retest' },
  { key: 'daily_pivots', title: 'Daily Pivots' },
  { key: 'daily_sweep', title: 'Daily Liquidity Sweep' },
]
type DecisionQuery = { data?: EntryDecisions; isError: boolean; error: unknown }

export function EntryDecisionAssistant(props: Props) {
  const [ratio, setRatio] = useState(2)
  const quantityValid =
    /^\d+$/.test(props.lots) && Number(props.lots) >= 1 && Number(props.lots) <= 100
  // All three columns use the same snapshot and selected-contract risk plan.
  const query = useQuery({
    queryKey: ['entry-decisions', props.scope, props.underlying, props.symbol, props.lots, ratio],
    queryFn: () =>
      kotakAssistantApi.entryDecisions({
        underlying: props.underlying,
        symbol: props.symbol,
        lots: Number(props.lots),
        ratio,
      }),
    enabled: !props.replay && quantityValid,
    refetchInterval: 1000,
    refetchIntervalInBackground: true,
    retry: false,
  })
  return (
    <Card className="gap-0 py-0" aria-label="Entry Decision Assistant">
      <CardContent className="space-y-3 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold">Entry Decision Assistant</h3>
            <p className="text-xs text-muted-foreground">
              Advisory only · no entry orders submitted
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <p className="max-w-full break-all text-sm font-medium">
              {props.symbol || 'Choose an option strike'}
            </p>
            <label className="text-xs">
              Lots
              <input
                aria-label="Decision plan lots"
                className="mt-1 block h-11 w-20 rounded-md border bg-background px-2 text-sm"
                type="number"
                min="1"
                max="100"
                step="1"
                value={props.lots}
                onChange={(e) => props.onLotsChange(e.target.value)}
              />
            </label>
            <label className="text-xs">
              Net target R:R
              <select
                aria-label="Decision net target ratio"
                className="mt-1 block h-11 rounded-md border bg-background px-2 text-sm"
                value={ratio}
                onChange={(e) => setRatio(Number(e.target.value))}
              >
                <option value={2}>1:2</option>
                <option value={3}>1:3</option>
              </select>
            </label>
          </div>
        </div>
        <div className="overflow-x-auto pb-1">
          <div
            role="group"
            aria-label="Entry strategy comparison"
            className="grid min-w-[1000px] grid-cols-3 items-stretch gap-3"
          >
            {strategies.map((strategy) => (
              <StrategyColumn
                key={strategy.key}
                {...props}
                strategy={strategy.key}
                title={strategy.title}
                query={query}
                onPivotOverlay={strategy.key === 'daily_pivots' ? props.onPivotOverlay : undefined}
              />
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function StrategyColumn({
  symbol,
  side,
  underlying,
  lots,
  onUse,
  now,
  replay,
  onPivotOverlay,
  strategy,
  title,
  query,
}: Props & { strategy: Strategy; title: string; query: DecisionQuery }) {
  const [pivotMode, setPivotMode] = useState<'pivot_rejection' | 'pivot_retest'>('pivot_retest')
  const isPivot = strategy === 'daily_pivots'
  const quantityValid = /^\d+$/.test(lots) && Number(lots) >= 1 && Number(lots) <= 100
  const data = query.data
  const current =
    !replay &&
    !query.isError &&
    quantityValid &&
    !!data &&
    now - data.generated_at <= 5 &&
    data.generated_at <= now + 3 &&
    data.symbol === symbol
  const sessionDate = new Date((now + 19800) * 1000).toISOString().slice(0, 10)
  // Daily levels are fixed context, independent of transient live quote freshness.
  const pivots =
    !replay && data?.pivots?.underlying === underlying && data.pivots.session_date === sessionDate
      ? data.pivots
      : null
  const overlayKey = JSON.stringify(isPivot ? pivots : null)
  useEffect(() => {
    onPivotOverlay?.(JSON.parse(overlayKey))
  }, [onPivotOverlay, overlayKey])
  const group = current
    ? data.candidates[isPivot ? pivotMode : (strategy as 'breakout_retest' | 'daily_sweep')]
    : undefined
  const signal: EntryDecisionSignal | undefined =
    side && group?.directions?.[side] ? group.directions[side] : group
  const computedPlan = current && data.plan_fresh ? data.plan : null
  // An over-budget plan still explains the calculated prices. It cannot be adopted.
  const plan =
    computedPlan &&
    'entry' in computedPlan &&
    [
      computedPlan.entry,
      computedPlan.sl,
      computedPlan.target,
      computedPlan.quantity,
      computedPlan.risk,
      computedPlan.reward,
      computedPlan.costs,
      computedPlan.net_rr,
    ].every((value) => typeof value === 'number' && Number.isFinite(value)) &&
    0 < computedPlan.sl &&
    computedPlan.sl < computedPlan.entry &&
    computedPlan.entry < computedPlan.target
      ? computedPlan
      : null
  const matches = !!side && signal?.direction === side && data?.side === side
  const ready =
    !!signal?.eligible &&
    ['ready', 'triggered'].includes(signal.stage) &&
    matches &&
    !!plan?.fits &&
    (signal.expires == null || signal.expires > now)
  const remaining = signal?.expires == null ? null : Math.max(0, Math.ceil(signal.expires - now))
  const label = ready
    ? `${side === 'CE' ? '↑ CE' : '↓ PE'} SETUP READY`
    : 'WAIT · entry checks incomplete'
  const reason = replay
    ? 'Read-only replay · live decision levels are disabled'
    : query.isError
      ? `Data unavailable: ${errorMessage(query.error)}. Wait for fresh quotes.`
      : !quantityValid
        ? 'Choose 1–100 whole lots'
        : !current
          ? 'Waiting for current market observations…'
          : !symbol
            ? 'Select a CE or PE strike to calculate its premium plan'
            : signal?.eligible && !plan
              ? data.plan_reason
              : !matches && signal?.direction
                ? `Setup favours ${signal.direction}; the selected contract is ${side}. Wait for a matching setup.`
                : signal?.reason || 'Wait for the setup sequence to form'
  return (
    <Card className="h-full min-w-0 gap-0 py-0" role="region" aria-label={`${title} setup`}>
      <CardContent className="space-y-3 p-3">
        <h4 className="font-semibold">{title}</h4>
        <p className="min-h-[60px] text-xs text-muted-foreground">
          {isPivot
            ? 'Traditional daily pivots · fixed from the previous completed session. A pivot touch or bias alone is not an entry.'
            : strategy === 'breakout_retest'
              ? '5m breakout → first retest within 3 candles → completed confirmation. Breakout alone is not entry.'
              : 'Previous daily high/low → fresh crossing → first completed red/green 1m candle → later strict trigger break.'}
        </p>
        <div
          className={`rounded-md border p-3 ${ready ? (side === 'CE' ? 'border-emerald-600 bg-emerald-50/40 dark:bg-emerald-950/30' : 'border-red-600 bg-red-50/40 dark:bg-red-950/30') : 'bg-muted/30'}`}
        >
          <p
            className={`font-semibold ${ready ? (side === 'CE' ? 'text-emerald-700 dark:text-emerald-400' : 'text-red-600 dark:text-red-400') : ''}`}
          >
            {label}
          </p>
          <p className="mt-1 text-sm">{reason}</p>
          {isPivot && signal?.pattern && (
            <p className="mt-1 text-xs">
              {signal.pattern} · {signal.reference?.name}
            </p>
          )}
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs tabular-nums">
            <span>
              Index reference <strong>{number(signal?.reference?.price)}</strong>
            </span>
            <span>
              Index trigger / confirmed entry <strong>{number(signal?.trigger)}</strong>
            </span>
            {isPivot && (
              <>
                <span>
                  Index invalidation <strong>{number(signal?.invalidation)}</strong>
                </span>
                <span>
                  Next index pivot <strong>{number(signal?.index_target)}</strong>
                </span>
              </>
            )}
            {remaining != null && (
              <span>
                Watch time <strong>{remaining}s</strong>
              </span>
            )}
          </div>
        </div>
        <div className="min-w-0">
          <p className="break-all text-sm font-medium">{symbol || 'Choose an option strike'}</p>
          <p className="text-xs text-muted-foreground">
            {plan
              ? `${plan.quantity} units · ${plan.source}`
              : 'Index trigger prices and option premiums are separate'}
          </p>
        </div>
        <dl className="grid grid-cols-3 gap-2 tabular-nums">
          {(
            [
              ['Entry premium', plan?.entry],
              ['Stop loss premium', plan?.sl],
              ['Target premium', plan?.target],
            ] as const
          ).map(([name, value]) => (
            <div key={name} className="rounded-md border p-3">
              <dt className="text-xs text-muted-foreground">{name} ₹</dt>
              <dd className="mt-1 text-base font-semibold">{value == null ? '—' : money(value)}</dd>
            </div>
          ))}
        </dl>
        {plan ? (
          <p className="flex flex-wrap gap-x-5 gap-y-1 text-xs tabular-nums">
            <span className="text-red-600 dark:text-red-400">Net at SL {money(-plan.risk)}</span>
            <span className="text-emerald-700 dark:text-emerald-400">
              Net at target {money(plan.reward)}
            </span>
            <span>Net R:R 1:{plan.net_rr.toFixed(2)}</span>
            <span>Entry + exit charges at target {money(plan.costs)}</span>
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">
            {current ? data.plan_reason : 'Premium plan unavailable until fresh data is received'}
          </p>
        )}
        {plan && !plan.fits && (
          <p
            role="status"
            className="rounded-md border border-amber-600/50 bg-amber-50/40 p-3 text-sm dark:bg-amber-950/30"
          >
            {plan.reason || data?.plan_reason}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button
            className="min-h-11"
            disabled={!ready}
            onClick={() => {
              if (ready && plan) onUse(plan)
            }}
          >
            Use setup · load ticket
          </Button>
          <p className="text-xs text-muted-foreground">
            Loads these prices only. Review your ticket before buying. Fresh ask is indicative; an
            actual fill can differ.
          </p>
        </div>
        {isPivot && (
          <div className="space-y-2">
            <label className="flex flex-wrap items-center gap-2 text-sm">
              Pivot entry pattern
              <select
                aria-label="Pivot entry pattern"
                className="h-11 rounded-md border bg-background px-2"
                value={pivotMode}
                onChange={(e) => setPivotMode(e.target.value as typeof pivotMode)}
              >
                <option value="pivot_rejection">Rejection + confirmation</option>
                <option value="pivot_retest">Breakout + retest</option>
              </select>
            </label>
            {pivots ? (
              <>
                <p className="text-xs text-muted-foreground">
                  For {pivots.session_date} · Previous session {pivots.reference_date} · H{' '}
                  {number(pivots.previous.high)} · L {number(pivots.previous.low)} · C{' '}
                  {number(pivots.previous.close)}
                </p>
                <div className="overflow-x-auto">
                  <table
                    aria-label="Previous-session Traditional daily pivots"
                    className="w-full text-center text-sm tabular-nums"
                  >
                    <thead>
                      <tr>
                        {(['S3', 'S2', 'S1', 'P', 'R1', 'R2', 'R3'] as const).map((k) => (
                          <th key={k} scope="col" className="p-2 font-medium">
                            {k}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        {(['S3', 'S2', 'S1', 'P', 'R1', 'R2', 'R3'] as const).map((k) => (
                          <td
                            key={k}
                            className={`p-2 ${k === 'P' ? 'font-semibold text-blue-700 dark:text-blue-400' : ''}`}
                          >
                            {number(pivots.levels[k])}
                          </td>
                        ))}
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p className="text-xs text-muted-foreground">
                  P, S1 and R1 are labelled on the index chart only when its single date matches{' '}
                  {pivots.session_date}. Broker daily values can differ from intraday candles.
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Previous completed daily H/L/C required; no substitute levels used.
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              App-defined research rules: completed 1m candles, confirmation within 3 candles, next
              pivot must offer the selected R:R. Separate pivot comparison: the 2R retest was
              positive in a small sample; rejection and 3R cases lost money. See Evidence and rules.
            </p>
          </div>
        )}
        <details className="text-xs text-muted-foreground">
          <summary className="min-h-11 cursor-pointer content-center">Evidence and rules</summary>
          <p>
            {(isPivot ? data?.pivot_evidence : data?.evidence) ||
              'NIFTY comparison: retest 2R had 11 resolved trades across 6 dates; daily sweep had 3. Neither is a proven live edge.'}
          </p>
          <p className="mt-2">
            Option SL uses 1.5 × completed 1m ATR14. Target covers the selected net reward/risk
            after configured brokerage, estimated taxes and exit slippage. Planned total-position
            risk is capped at ₹1,000 for these candidates. Gaps can exceed planned risk. Retest and
            triggered reversal entries expire after 1 minute. CE reversal is an inferred mirror.
            Pivot entries use completed 1m confirmation, and observed invalidation or insufficient
            remaining index room cancels readiness. REST snapshots can miss intervening moves.
          </p>
          {underlying !== 'NIFTY' && (
            <p className="mt-2">
              {underlying} did not have sufficient backtest coverage; these rules have no
              demonstrated result for this index.
            </p>
          )}
        </details>
      </CardContent>
    </Card>
  )
}
