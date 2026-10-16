import type {
  ExecutionReadiness,
  SetupDirection,
  SetupMode,
  SetupResult,
  SetupStrategy,
} from '@/api/kotakAssistant'
import { money } from './model'
import { setupForSelectedSide } from './setupChart'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

export interface SelectedSetupContract {
  symbol: string
  side: SetupDirection
  strike: number
  expiry: string
  quantity?: number
  entry?: number | null
  sl?: number | null
  target?: number | null
  source?: string
  reason?: string
  costs?: { netSL: number; netTarget: number; chargesSL: number; chargesTarget: number } | null
}

export interface SetupAssistantProps {
  selectedContract?: SelectedSetupContract | null
  setup?: SetupResult | null
  strategy: SetupStrategy
  mode: SetupMode
  onStrategyChange: (strategy: SetupStrategy) => void
  onModeChange: (mode: SetupMode) => void
  onUseSetup: (setup: SetupResult) => void
  now?: number
  replay?: boolean
  executionReadiness?: ExecutionReadiness[]
}
const price = (value?: number | null) =>
  value == null || !Number.isFinite(value)
    ? '—'
    : value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const time = (value?: number | null) =>
  value == null
    ? '—'
    : new Date(value * 1000).toLocaleTimeString('en-IN', {
        timeZone: 'Asia/Kolkata',
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
const title = (value: string) =>
  (
    ({
      waiting_reference: 'Waiting for swings',
      waiting_break: 'Waiting for reference break',
      waiting_signal: 'Waiting for signal candle',
      waiting_trigger: 'Watching trigger',
    }) as Record<string, string>
  )[value] || value.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())

export function SetupAssistant({
  setup: indexSetup,
  selectedContract,
  strategy,
  mode,
  onStrategyChange,
  onModeChange,
  onUseSetup,
  now = Date.now() / 1000,
  replay = false,
  executionReadiness = [],
}: SetupAssistantProps) {
  const opening = strategy === 'opening_reversal'
  const side = selectedContract?.side
  const setup = setupForSelectedSide(indexSetup, side)
  const mismatch = !!side && !!setup?.direction && side !== setup.direction
  const readOnly = replay || setup?.read_only
  const remaining = setup?.expires == null ? null : Math.max(0, Math.ceil(setup.expires - now))
  const expired = remaining === 0
  const usable =
    !!setup &&
    !!setup.direction &&
    !mismatch &&
    selectedContract !== null &&
    !readOnly &&
    !expired &&
    setup.eligible !== false &&
    ['ready', 'triggered'].includes(setup.stage)
  const steps = opening
    ? ['Reference swings', 'Reference crossed', 'Signal candle', 'Later price trigger']
    : [
        'Completed history',
        'Trend context',
        mode === 'early' ? 'First break' : 'Retest or sweep',
        'Entry zone',
      ]
  const progress =
    setup?.stage === 'ready' || setup?.stage === 'triggered'
      ? 4
      : setup?.stage === 'waiting_trigger'
        ? 3
        : setup?.stage === 'waiting_signal' || setup?.stage === 'waiting_pattern'
          ? 2
          : setup?.stage === 'waiting_break' || setup?.stage === 'waiting_trend'
            ? 1
            : 0
  const directions = setup?.directions ? Object.entries(setup.directions) : []
  const candle = setup?.signal_candle
  const directionLabel = !setup?.direction
    ? ''
    : setup.stage === 'triggered'
      ? `${setup.direction === 'CE' ? '↑ CE TRIGGERED · BUY CALL' : '↓ PE TRIGGERED · BUY PUT'}`
      : setup.stage === 'ready'
        ? `${setup.direction === 'CE' ? '↑ CE READY · BUY CALL' : '↓ PE READY · BUY PUT'}`
        : setup.stage === 'waiting_trigger'
          ? `Watching ${setup.direction} ${setup.direction === 'CE' ? 'above' : 'below'} ${price(setup.trigger)}`
          : `${setup.direction === 'CE' ? '↑ CE' : '↓ PE'} sequence`
  return (
    <Card className="gap-0 py-0" aria-label="Chart setup assistant">
      <CardContent className="max-h-[30rem] space-y-3 overflow-y-auto p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold">Chart setup assistant</h3>
          <span className="text-xs text-muted-foreground">
            {readOnly ? 'Read-only replay · no live eligibility' : 'Advisory · entry requires Buy'}
          </span>
        </div>
        <p className="text-xs text-muted-foreground">
          Index context ·{' '}
          {opening
            ? '1m signal candles · intrabar price trigger'
            : '5m trend context · 1m entry candles'}
        </p>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-xs font-medium">
            Strategy
            <select
              className="mt-1 h-9 w-full rounded-md border bg-background px-2"
              value={strategy}
              onChange={(event) => onStrategyChange(event.target.value as SetupStrategy)}
            >
              <option value="trend">Trend setup</option>
              <option value="opening_reversal">Opening swing reversal</option>
            </select>
          </label>
          <label className="text-xs font-medium">
            Signal mode
            <select
              className="mt-1 h-9 w-full rounded-md border bg-background px-2"
              value={opening ? 'literal' : mode}
              disabled={opening}
              onChange={(event) => onModeChange(event.target.value as SetupMode)}
            >
              {opening && <option value="literal">Literal reversal sequence</option>}
              <option value="confirmed">Confirmed</option>
              <option value="early">Early</option>
            </select>
          </label>
        </div>
        {selectedContract ? (
          <section
            aria-label="Selected strike plan"
            className="space-y-2 rounded-md border bg-background/40 p-3 text-xs tabular-nums"
          >
            <div className="flex flex-wrap items-center justify-between gap-1">
              <strong className="break-all">{selectedContract.symbol}</strong>
              <span className="text-muted-foreground">
                Selected strike {price(selectedContract.strike)} · {side} ·{' '}
                {selectedContract.expiry}
              </span>
            </div>
            <p className="text-muted-foreground">
              {selectedContract.source || 'Selected contract'}
              {selectedContract.quantity ? ` · ${selectedContract.quantity} units` : ''} · option
              premiums
            </p>
            <dl className="grid grid-cols-3 gap-2">
              {(
                [
                  ['Entry', selectedContract.entry],
                  ['Stop loss', selectedContract.sl],
                  ['Profit target', selectedContract.target],
                ] as const
              ).map(([label, value]) => (
                <div key={label}>
                  <dt className="text-muted-foreground">{label} ₹</dt>
                  <dd className="mt-1 text-sm font-semibold">
                    {value != null && value > 0 ? money(value) : '—'}
                  </dd>
                </div>
              ))}
            </dl>
            {selectedContract.costs ? (
              <p className="flex flex-wrap gap-x-4 gap-y-1">
                <span className="text-red-600 dark:text-red-400">
                  Net at SL {money(selectedContract.costs.netSL)}{' '}
                  <span className="text-muted-foreground">
                    (charges {money(selectedContract.costs.chargesSL)})
                  </span>
                </span>
                <span className="text-emerald-700 dark:text-emerald-400">
                  Net at target {money(selectedContract.costs.netTarget)}{' '}
                  <span className="text-muted-foreground">
                    (charges {money(selectedContract.costs.chargesTarget)})
                  </span>
                </span>
              </p>
            ) : null}
            {selectedContract.reason && (
              <p className="text-muted-foreground">{selectedContract.reason}</p>
            )}
            {mismatch && (
              <p className="font-medium text-amber-700 dark:text-amber-400">
                Selected {side}: index setup favours {setup?.direction}. No matching setup for this
                contract yet.
              </p>
            )}
          </section>
        ) : (
          <p className="text-xs text-muted-foreground">Select a strike to see its premium plan.</p>
        )}
        <ol className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4" aria-label="Setup sequence">
          {steps.map((step, index) => (
            <li
              key={step}
              className={`rounded border px-2 py-1.5 ${index < progress ? 'border-emerald-500/40 bg-emerald-500/10' : 'text-muted-foreground'}`}
              aria-current={index === progress ? 'step' : undefined}
            >
              {index < progress ? '✓' : index + 1} {step}
            </li>
          ))}
        </ol>
        {setup?.direction && (
          <p
            className={`text-sm font-semibold ${setup.direction === 'CE' ? 'text-emerald-500' : 'text-red-500'}`}
          >
            {directionLabel}
          </p>
        )}
        <div className="text-sm" aria-live="polite">
          <p className="font-medium">
            {setup?.stage === 'triggered' && expired
              ? 'Triggered · Entry window ended'
              : expired
                ? 'Setup expired'
                : setup
                  ? title(setup.stage)
                  : 'Waiting for chart data'}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {setup?.reason ||
              'Completed candles and observed prices will build the setup sequence.'}
          </p>
        </div>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs tabular-nums sm:grid-cols-4">
          <div>
            <dt className="text-muted-foreground">Index reference {setup?.reference?.kind}</dt>
            <dd className="mt-0.5 font-medium">{price(setup?.reference?.price)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Index trigger</dt>
            <dd className="mt-0.5 font-medium">{price(setup?.trigger)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Signal candle · IST</dt>
            <dd className="mt-0.5 font-medium">{time(candle?.time)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Time remaining</dt>
            <dd className="mt-0.5 font-medium">
              {remaining == null
                ? 'No signal frozen'
                : `${Math.floor(remaining / 60)}m ${remaining % 60}s`}
            </dd>
          </div>
        </dl>
        {candle && (
          <p className="text-xs tabular-nums text-muted-foreground">
            Index candle O {price(candle.open)} · H {price(candle.high)} · L {price(candle.low)} · C{' '}
            {price(candle.close)}
          </p>
        )}
        {setup?.entry_zone && (
          <p className="text-xs tabular-nums">
            Index entry zone {price(setup.entry_zone.lower)}–{price(setup.entry_zone.upper)} ·
            invalidation {price(setup.invalidation)} ·{' '}
            {setup.projected ? 'projected 2R target' : 'target'} {price(setup.index_target)}
          </p>
        )}
        {setup?.index_entry != null && (
          <p className="text-xs tabular-nums">
            {opening ? 'Triggered index price' : 'Frozen index entry'} {price(setup.index_entry)}
            {!opening && !setup.entry_zone && (
              <>
                {' '}
                · invalidation {price(setup.invalidation)} · target {price(setup.index_target)}
              </>
            )}
          </p>
        )}
        {directions.length > 0 && (
          <div className="grid gap-2 text-xs sm:grid-cols-2">
            {directions.map(
              ([side, result]) =>
                result && (
                  <div key={side} className="rounded border px-2 py-1.5">
                    <strong className={side === 'CE' ? 'text-emerald-500' : 'text-red-500'}>
                      {side === 'CE' ? '↑' : '↓'} {side}
                    </strong>{' '}
                    · {title(result.stage)}
                    <p className="mt-1 text-muted-foreground">{result.reason}</p>
                  </div>
                )
            )}
          </div>
        )}
        <p className="text-xs text-muted-foreground">
          These are index levels. Option strike identifies the contract; ticket entry, SL and target
          are option premiums in ₹.
        </p>
        <Button
          variant="secondary"
          className="w-full"
          disabled={!usable}
          onClick={() => {
            if (usable && setup) onUseSetup(setup)
          }}
        >
          Use setup
        </Button>
        <p className="text-xs text-muted-foreground">
          Use setup prepares your selected strike’s option ticket. Review its premium, quantity and
          risk, then click Buy to submit.
        </p>
        <details className="rounded-md border px-3 py-2 text-xs">
          <summary className="cursor-pointer font-medium">Evidence and assumptions</summary>
          <div className="mt-2 space-y-2 text-muted-foreground">
            <p>
              {opening
                ? 'Opening reversal uses confirmed 1m swings and a later observed price crossing the frozen signal-candle trigger. CE follows the inferred mirror of the PE sequence; the trigger need not cross back through the reference. No trend indicator gate is applied.'
                : `Trend ${mode} uses completed candles, trend context and available opposing room. Index levels describe chart structure; option volatility sets the premium stop.`}
            </p>
            {setup?.evidence?.length ? (
              <ul className="list-disc space-y-1 pl-4">
                {setup.evidence.map((item, index) => (
                  <li key={`${index}:${item}`}>{item}</li>
                ))}
              </ul>
            ) : (
              <p>No setup evidence available yet.</p>
            )}
            {setup?.numbered_swings?.length ? (
              <p className="tabular-nums">
                {setup.numbered_swings
                  .map(
                    (swing) =>
                      `${swing.kind === 'high' ? 'H' : 'L'}${swing.ordinal} ${price(swing.price)} (known ${time(swing.known_at)} IST)`
                  )
                  .join(' · ')}
              </p>
            ) : null}
            <p>
              Price source: {setup?.source || 'not reported'}. REST snapshots sample observed prices
              and do not represent every market tick.
            </p>
            {setup && (
              <p>
                Strategy {setup.strategy} · v{setup.version} · {setup.mode}
              </p>
            )}
          </div>
        </details>
        <div className="space-y-1 border-t pt-2 text-xs" aria-label="Execution readiness">
          <p className="font-medium">Account and order checks</p>
          {executionReadiness.length ? (
            <ul className="space-y-1 text-muted-foreground">
              {executionReadiness.map((item, index) => (
                <li key={index}>
                  {typeof item === 'string'
                    ? item
                    : [item.label || item.name, item.reason].filter(Boolean).join(' · ')}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted-foreground">
              Broker checks run on Buy. Chart readiness is assessed separately.
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
