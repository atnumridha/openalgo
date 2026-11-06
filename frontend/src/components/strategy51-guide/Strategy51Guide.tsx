import { useId, useMemo, useState } from 'react'
import { STRATEGIES_51 } from './catalog'
import { STRATEGY51_CHART_NAMES } from './chartNames'
import { explainStrategy51, formatStrategy51Price } from './explanation'
import type { Strategy51Result, Strategy51Settings, SuppliedContext, RowState } from './types'
const price = (v: number | undefined) =>
  v == null || !Number.isFinite(v) ? '—' : v.toLocaleString('en-IN', { maximumFractionDigits: 4 })
const status: Record<RowState, string> = {
  confirmed: 'Confirmed',
  waiting: 'Waiting',
  timeframe: 'Other timeframe',
  'needs-data': 'Needs data',
  'needs-context': 'Needs context',
}
const inputClass =
  'min-h-9 w-full rounded border bg-background px-2 py-1 text-xs focus-visible:outline focus-visible:outline-2'
export function Strategy51Guide({
  result,
  settings,
  onChange,
  symbol,
  exchange,
  seconds,
}: {
  result: Strategy51Result | null
  settings: Strategy51Settings
  onChange: (change: Partial<Strategy51Settings>) => void
  symbol: string
  exchange: string
  seconds: number
}) {
  const id = useId(),
    [open, setOpen] = useState(false),
    [search, setSearch] = useState(''),
    [category, setCategory] = useState('All'),
    [readingState, setReadingState] = useState('all'),
    [activeRow, setActiveRow] = useState(''),
    [manual, setManual] = useState<Record<string, string>>({})
  const explanation = explainStrategy51(result, settings)
  const quote = (value: number | undefined) => formatStrategy51Price(value, result?.tickSize)
  const p = result?.plan,
    selected = result?.rows.find((x) => x.definition.id === settings.selected),
    title = p?.name ?? selected?.definition.title ?? 'Scanning all 51 strategies',
    scope = `${exchange}:${symbol}`
  const rows = useMemo(
    () =>
      STRATEGIES_51.filter(
        (d) =>
          (category === 'All' || d.category === category) &&
          `${d.id} ${d.title}`.toLowerCase().includes(search.toLowerCase())
      ).map(
        (d) =>
          result?.rows.find((r) => r.definition.id === d.id) ?? {
            definition: d,
            state: 'needs-data' as const,
            reason: 'Waiting for verified source candles',
            next: 'Load matching chart history',
            notes: [],
          }
      ),
    [result?.rows, category, search]
  ).filter(
    (r) =>
      readingState === 'all' ||
      (readingState === 'blocked'
        ? r.state === 'needs-data' || r.state === 'needs-context'
        : r.state === readingState)
  )
  const checked =
    result?.readiness !== 'unavailable' && result?.completedAt
      ? new Set(result.rows.map((r) => r.definition.id)).size
      : 0
  const watching =
    result?.rows.filter((r) => r.state === 'waiting' || r.state === 'confirmed').length ?? 0
  const matching = result?.rows.filter((r) => r.state === 'confirmed').length ?? 0
  const closeLabel = result?.completedAt
    ? new Intl.DateTimeFormat('en-IN', {
        timeZone: 'Asia/Kolkata',
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).format(new Date(result.completedAt * 1000))
    : ''
  const product = settings.instrumentScope === scope ? settings.instrument : undefined
  const focus = STRATEGIES_51.find((d) => d.id === settings.selected),
    row = result?.rows.find((d) => d.definition.id === settings.selected)
  const numeric = (key: keyof Strategy51Settings, label: string, min = 0) => (
    <label className="block space-y-1" key={key}>
      <span>{label}</span>
      <input
        className={inputClass}
        type="number"
        min={min}
        step="any"
        value={settings[key] as number}
        onChange={(e) => onChange({ [key]: Number(e.target.value) })}
      />
    </label>
  )
  const toggles = [
    ['cleanChart', 'Clean view · temporarily hide other studies'],
    ['showOtherSetups', 'Show other confirmed setups on the chart'],
    ['showPending', 'Show forming-candle progress'],
    ['fullHistory', 'Show retained confirmed history'],
    ['showTrendLines', 'Show confirmed context trend lines'],
    ['localStructures', 'Use disclosed local structure definitions'],
    ['localTargets', 'Use a local R target when the source has none'],
  ] as const
  const addContext = () => {
    if (!focus || !manual.description || !manual.asOf) return
    const asOf = Date.parse(`${manual.asOf}:00+05:30`) / 1000
    if (!Number.isFinite(asOf)) return
    const kinds: Record<string, SuppliedContext['kind']> = {
      '1.5': 'gap-zone',
      '3.2': 'gap-zone',
      '3.3': 'elliott',
      '3.5': 'renko',
      '3.7': 'gann',
      '4.3': 'sector',
      '7.5': 'repo',
    }
    const item: SuppliedContext = {
      strategyId: focus.id,
      kind: kinds[focus.id] ?? 'risk',
      symbol,
      exchange,
      intervalSeconds: seconds,
      asOf,
      side: manual.side === 'short' ? 'short' : 'long',
      description: manual.description,
    }
    for (const k of [
      'entry',
      'stop',
      'target',
      'zoneLow',
      'zoneHigh',
      'newRate',
      'previousRate',
      'touchCount',
    ] as const)
      if (manual[k] !== '' && manual[k] != null && Number.isFinite(Number(manual[k])))
        item[k] = Number(manual[k])
    item.liquidityConfirmed = manual.liquidity === 'yes'
    if (focus.id === '6.10' && manual.nextSessionExitAt) {
      const exit = Date.parse(`${manual.nextSessionExitAt}:00+05:30`) / 1000
      if (Number.isFinite(exit)) item.nextSessionExitAt = exit
    }
    onChange({
      supplied: [
        ...settings.supplied.filter(
          (s) =>
            !(
              s.strategyId === focus.id &&
              s.symbol === symbol &&
              s.exchange === exchange &&
              s.intervalSeconds === seconds
            )
        ),
        item,
      ],
    })
  }
  return (
    <section
      aria-label="51 strategies compact guide"
      className="mb-2 rounded border border-border bg-card text-xs"
    >
      <div className="space-y-2 p-2">
        <div className="flex items-center justify-between gap-2">
          <strong className="text-[11px] text-muted-foreground">51 strategies</strong>
          <button
            type="button"
            aria-label="Strategies & details"
            className="min-h-8 shrink-0 rounded border px-2 hover:bg-muted focus-visible:outline focus-visible:outline-2"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            aria-controls={`${id}-details`}
          >
            All 51
          </button>
        </div>
        <output
          aria-label="51 strategy scan status"
          title={`Last checked candle close: ${closeLabel || 'unavailable'} IST`}
          className="block text-[10px] leading-relaxed text-muted-foreground"
        >
          {checked === 51 ? (
            <>
              {checked}/51 checked · {result?.readiness === 'ready' ? 'Live' : 'Session history'}
              <br />
              {watching} watching · {matching} {matching === 1 ? 'match' : 'matches'} · close{' '}
              {closeLabel} IST
            </>
          ) : (
            <>Scanner paused · waiting for verified candles</>
          )}
        </output>
        <output
          aria-label="51 strategy action"
          className={`block font-semibold ${result?.readiness === 'ready' && p ? (p.side === 'long' ? 'text-emerald-500' : 'text-red-500') : 'text-muted-foreground'}`}
        >
          {result?.readiness === 'last-session'
            ? result.viewMode === 'history'
              ? 'REVIEW · History / replay'
              : result.viewMode === 'closed-session'
                ? 'MARKET CLOSED · Review'
                : 'REVIEW · Earlier candles'
            : result?.readiness !== 'ready'
              ? 'WAIT · Checking data'
              : p
                ? p.side === 'long'
                  ? 'LONG SETUP'
                  : 'SHORT SETUP'
                : 'WAIT · No confirmed setup'}
        </output>
        <p className="break-words font-medium" title={title}>
          {p
            ? `${p.strategyId} · ${STRATEGY51_CHART_NAMES[p.strategyId] ?? p.name}`
            : settings.selected === 'auto'
              ? 'Scanning all 51 strategies'
              : `${settings.selected} · ${STRATEGY51_CHART_NAMES[settings.selected] ?? title}`}
        </p>
        <p className="text-[11px] text-muted-foreground">
          {result?.trend === 'bull'
            ? 'Bullish trend'
            : result?.trend === 'bear'
              ? 'Bearish trend'
              : result?.trend === 'neutral'
                ? 'Sideways trend'
                : 'Trend unavailable'}{' '}
          · {seconds / 60}m
        </p>
        <section aria-label="Why this setup" className="leading-relaxed">
          <p>
            <strong>Why:</strong> {explanation.why}
          </p>
          {explanation.confirmed && (
            <p className="text-[10px] text-muted-foreground">{explanation.confirmed}</p>
          )}
        </section>
        {p && (
          <fieldset
            className="space-y-1 border-y py-2 tabular-nums"
            aria-label="51 strategy price references"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-x-2">
              <span className="block text-[10px] text-muted-foreground">Entry</span>
              <strong className="whitespace-nowrap">{quote(p.entry)}</strong>
            </div>
            <div className="flex flex-wrap items-baseline justify-between gap-x-2">
              <span className="block text-[10px] text-red-500">SL</span>
              <strong className="whitespace-nowrap">{quote(p.currentStop ?? p.stop)}</strong>
            </div>
            <div className="flex flex-wrap items-baseline justify-between gap-x-2">
              <span className="block text-[10px] text-emerald-500">
                {p.targetOrigin === 'local'
                  ? 'Local target'
                  : p.targetOrigin === 'supplied'
                    ? 'Supplied target'
                    : 'Target'}
              </span>
              <strong className="whitespace-nowrap">
                {p.target == null ? 'Exit rule' : quote(p.target)}
              </strong>
              {p.rr != null && (
                <span className="w-full text-right text-[10px] text-muted-foreground">
                  {price(p.rr)}R reward / risk
                </span>
              )}
            </div>
          </fieldset>
        )}
        {explanation.now && (
          <section aria-label="Price progress" className="leading-relaxed">
            <p>
              <strong>Now:</strong> {explanation.now}
            </p>
          </section>
        )}
        {explanation.scenario && (
          <section aria-label="Expected scenario" className="leading-relaxed">
            <p>
              <strong>Scenario:</strong> {explanation.scenario}
            </p>
          </section>
        )}
        {explanation.invalidation && (
          <section aria-label="Setup invalidation" className="leading-relaxed">
            <p>
              <strong>Invalid if:</strong> {explanation.invalidation}
            </p>
          </section>
        )}
        <section aria-label="Next chart action" className="leading-relaxed">
          <p>
            <strong>Next:</strong> {explanation.next}
          </p>
        </section>
        <p className="text-[10px] leading-relaxed text-muted-foreground">
          Dotted link → source candle · orange line → swing support / resistance context.
        </p>
        {settings.showPending && result?.forming && (
          <p className="text-muted-foreground">
            Forming {price(result.forming.price)} · provisional; confirmations wait for
            source-observed candle close.
          </p>
        )}
      </div>
      {open && (
        <div id={`${id}-details`} className="space-y-3 border-t p-2">
          <p title={title}>{title}</p>
          <p>{result?.next}</p>
          {settings.cleanChart && (
            <p>
              Other indicator drawings are temporarily hidden. Turn off Clean view below to restore
              your saved studies.
            </p>
          )}
          <p>
            {result?.reason ?? 'Waiting for chart history.'} Chart {symbol} · {seconds / 60}m. The
            study reads data and draws references; orders remain manual.
          </p>
          {checked === 51 && <p>Last checked candle close: {closeLabel} IST.</p>}
          <p>
            All 51 checks continue when you focus a plan. Only matching chart timeframes,
            instruments and available inputs can confirm a setup.
          </p>
          <label className="block space-y-1">
            <span>Plan selection</span>
            <select
              className={inputClass}
              value={settings.selected}
              onChange={(e) => onChange({ selected: e.target.value })}
            >
              <option value="auto">Auto · one frozen plan</option>
              {STRATEGIES_51.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.id} · {d.title}
                </option>
              ))}
            </select>
          </label>
          {p && (
            <div className="space-y-1 rounded border p-2">
              <p>{p.expected}</p>
              <p>{p.stopMethod}</p>
              <p>{p.targetMethod}</p>
              <p>{p.exitRule}</p>
              {p.partialAtR != null && (
                <p>
                  Source partial reference at {p.partialAtR}R
                  {p.breakevenAfterPartial ? ' then remaining stop to entry' : ''}; actual
                  quantities/fills are not inferred.
                </p>
              )}
              <p>
                {p.sizing?.quantity != null
                  ? `Fixed-risk quantity ${price(p.sizing.quantity)}${p.sizing.lots != null ? ` · ${price(p.sizing.lots)} lots` : ''} · estimated risk ${price(p.sizing.estimatedRiskCash)} ${product?.accountCurrency ?? ''}`
                  : 'Monetary size unavailable until equity and exact product units are supplied.'}
              </p>
              {p.sizing?.unavailableReasons.map((r) => (
                <p className="text-muted-foreground" key={r}>
                  {r}
                </p>
              ))}
              {p.notes.map((n) => (
                <p className="text-muted-foreground" key={n}>
                  {n}
                </p>
              ))}
            </div>
          )}
          {result?.lastPlan && (
            <p>
              Previous reference · {result.lastPlan.strategyId} ·{' '}
              {result.lastPlan.status.replaceAll('-', ' ')}
            </p>
          )}
          <div className="grid grid-cols-2 gap-2">
            <label className="block space-y-1">
              <span>Find a strategy</span>
              <input
                className={inputClass}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Name or book ID"
              />
            </label>
            <label className="block space-y-1">
              <span>Category</span>
              <select
                className={inputClass}
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                {[
                  'All',
                  'Swing',
                  'Intraday',
                  'Trend',
                  'Positional',
                  'Scalping',
                  'Options',
                  'Price action',
                ].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
          </div>
          <label className="block space-y-1">
            <span>Reading status</span>
            <select
              className={inputClass}
              value={readingState}
              onChange={(e) => setReadingState(e.target.value)}
            >
              <option value="all">All 51 readings</option>
              <option value="confirmed">Matching conditions</option>
              <option value="waiting">Watching for confirmation</option>
              <option value="blocked">Needs data or context</option>
              <option value="timeframe">Other timeframe</option>
            </select>
          </label>
          <p>
            {rows.length} of 51 strategies · select any row to focus its plan. Closed confirmations
            only; incomplete data stays explicit.
          </p>
          <div className="max-h-80 overflow-y-auto rounded border">
            <table className="w-full table-fixed text-left" aria-label="All 51 strategy readings">
              <thead className="sticky top-0 bg-card">
                <tr>
                  <th className="p-2">Strategy / expected action</th>
                  <th className="w-24 p-2">State</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.definition.id} className="border-t align-top">
                    <td className="break-words p-2">
                      <button
                        type="button"
                        className="min-h-9 text-left font-medium underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2"
                        aria-label={`Focus strategy ${r.definition.id} ${r.definition.title}`}
                        onClick={() => {
                          onChange({ selected: r.definition.id })
                          setActiveRow(r.definition.id)
                        }}
                      >
                        {r.definition.id} · {r.definition.title}
                      </button>
                      <p className="text-muted-foreground">{r.reason}</p>
                      {(activeRow === r.definition.id || settings.selected === r.definition.id) && (
                        <div className="mt-2 space-y-1">
                          <p>Next: {r.next}</p>
                          <p>Entry: {r.definition.entry}</p>
                          <p>Stop: {r.definition.stop}</p>
                          <p>
                            Target / exit: {r.definition.target} · {r.definition.exit}
                          </p>
                          <p>Inputs: {r.definition.requirements.join('; ')}</p>
                          <p>Source pp. {r.definition.pages.join('–')}</p>
                          {r.definition.notes.map((n) => (
                            <p key={n}>{n}</p>
                          ))}
                          {r.definition.local.map((n) => (
                            <p className="text-muted-foreground" key={n}>
                              Local convention: {n}
                            </p>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="p-2">{status[r.state]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary className="min-h-9 cursor-pointer py-2 font-medium">
              Display, local rules &amp; fixed risk
            </summary>
            <div className="space-y-2">
              {toggles.map(([key, label]) => (
                <label className="flex min-h-9 items-center gap-2" key={key}>
                  <input
                    type="checkbox"
                    checked={settings[key]}
                    onChange={(e) => onChange({ [key]: e.target.checked })}
                  />
                  <span>{label}</span>
                </label>
              ))}
              <p>
                One plan is drawn by default. Other confirmed setups and history are optional.
                Latest {settings.labelLookback} actual candles; retained drawings are bounded to 8
                whole strategy annotations. All 51 readings remain available here. Local canonical
                defaults: EMA/SMA seeding, BB20/2, RSI14, VO EMA5/10, Donchian20, ST7/3 or10/3,
                confirmed3L/3R structure (4L/4R for3.4), .25ATR touches and1.5×volume.
              </p>
              {numeric('labelLookback', 'Confirmed label window', 1)}
              {numeric('equity', 'Account equity')}
              {numeric('riskPercent', 'Fixed risk per plan (%)', 0.001)}
              {numeric('targetR', 'Local fallback target (R)', 0.25)}
              {numeric('minRR', 'Optional minimum reward / risk')}
              {numeric('planExpiryBars', 'Local reference expiry (completed candles)', 1)}
              {numeric('fixedCost', 'Fixed round-trip cost')}
              {numeric('perUnitCost', 'Round-trip cost per unit')}
              {numeric('slippagePrice', 'Slippage price allowance')}
              <fieldset className="space-y-2 rounded border p-2">
                <legend>Exact product units · {scope}</legend>
                <p>
                  Enter money per price unit for the selected quantity unit. Lots are presentation
                  only; no extra lot multiplier is applied.
                </p>
                <label className="block">
                  Product
                  <select
                    className={inputClass}
                    value={settings.instrumentScope === scope ? (product?.kind ?? '') : ''}
                    onChange={(e) =>
                      onChange({
                        instrumentScope: scope,
                        instrument: {
                          ...product,
                          kind: e.target.value as 'linear',
                          unitDefinition: product?.unitDefinition ?? 'underlying',
                          chartPriceKind: /(CE|PE)$/.test(symbol) ? 'premium' : 'underlying',
                        },
                      })
                    }
                  >
                    <option value="">Not verified</option>
                    <option value="linear">Verified linear product</option>
                    <option value="index">Index reference (no sizing)</option>
                  </select>
                </label>
                <label className="block">
                  Quantity unit
                  <select
                    className={inputClass}
                    value={product?.unitDefinition ?? 'underlying'}
                    onChange={(e) =>
                      onChange({
                        instrumentScope: scope,
                        instrument: {
                          ...product,
                          kind: product?.kind ?? 'linear',
                          unitDefinition: e.target.value as 'contract',
                          chartPriceKind: /(CE|PE)$/.test(symbol) ? 'premium' : 'underlying',
                        },
                      })
                    }
                  >
                    <option value="underlying">Underlying unit</option>
                    <option value="contract">Contract</option>
                    <option value="option-premium">Option premium unit</option>
                  </select>
                </label>
                {(['valuePerPriceUnit', 'quantityStep', 'lotSize', 'conversionRate'] as const).map(
                  (k) => (
                    <label className="block" key={k}>
                      {
                        {
                          valuePerPriceUnit: 'Money per price unit',
                          quantityStep: 'Quantity step',
                          lotSize: 'Units per displayed lot',
                          conversionRate: 'Quote to account conversion',
                        }[k]
                      }
                      <input
                        className={inputClass}
                        type="number"
                        min="0"
                        step="any"
                        value={product?.[k] ?? ''}
                        onChange={(e) =>
                          onChange({
                            instrumentScope: scope,
                            instrument: {
                              ...product,
                              kind: product?.kind ?? 'linear',
                              unitDefinition: product?.unitDefinition ?? 'underlying',
                              [k]: e.target.value === '' ? undefined : Number(e.target.value),
                            },
                          })
                        }
                      />
                    </label>
                  )
                )}
                {(['accountCurrency', 'quoteCurrency'] as const).map((k) => (
                  <label className="block" key={k}>
                    {k === 'accountCurrency' ? 'Account currency' : 'Quote currency'}
                    <input
                      className={inputClass}
                      maxLength={8}
                      value={product?.[k] ?? ''}
                      onChange={(e) =>
                        onChange({
                          instrumentScope: scope,
                          instrument: {
                            ...product,
                            kind: product?.kind ?? 'linear',
                            unitDefinition: product?.unitDefinition ?? 'underlying',
                            [k]: e.target.value.toUpperCase(),
                          },
                        })
                      }
                    />
                  </label>
                ))}
              </fieldset>
            </div>
          </details>
          {focus && (
            <details>
              <summary className="min-h-9 cursor-pointer py-2 font-medium">
                Supply missing context for {focus.id}
              </summary>
              <div className="space-y-2">
                <p>
                  {row?.next ?? focus.requirements.join('; ')}. Supplied context is labelled manual
                  and applies only to this exact chart/timeframe. Never enter future-known anchors.
                </p>
                <label className="block">
                  Known as of (IST)
                  <input
                    className={inputClass}
                    type="datetime-local"
                    value={manual.asOf ?? ''}
                    onChange={(e) => setManual((v) => ({ ...v, asOf: e.target.value }))}
                  />
                </label>
                {focus.id === '6.10' && (
                  <label className="block">
                    Verified next trading session exit (IST ·09:30)
                    <input
                      className={inputClass}
                      type="datetime-local"
                      value={manual.nextSessionExitAt ?? ''}
                      onChange={(e) =>
                        setManual((v) => ({ ...v, nextSessionExitAt: e.target.value }))
                      }
                    />
                    <span className="text-muted-foreground">
                      Verify the exchange calendar, including holidays. The contract must remain
                      valid through this exit.
                    </span>
                  </label>
                )}
                <label className="block">
                  Direction
                  <select
                    className={inputClass}
                    value={manual.side ?? 'long'}
                    onChange={(e) => setManual((v) => ({ ...v, side: e.target.value }))}
                  >
                    <option value="long">Long</option>
                    <option value="short">Short</option>
                  </select>
                </label>
                {(focus.id === '7.5'
                  ? ['newRate', 'previousRate']
                  : ['entry', 'stop', 'target', 'zoneLow', 'zoneHigh', 'touchCount']
                ).map((k) => (
                  <label className="block" key={k}>
                    {
                      (
                        {
                          entry: 'Source price trigger',
                          stop: 'Explicit stop anchor',
                          target: 'Known target',
                          zoneLow: 'Zone low (if applicable)',
                          zoneHigh: 'Zone high (if applicable)',
                          touchCount: 'Old zone touch count',
                          newRate: 'Announced repo rate',
                          previousRate: 'Previous repo rate',
                        } as Record<string, string>
                      )[k]
                    }
                    <input
                      className={inputClass}
                      type="number"
                      min="0"
                      step="any"
                      value={manual[k] ?? ''}
                      onChange={(e) => setManual((v) => ({ ...v, [k]: e.target.value }))}
                    />
                  </label>
                ))}
                <label className="block">
                  Source / as-of context explanation
                  <textarea
                    className={inputClass}
                    value={manual.description ?? ''}
                    onChange={(e) => setManual((v) => ({ ...v, description: e.target.value }))}
                  />
                </label>
                {focus.id === '1.5' && (
                  <label className="flex min-h-9 items-center gap-2">
                    <input
                      type="checkbox"
                      checked={manual.liquidity === 'yes'}
                      onChange={(e) =>
                        setManual((v) => ({ ...v, liquidity: e.target.checked ? 'yes' : 'no' }))
                      }
                    />
                    Liquid universe confirmed by user
                  </label>
                )}
                <button
                  type="button"
                  className="min-h-9 rounded border px-3 hover:bg-muted disabled:opacity-50"
                  disabled={!manual.asOf || !manual.description}
                  onClick={addContext}
                >
                  Use supplied context
                </button>
              </div>
            </details>
          )}
          <p className="text-muted-foreground">
            Source price levels and local interpretations are separated. No historical win rate,
            guaranteed outcome, margin availability or order fill is implied. Martingale loss
            escalation is never used.
          </p>
        </div>
      )}
    </section>
  )
}
