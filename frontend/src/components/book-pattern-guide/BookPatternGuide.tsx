import { useEffect, useId, useState } from 'react'
import {
  DEFAULT_BOOK_SETTINGS,
  bookOrdinaryEventVisible,
  type BookAlert,
  type BookContext,
  type BookGuideResult,
  type BookInstrument,
  type BookSettings,
} from './engine'
const price = (n: number | undefined) =>
  n == null || !Number.isFinite(n) ? '—' : n.toLocaleString('en-IN', { maximumFractionDigits: 6 })
const words = (s: string) =>
  s
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/ATR/g, ' ATR')
    .replace(/RR/g, ' R:R')
    .replace(/^./, (s) => s.toUpperCase())
const mainNumbers = [
  ['equity', 'Account equity'],
  ['riskPercent', 'Risk per plan (%)'],
  ['minRR', 'Minimum reward / risk'],
  ['targetR', 'Local fallback target (R)'],
  ['planExpiryBars', 'Plan expiry (completed candles)'],
  ['fixedCost', 'Fixed round-trip cost'],
  ['perUnitCost', 'Cost per quantity unit'],
  ['slippagePrice', 'Slippage (price units)'],
] as const
const toggles = [
  ['showPending', 'Show pending formations'],
  ['showNeutral', 'Show neutral observations'],
  ['showTrendLines', 'Show confirmed context trend lines'],
  ['fullHistory', 'Full retained history'],
  ['rsiFilter', 'RSI filter'],
  ['macdFilter', 'MACD filter'],
  ['volumeFilter', 'Volume filter'],
  ['strictRangeEngulfing', 'Require full-range engulfing'],
] as const
const numericUnits = [
  ['valuePerPriceUnit', 'Money per price unit'],
  ['conversionRate', 'Quote to account conversion'],
  ['quantityStep', 'Quantity step'],
  ['lotSize', 'Units per lot'],
] as const
export function BookPatternGuide({
  result,
  settings,
  context,
  instrument,
  onSettingsChange,
  onInstrumentChange,
}: {
  result: BookGuideResult | null
  settings: BookSettings
  context: BookContext | null
  instrument: Partial<BookInstrument>
  onSettingsChange: (change: Partial<BookSettings>) => void
  onInstrumentChange: (change: Partial<BookInstrument>) => void
}) {
  const id = useId(),
    p = result?.activePlan,
    terminal = result?.lastTerminalPlan
  const latest = result?.events
    .filter((e) => bookOrdinaryEventVisible(e, settings.showNeutral))
    .at(-1)
  const pending = settings.showPending
    ? result?.pendingEvents.filter((e) => bookOrdinaryEventVisible(e, settings.showNeutral)).at(-1)
    : undefined
  const event = result?.events.find((e) => e.id === p?.eventId) ?? latest ?? pending
  const fieldClass =
    'w-full rounded border bg-background px-2 py-1.5 text-xs focus-visible:outline focus-visible:outline-2'
  const numberField = (key: keyof BookSettings, label: string) => (
    <label key={key} className="block space-y-1">
      <span>{label}</span>
      <input
        className={fieldClass}
        type="number"
        min="0"
        step="any"
        value={settings[key] as number}
        onChange={(e) => onSettingsChange({ [key]: Number(e.target.value) })}
      />
    </label>
  )
  const [notices, setNotices] = useState<BookAlert[]>([])
  useEffect(() => {
    if (!result?.alerts.length) return
    setNotices((old) =>
      [...new Map([...old, ...result.alerts].map((a) => [a.id, a])).values()].slice(-20)
    )
  }, [result?.alerts])
  const size = p?.sizing
  return (
    <section
      aria-label="Book patterns and risk guide"
      className="mb-2 rounded border border-border bg-card text-xs"
    >
      <section aria-label="Book compact summary" className="space-y-1 px-2 py-2">
        <p
          className="truncate font-medium"
          title={p?.name ?? event?.name ?? 'Book patterns & risk'}
        >
          {p?.name ?? event?.name ?? 'Book patterns & risk'} ·{' '}
          {p ? `${p.side === 'long' ? 'Long' : 'Short'} · frozen` : 'WAIT'}
          {' · '}
          {result?.readiness === 'ready'
            ? 'Verified'
            : result?.readiness === 'last-session'
              ? 'Last-session references'
              : 'Data unavailable'}
        </p>
        <p className="truncate text-muted-foreground" title={result?.nextCondition}>
          Trend {result?.indicators.trend ?? 'unavailable'} · Next ·{' '}
          {result?.nextCondition ?? 'Wait for matching source history.'}
        </p>
        <section
          className="flex flex-wrap gap-x-3 tabular-nums"
          aria-label="Compact price references"
        >
          <span>Entry {price(p?.entry)}</span>
          <span>SL {price(p?.stop)}</span>
          <span>Target {price(p?.target)}</span>
          <span>RR {price(p?.rr)}R</span>
        </section>
        <p className="truncate text-muted-foreground" title={size?.unavailableReasons.join('; ')}>
          {size?.quantity != null
            ? `Quantity ${price(size.quantity)}${size.lots != null ? ` · ${price(size.lots)} lots` : ''}`
            : 'Sizing unavailable · open Details for inputs'}
        </p>
      </section>
      <details>
        <summary className="cursor-pointer border-t px-2 py-1 focus-visible:outline focus-visible:outline-2">
          Details
        </summary>
        <div className="space-y-2 border-t px-2 py-2">
          <p className="text-muted-foreground">
            {context?.symbol ?? 'Chart'} · {context ? `${context.intervalSeconds}s` : ''}
          </p>
          <dl className="space-y-1" aria-label="Current book pattern reading">
            <dt className="font-medium">Pattern</dt>
            <dd>
              {event?.name ?? p?.name ?? 'No confirmed pattern'}
              {event ? ` · ${event.status}` : ''}
            </dd>
            <dt className="font-medium">Direction</dt>
            <dd>
              {(p?.side ?? event?.side) === 'long'
                ? 'Bullish price expectation'
                : (p?.side ?? event?.side) === 'short'
                  ? 'Bearish price expectation'
                  : 'Neutral / wait for directional confirmation'}
            </dd>
            <dt className="font-medium">Expected</dt>
            <dd>{result?.explanation ?? 'Waiting for verified chart candles.'}</dd>
            <dt className="font-medium">Next condition</dt>
            <dd>{result?.nextCondition ?? 'Wait for matching source history.'}</dd>
            <dt className="font-medium">Invalidation</dt>
            <dd>
              {p
                ? `SL reference ${price(p.stop)} · ${p.stopMethod}`
                : event
                  ? `${event.stopMethod}: ${price(event.stopAnchor)} structural anchor; confirmation and buffer still required.`
                  : 'No active plan; a price trigger and valid stop are required.'}
            </dd>
          </dl>
          {!!result?.unavailableReasons.length && (
            <ul aria-label="Book data status" className="text-amber-700 dark:text-amber-400">
              {result.unavailableReasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          <p>
            Trend · {result?.indicators.trend ?? 'unavailable'} · {settings.maType.toUpperCase()}
            {settings.maFast} {price(result?.indicators.maFast)} / {settings.maSlow}{' '}
            {price(result?.indicators.maSlow)}
          </p>
          <ul aria-label="Book filter states" className="text-muted-foreground">
            {result?.filters.map((f) => (
              <li key={f.name}>
                {f.name.toUpperCase()} · {f.state} · {price(f.value)}
                {f.baseline != null ? ` / ${price(f.baseline)}` : ''}
              </li>
            ))}
          </ul>
          {event?.qualificationReason && <p>{event.qualificationReason}</p>}
          <details>
            <summary className="cursor-pointer py-1">Recent context observations</summary>
            <ul className="mt-1 space-y-1" aria-label="Book context observations">
              {result?.observations.slice(-10).map((o) => (
                <li key={o.id}>{o.text}</li>
              ))}
            </ul>
            <p className="text-muted-foreground">Context alone cannot start a plan.</p>
          </details>
          <output className="block" aria-live="polite" aria-label="Confirmed book observations">
            {notices.at(-1)?.text ?? 'No new confirmed alert.'}
          </output>
          {notices.length > 1 && (
            <details>
              <summary className="cursor-pointer py-1">Recent confirmed alerts</summary>
              <ul className="mt-1 space-y-1">
                {notices.slice(0, -1).map((a) => (
                  <li key={a.id}>{a.text}</li>
                ))}
              </ul>
            </details>
          )}
          {p && (
            <>
              <dl
                aria-label="Frozen book plan price references"
                className="grid grid-cols-2 gap-x-2 gap-y-1 tabular-nums"
              >
                <dt>Entry · white</dt>
                <dd className="text-right">{price(p.entry)}</dd>
                <dt>SL · red</dt>
                <dd className="text-right">{price(p.stop)}</dd>
                <dt>Target · green</dt>
                <dd className="text-right">{price(p.target)}</dd>
                <dt>Reward / risk</dt>
                <dd className="text-right">{price(p.rr)}R</dd>
                <dt>Price risk</dt>
                <dd className="text-right">{price(Math.abs(p.entry - p.stop))}</dd>
                <dt>Price reward</dt>
                <dd className="text-right">{price(Math.abs(p.target - p.entry))}</dd>
                {size?.estimatedRewardCash != null && (
                  <>
                    <dt>Estimated reward cash</dt>
                    <dd className="text-right">
                      {price(size.estimatedRewardCash)} {instrument.accountCurrency}
                    </dd>
                  </>
                )}
              </dl>
              <p>
                {p.targetMethod === 'measured'
                  ? 'Measured objective'
                  : p.targetMethod === 'support-resistance'
                    ? 'Confirmed support / resistance target'
                    : 'Local R target · planning constraint'}{' '}
                · {p.stopMethod}
              </p>
              {p.notes.map((n) => (
                <p className="text-muted-foreground" key={n}>
                  {n}
                </p>
              ))}
              <p className="text-muted-foreground">
                Frozen until a closed-candle SL/target reference touch or expiry. References
                describe prices, not fills.
              </p>
            </>
          )}
          {result?.provisional && (
            <p className="text-muted-foreground">
              Forming · {price(result.provisional.price)} · SL distance{' '}
              {price(result.provisional.distanceToStop)} · target distance{' '}
              {price(result.provisional.distanceToTarget)}. Provisional only.
            </p>
          )}
          {terminal && (
            <p>
              Previous plan · {terminal.name} · {terminal.status.replaceAll('-', ' ')}
              {terminal.status === 'ambiguous' ? ' · touch order unknown' : ''}
            </p>
          )}
          {!!result?.alternatives.length && (
            <p>
              Later evidence · {result.alternatives.map((e) => `${e.name} (${e.side})`).join(', ')}.
              The active plan stays frozen.
            </p>
          )}
          <p>
            {size?.quantity != null
              ? `Quantity ${price(size.quantity)}${size.lots != null ? ` · lots ${price(size.lots)}` : ''} · estimated risk ${price(size.estimatedRiskCash)} ${instrument.accountCurrency ?? ''}`
              : 'Capital and validated instrument units are required for monetary sizing; price references remain available.'}
          </p>
          {size?.unavailableReasons.map((reason) => (
            <p className="text-muted-foreground" key={reason}>
              {reason}
            </p>
          ))}
          <p className="text-muted-foreground">
            Margin, affordability and portfolio exposure have not been established.
          </p>
          <details>
            <summary className="cursor-pointer py-1 font-medium">
              Display, filters &amp; risk settings
            </summary>
            <div className="mt-2 space-y-2">
              <fieldset className="space-y-2">
                <legend className="font-medium">Display &amp; confirmation</legend>
                {toggles.map(([key, label]) => (
                  <label key={key} className="flex min-h-8 items-center gap-2">
                    <input
                      type="checkbox"
                      checked={settings[key]}
                      onChange={(e) => onSettingsChange({ [key]: e.target.checked })}
                    />
                    <span>{label}</span>
                  </label>
                ))}
                <p className="text-muted-foreground">
                  Confirmed labels use the latest {settings.labelLookback} actual chart candles,
                  including a forming candle. History remains bounded to 40 formations, 80
                  polylines, 160 labels and 120 lines.
                </p>
                <label className="block space-y-1">
                  <span>Gap policy</span>
                  <select
                    className={fieldClass}
                    value={settings.gapPolicy}
                    onChange={(e) =>
                      onSettingsChange({ gapPolicy: e.target.value as BookSettings['gapPolicy'] })
                    }
                  >
                    <option value="explicit">Explicit comparisons</option>
                    <option value="continuous">Continuous-market local variant</option>
                  </select>
                </label>
                <label className="block space-y-1">
                  <span>Trend average</span>
                  <select
                    className={fieldClass}
                    value={settings.maType}
                    onChange={(e) =>
                      onSettingsChange({ maType: e.target.value as BookSettings['maType'] })
                    }
                  >
                    <option value="ema">EMA</option>
                    <option value="sma">SMA</option>
                  </select>
                </label>
              </fieldset>
              <fieldset className="space-y-2">
                <legend className="font-medium">Risk inputs</legend>
                {mainNumbers.map(([key, label]) => numberField(key, label))}
              </fieldset>
              <fieldset className="space-y-2" aria-describedby={`${id}-units`}>
                <legend className="font-medium">Explicit instrument units</legend>
                <p id={`${id}-units`} className="text-muted-foreground">
                  Use verified product units. Money per price unit is already per chosen quantity
                  unit; the lot multiplier is not applied again.
                </p>
                <label className="block space-y-1">
                  <span>Product type</span>
                  <select
                    className={fieldClass}
                    value={instrument.kind ?? ''}
                    onChange={(e) =>
                      onInstrumentChange({
                        kind: (e.target.value || undefined) as BookInstrument['kind'] | undefined,
                      })
                    }
                  >
                    <option value="">Not provided</option>
                    <option value="linear">Linear</option>
                    <option value="inverse">Inverse · sizing unavailable</option>
                    <option value="nonlinear">Nonlinear · sizing unavailable</option>
                    <option value="index">Index reference · sizing unavailable</option>
                  </select>
                </label>
                <label className="block space-y-1">
                  <span>Quantity unit</span>
                  <select
                    className={fieldClass}
                    value={instrument.unitDefinition ?? ''}
                    onChange={(e) =>
                      onInstrumentChange({
                        unitDefinition: (e.target.value || undefined) as
                          | BookInstrument['unitDefinition']
                          | undefined,
                      })
                    }
                  >
                    <option value="">Not provided</option>
                    <option value="underlying">Underlying unit</option>
                    <option value="contract">Contract</option>
                    <option value="option-premium">Option premium unit</option>
                  </select>
                </label>
                <label className="block space-y-1">
                  <span>Chart price source</span>
                  <select
                    className={fieldClass}
                    value={instrument.chartPriceKind ?? ''}
                    onChange={(e) =>
                      onInstrumentChange({
                        chartPriceKind: (e.target.value ||
                          undefined) as BookInstrument['chartPriceKind'],
                      })
                    }
                  >
                    <option value="">Not verified</option>
                    <option value="underlying">Underlying price</option>
                    <option value="premium">This option premium</option>
                  </select>
                </label>
                {(['accountCurrency', 'quoteCurrency'] as const).map((key) => (
                  <label key={key} className="block space-y-1">
                    <span>{key === 'accountCurrency' ? 'Account currency' : 'Quote currency'}</span>
                    <input
                      className={fieldClass}
                      value={instrument[key] ?? ''}
                      onChange={(e) => onInstrumentChange({ [key]: e.target.value.toUpperCase() })}
                    />
                  </label>
                ))}
                {numericUnits.map(([key, label]) => (
                  <label key={key} className="block space-y-1">
                    <span>{label}</span>
                    <input
                      className={fieldClass}
                      type="number"
                      min="0"
                      step="any"
                      value={instrument[key] ?? ''}
                      onChange={(e) =>
                        onInstrumentChange({
                          [key]: e.target.value === '' ? undefined : Number(e.target.value),
                        })
                      }
                    />
                  </label>
                ))}
              </fieldset>
              <details>
                <summary className="cursor-pointer py-1 font-medium">Local numerical rules</summary>
                <p className="my-2 text-muted-foreground">
                  These are explicit local definitions for detection and planning. They are not a
                  performance estimate.
                </p>
                <div className="space-y-2">
                  {(Object.keys(DEFAULT_BOOK_SETTINGS) as (keyof BookSettings)[])
                    .filter(
                      (key) =>
                        typeof DEFAULT_BOOK_SETTINGS[key] === 'number' &&
                        !mainNumbers.some(([k]) => k === key)
                    )
                    .map((key) => numberField(key, words(key)))}
                </div>
              </details>
            </div>
          </details>
        </div>
      </details>
    </section>
  )
}
