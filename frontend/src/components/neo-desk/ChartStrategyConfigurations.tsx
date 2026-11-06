import { useEffect, useId, useMemo, useState, type Dispatch, type SetStateAction } from 'react'
import { scalpingApi } from '@/api/scalping'
import { activeExpiries, nearestExpiry } from '@/lib/neoOptionSelection'
import type { OptionChainResponse } from '@/types/scalping'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import {
  SOURCE_STRATEGIES,
  strategyCompatibility,
  optionChartReference,
  proposedFutureTrigger,
  strategyStorageKey,
  readStrategyConfiguration,
  saveStrategyConfiguration,
  proposedOptionLegs,
  optionStructurePreview,
  strategyReferenceLevels,
  type StrategyConfiguration,
  type StrategyReference,
  type SourceStrategy,
} from './chartStrategyConfigurations'

export interface ChartStrategyConfigurationsProps {
  symbol: string
  exchange: string
  interval: string
  tickSize?: number
  lotSize?: number | null
  selectedId?: string
  onSelectedIdChange?: (id: string) => void
  onReferences?: (levels: StrategyReference[]) => void
}
export function ChartStrategyConfigurations(props: ChartStrategyConfigurationsProps) {
  const owner = useAuthStore((s) => s.user?.username),
    broker = useAuthStore((s) => s.user?.broker)
  const appMode = useThemeStore((s) => s.appMode)
  const storageKey = strategyStorageKey({ owner, broker, appMode, ...props })
  return (
    <ConfigurationSelection
      key={
        storageKey ??
        JSON.stringify([owner, broker, appMode, props.symbol, props.exchange, props.interval])
      }
      {...props}
      storageKey={storageKey}
    />
  )
}
function ConfigurationSelection(
  props: ChartStrategyConfigurationsProps & { storageKey: string | null }
) {
  const [internalId, setInternalId] = useState(
    () => readStrategyConfiguration(localStorage, props.storageKey).selectedId
  )
  const requested = props.selectedId ?? internalId
  const selectedId = SOURCE_STRATEGIES.some((s) => s.id === requested) ? requested : ''
  return (
    <ScopedConfigurations
      key={selectedId}
      {...props}
      selectedId={selectedId}
      onSelectedIdChange={(id) => {
        if (props.selectedId === undefined) setInternalId(id)
        props.onSelectedIdChange?.(id)
      }}
    />
  )
}
function ScopedConfigurations({
  symbol,
  exchange,
  interval,
  tickSize,
  lotSize,
  storageKey,
  selectedId,
  onSelectedIdChange,
  onReferences,
}: ChartStrategyConfigurationsProps & { storageKey: string | null; selectedId: string }) {
  const id = useId(),
    templateKey = storageKey ? `${storageKey}:template:${selectedId}` : null
  const [draft, setDraft] = useState<StrategyConfiguration>(() => {
    const scoped = readStrategyConfiguration(localStorage, templateKey),
      legacy = readStrategyConfiguration(localStorage, storageKey)
    const saved =
      scoped.selectedId === selectedId
        ? scoped
        : legacy.selectedId === selectedId
          ? legacy
          : { selectedId, entry: '', direction: '' as const, notes: '' }
    return {
      ...saved,
      anchor: saved.anchor ?? '',
      expiry: saved.expiry ?? '',
      legs: saved.legs ?? proposedOptionLegs(selectedId),
    }
  })
  const [saveFailed, setSaveFailed] = useState(false)
  useEffect(() => {
    if (!storageKey || !selectedId) return
    const perTemplate = saveStrategyConfiguration(localStorage, templateKey, draft)
    const current = saveStrategyConfiguration(localStorage, storageKey, draft)
    setSaveFailed(!perTemplate || !current)
  }, [draft, storageKey, templateKey, selectedId])
  const strategy = SOURCE_STRATEGIES.find((s) => s.id === selectedId)
  const compatibility = strategy ? strategyCompatibility(strategy, symbol, exchange) : null
  const selectedOption = strategy ? optionChartReference(strategy, symbol, exchange) : null
  const levels = useMemo(
    () =>
      strategy
        ? strategyReferenceLevels({ strategy, configuration: draft, symbol, exchange, tickSize })
        : [],
    [strategy, draft, symbol, exchange, tickSize]
  )
  useEffect(() => {
    onReferences?.(levels)
  }, [onReferences, levels])
  const trigger = strategy
    ? proposedFutureTrigger({
        strategy,
        symbol,
        exchange,
        tickSize,
        entry: Number(draft.entry),
        direction: draft.direction,
      })
    : null
  const control = 'w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs'
  return (
    <section aria-label="Selected strategy configuration" className="space-y-3 p-3 text-xs">
      <label className="block max-w-md space-y-1" htmlFor={`${id}-source`}>
        <span>Strategy</span>
        <select
          id={`${id}-source`}
          className={control}
          value={selectedId}
          onChange={(e) => onSelectedIdChange?.(e.target.value)}
        >
          <option value="">No source template</option>
          {SOURCE_STRATEGIES.map((source) => (
            <option key={source.id} value={source.id}>
              {source.id} · {source.name}
            </option>
          ))}
        </select>
      </label>
      {strategy && (
        <>
          <div className="rounded-md border border-border bg-muted/30 p-3">
            <strong className="text-sm">{strategy.name} · how it works</strong>
            <p className="mt-1">
              Choose a strike and expiry below. Prices and the example profit/loss chart update
              automatically. This screen does not place trades.
            </p>
            <output
              className={`mt-2 block ${compatibility?.compatible || selectedOption ? 'text-muted-foreground' : 'text-destructive'}`}
            >
              {selectedOption
                ? `You are viewing the option price. Selected contract: ${strategy.underlying} ${selectedOption.strike}, expiry ${selectedOption.expiry}.`
                : compatibility?.kind === 'index-context'
                  ? `You are viewing the ${strategy.underlying} index. Choose an option strike below.`
                  : compatibility?.kind === 'future'
                    ? 'Futures contract selected. Enter your price and direction to see the stop level.'
                    : `This example needs a ${strategy.underlying} contract. Select one to continue.`}
            </output>
            {strategy.instrument === 'options' && !compatibility?.compatible && (
              <a
                className="mt-1 inline-block underline underline-offset-2"
                href={`/trading?${new URLSearchParams({ symbol: strategy.underlying, exchange: 'NSE_INDEX', interval })}`}
              >
                Open {strategy.underlying} index to view strike guides
              </a>
            )}
            {strategy.instrument === 'future' && compatibility?.kind !== 'future' && (
              <p className="mt-1 font-medium">
                Use the chart symbol selector to choose a listed {strategy.underlying} dated NFO
                futures contract. The current chart stays selected.
              </p>
            )}
          </div>
          <div className="grid items-start gap-4 lg:grid-cols-2">
            <div className="space-y-3">
              {strategy.instrument === 'options' ? (
                <>
                  <p className="text-muted-foreground">
                    This is an example setup based on your selected strike. Check or change its
                    option contracts in Advanced details.
                  </p>
                  <ListedStrategySelectors
                    strategy={strategy}
                    selectedOption={selectedOption}
                    draft={draft}
                    setDraft={setDraft}
                    control={control}
                  />
                  <details className="space-y-2 rounded-md border border-border p-2">
                    <summary className="cursor-pointer font-medium">
                      Advanced details · option contracts
                    </summary>
                    {(draft.legs ?? []).map((leg, i) => (
                      <fieldset key={i} className="rounded-md border border-border p-2">
                        <legend className="px-1 font-medium">
                          Proposed leg {i + 1} · quantity + buy / − sell
                          {draft.anchor?.trim() && Number.isFinite(Number(leg.offset)) && (
                            <span>
                              {' '}
                              · strike {Number(draft.anchor) + Number(leg.offset)} {leg.optionType}
                            </span>
                          )}
                        </legend>
                        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                          <label className="space-y-1">
                            <span>Option</span>
                            <select
                              aria-label={`Leg ${i + 1} option type`}
                              className={control}
                              value={leg.optionType}
                              onChange={(e) =>
                                setDraft({
                                  ...draft,
                                  legs: draft.legs!.map((old, j) =>
                                    i === j
                                      ? { ...old, optionType: e.target.value as 'CE' | 'PE' }
                                      : old
                                  ),
                                })
                              }
                            >
                              <option>CE</option>
                              <option>PE</option>
                            </select>
                          </label>
                          {(['quantity', 'offset', 'premium'] as const).map((field) => (
                            <label key={field} className="space-y-1">
                              <span>
                                {field === 'offset'
                                  ? 'Distance from selected strike'
                                  : field === 'quantity'
                                    ? 'Buy (+) / sell (−)'
                                    : 'Premium'}
                              </span>
                              <input
                                aria-label={`Leg ${i + 1} ${field}`}
                                className={control}
                                type="number"
                                step={field === 'quantity' ? 1 : 'any'}
                                min={field === 'premium' ? 0 : undefined}
                                value={leg[field]}
                                placeholder={field === 'premium' ? 'Quote unavailable' : ''}
                                onChange={(e) =>
                                  setDraft({
                                    ...draft,
                                    legs: draft.legs!.map((old, j) =>
                                      i === j ? { ...old, [field]: e.target.value } : old
                                    ),
                                  })
                                }
                              />
                            </label>
                          ))}
                        </div>
                      </fieldset>
                    ))}
                  </details>
                  <p className="text-muted-foreground">
                    Option prices are filled automatically when quotes are available. Fees are not
                    included. These example settings still need checking before any trade.
                  </p>
                </>
              ) : compatibility?.kind === 'future' ? (
                <>
                  <p className="font-medium">
                    Your futures contract · {symbol} · {interval}
                  </p>
                  <label className="block space-y-1">
                    <span>Your direction</span>
                    <select
                      aria-label="Your direction"
                      className={control}
                      value={draft.direction}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          direction: e.target.value as StrategyConfiguration['direction'],
                        })
                      }
                    >
                      <option value="">Choose direction</option>
                      <option value="long">Long</option>
                      <option value="short">Short</option>
                    </select>
                  </label>
                  <label className="block space-y-1">
                    <span>Actual futures entry</span>
                    <input
                      aria-label="Actual futures entry"
                      className={control}
                      type="number"
                      min="0"
                      step={tickSize && tickSize > 0 ? tickSize : 'any'}
                      value={draft.entry}
                      onChange={(e) => setDraft({ ...draft, entry: e.target.value })}
                    />
                  </label>
                  {trigger === null ? (
                    <p className="text-muted-foreground">
                      Supply actual entry and direction with verified tick metadata. Entry and
                      trigger must align with that tick before lines appear.
                    </p>
                  ) : (
                    <output className="block font-medium">
                      Proposed trigger: {trigger} futures price points ·{' '}
                      {draft.direction === 'long' ? 'entry − 200' : 'entry + 200'}. Entry and stop
                      references are now on this chart.
                    </output>
                  )}
                  <p className="text-muted-foreground">
                    200 points is a stop trigger, not guaranteed capped monetary loss. Slippage and
                    gaps can change the outcome. No order is placed.
                  </p>
                </>
              ) : (
                <p className="text-muted-foreground">
                  Entry and stop lines require the actual listed future, its verified price
                  increment, your entry and direction. The diagram explains the 200-point stop
                  relationship while you choose the contract.
                </p>
              )}
            </div>
            <SourceStructurePreview strategy={strategy} draft={draft} />
          </div>
          <p className="text-muted-foreground">
            {strategy.instrument === 'options'
              ? levels.length
                ? 'Dashed lines on the index chart mark the example strikes.'
                : 'This option chart shows the option price. Strike lines appear on the index chart.'
              : 'Only your matching future entry and stop references can appear on the price chart. This template does not supply an automatic entry signal.'}
          </p>
          <details className="rounded-md border border-border p-2">
            <summary className="cursor-pointer font-medium">About this example</summary>
            <p className="mt-2">
              <strong>Source supplied: </strong>
              {strategy.sourceParameters}
            </p>
            <p className="mt-2">
              <strong>Unconfigured: </strong>
              {strategy.unconfigured.join('; ')}. No orders or proprietary entry signals are
              generated.
            </p>
            <p className="mt-2 text-muted-foreground">
              Source card capital ₹{strategy.sourceClaim.minimumCapitalInr.toLocaleString('en-IN')}{' '}
              and drawdown {strategy.sourceClaim.maximumDrawdownPercent}% are unverified claims, not
              measured app performance or sizing guarantees.
            </p>
          </details>
          <label className="block space-y-1">
            <span>Your notes (optional)</span>
            <textarea
              aria-label="Your notes (optional)"
              className={control}
              rows={2}
              maxLength={4000}
              value={draft.notes}
              placeholder="Add a note…"
              onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
            />
          </label>
          <p className="text-muted-foreground">
            Contract lot size:{' '}
            {lotSize && lotSize > 0
              ? `${lotSize}; verify actual selected contract`
              : 'unconfigured'}
            . The graph shows points per unit; fees are extra.
          </p>
        </>
      )}
      {!storageKey && (
        <p className="text-muted-foreground">Sign in to save this chart configuration.</p>
      )}
      {saveFailed && (
        <output className="block text-destructive">
          Changes are visible here but could not be saved on this device.
        </output>
      )}
    </section>
  )
}
function SourceStructurePreview({
  strategy,
  draft,
}: {
  strategy: SourceStrategy
  draft: StrategyConfiguration
}) {
  const relative = !draft.anchor?.trim()
  // A synthetic origin is used ONLY in this explicitly relative illustration, never for chart levels.
  const origin = relative
    ? Math.max(1000, ...(draft.legs ?? []).map((leg) => Math.abs(Number(leg.offset) || 0) + 1000))
    : Number(draft.anchor)
  const preview = useMemo(
    () => optionStructurePreview(strategy, relative ? { ...draft, anchor: String(origin) } : draft),
    [strategy, draft, relative, origin]
  )
  if (strategy.instrument === 'future')
    return (
      <figure className="rounded-md border border-border bg-muted/20 p-3">
        <svg
          role="img"
          aria-label={`Illustrative ${strategy.name} preview`}
          viewBox="0 0 360 150"
          className="w-full text-foreground"
        >
          <line x1="30" y1="70" x2="330" y2="70" stroke="currentColor" opacity=".3" />
          <line x1="180" y1="35" x2="180" y2="100" stroke="currentColor" />
          <path
            d="M55 50 L180 50 M180 90 L305 90"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          />
          <text x="30" y="35" fontSize="12" fill="currentColor">
            Long stop: −200 points
          </text>
          <text x="177" y="122" textAnchor="middle" fontSize="12" fill="currentColor">
            Your entry
          </text>
          <text x="190" y="145" fontSize="12" fill="currentColor">
            Short stop: +200 points
          </text>
        </svg>
        <section aria-label="Preview calculation" className="space-y-1 text-xs">
          <strong>Illustrative 200-point stop relationship</strong>
          <p className="text-muted-foreground">
            Relative distance only. Actual chart levels require a matching future and valid
            entry/direction. No target or automatic entry is inferred.
          </p>
        </section>
      </figure>
    )
  const points = preview.points,
    minX = points.at(0)?.price ?? 0,
    maxX = points.at(-1)?.price ?? 1
  const minY = Math.min(0, ...points.map((p) => p.value)),
    maxY = Math.max(0, ...points.map((p) => p.value)),
    rangeY = Math.max(1, maxY - minY)
  const x = (price: number) => 32 + ((price - minX) / Math.max(1, maxX - minX)) * 296,
    y = (value: number) => 130 - ((value - minY) / rangeY) * 100
  const fmt = (v: number) => v.toLocaleString('en-IN', { maximumFractionDigits: 2 })
  return (
    <figure className="rounded-md border border-border bg-muted/20 p-3">
      <svg
        role="img"
        aria-label={`Illustrative ${strategy.name} preview`}
        viewBox="0 0 360 175"
        className="w-full text-foreground"
      >
        <line x1="32" x2="328" y1={y(0)} y2={y(0)} stroke="currentColor" opacity=".25" />
        <line x1="32" x2="32" y1="22" y2="132" stroke="currentColor" opacity=".25" />
        {points.length > 0 && (
          <polyline
            data-testid="structure-payoff"
            points={points.map((p) => `${x(p.price)},${y(p.value)}`).join(' ')}
            fill="none"
            className="stroke-primary"
            strokeWidth="2"
          />
        )}
        <text x="32" y="15" fontSize="11" fill="currentColor">
          {fmt(maxY)} points
        </text>
        <text x="32" y="146" fontSize="11" fill="currentColor">
          {fmt(minY)} points
        </text>
        <text x="32" y="168" fontSize="11" fill="currentColor">
          {fmt(minX - (relative ? origin : 0))}
        </text>
        <text x="328" y="168" textAnchor="end" fontSize="11" fill="currentColor">
          {fmt(maxX - (relative ? origin : 0))}
        </text>
      </svg>
      <section aria-label="Preview calculation" className="space-y-2">
        <strong>
          {preview.includesPremiums
            ? 'Possible profit / loss at expiry'
            : 'Option prices still loading'}{' '}
          · example
        </strong>
        <p className="text-muted-foreground">
          Left to right: {strategy.underlying} price at expiry. Up: possible profit. Down: possible
          loss. Values are points per unit, before fees.
        </p>
        {!preview.includesPremiums && (
          <p>Some option prices are missing. The line does not show the full profit or loss yet.</p>
        )}
        {!points.length && preview.reason && (
          <p className="text-destructive">
            Choose a valid strike and check the option details to show this example.
          </p>
        )}
      </section>
    </figure>
  )
}

/** Resolve current listed expiries/strikes using the same session API as the chart's strike picker. */
function ListedStrategySelectors({
  strategy,
  selectedOption,
  draft,
  setDraft,
  control,
}: {
  strategy: SourceStrategy
  selectedOption: { strike: number; expiry: string } | null
  draft: StrategyConfiguration
  setDraft: Dispatch<SetStateAction<StrategyConfiguration>>
  control: string
}) {
  const [dates, setDates] = useState<string[] | null>(null)
  const [catalog, setCatalog] = useState<OptionChainResponse | null>(null)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const expiry = dates?.includes(draft.expiry ?? '')
    ? draft.expiry!
    : selectedOption && dates?.includes(selectedOption.expiry)
      ? selectedOption.expiry
      : nearestExpiry(dates ?? [])
  // biome-ignore lint/correctness/useExhaustiveDependencies: refresh explicitly retries the same listing request.
  useEffect(() => {
    let current = true
    setDates(null)
    setError('')
    void scalpingApi
      .getExpiry(strategy.underlying, 'NFO', 'options')
      .then((result) => {
        if (!current) return
        if (result.status !== 'success' || !Array.isArray(result.data))
          throw Error('Listed expiries unavailable.')
        const active = activeExpiries(result.data)
        setDates(active)
        if (!active.length) setError('No active listed expiries are available for this underlying.')
      })
      .catch(() => {
        if (current) {
          setDates([])
          setError('Could not load listed expiries. Refresh to retry.')
        }
      })
    return () => {
      current = false
    }
  }, [strategy.underlying, refresh])
  // biome-ignore lint/correctness/useExhaustiveDependencies: refresh explicitly reloads quotes for the same expiry.
  useEffect(() => {
    let current = true
    setCatalog(null)
    if (!expiry)
      return () => {
        current = false
      }
    setError('')
    void scalpingApi
      .getStrikes(strategy.underlying, 'NFO', expiry, 20, { quotes: true })
      .then((result) => {
        if (!current) return
        if (
          result.status !== 'success' ||
          result.underlying !== strategy.underlying ||
          result.expiry_date !== expiry ||
          result.fo_exchange !== 'NFO' ||
          !Array.isArray(result.chain)
        )
          throw Error('Strike catalog does not match the selected expiry.')
        setCatalog(result)
        if (!result.chain.length) setError('No listed strikes are available for this expiry.')
      })
      .catch(() => {
        if (current) setError('Could not load listed strikes. Refresh to retry.')
      })
    return () => {
      current = false
    }
  }, [strategy.underlying, expiry, refresh])
  const chain = catalog?.expiry_date === expiry ? catalog : null
  const strikes = [
    ...new Set(
      (chain?.chain ?? [])
        .filter(
          (row) =>
            Number.isFinite(row.strike) && row.strike > 0 && (row.ce?.symbol || row.pe?.symbol)
        )
        .map((row) => row.strike)
    ),
  ].sort((a, b) => a - b)
  const legGeometry = (draft.legs ?? []).map((leg) => `${leg.optionType}:${leg.offset}`).join('|')
  // biome-ignore lint/correctness/useExhaustiveDependencies: geometry and anchor trigger quote recalculation; the updater reads the latest draft.
  useEffect(() => {
    if (!chain) return
    const listed = chain.chain.filter(
      (row) => Number.isFinite(row.strike) && row.strike > 0 && (row.ce?.symbol || row.pe?.symbol)
    )
    if (!listed.length) return
    setDraft((previous) => {
      const saved = Number(previous.anchor)
      const atm = listed.find((row) => row.strike === chain.atm_strike)?.strike
      const quote = chain.underlying_ltp
      const fallback =
        Number.isFinite(quote) && quote! > 0
          ? [...listed].sort((a, b) => Math.abs(a.strike - quote!) - Math.abs(b.strike - quote!))[0]
              .strike
          : undefined
      const fromChart =
        selectedOption &&
        selectedOption.expiry === expiry &&
        listed.some((row) => row.strike === selectedOption.strike)
          ? selectedOption.strike
          : undefined
      const anchor = listed.some((row) => row.strike === saved)
        ? saved
        : (fromChart ?? atm ?? fallback)
      if (anchor === undefined) return previous
      const legs = previous.legs?.map((leg) => {
        const offset = leg.offset.trim() ? Number(leg.offset) : NaN
        const row = listed.find((row) => row.strike === anchor + offset)
        const contract = leg.optionType === 'CE' ? row?.ce : row?.pe
        const premium =
          contract?.symbol &&
          contract.exists !== false &&
          typeof contract.ltp === 'number' &&
          Number.isFinite(contract.ltp) &&
          contract.ltp > 0
            ? String(contract.ltp)
            : ''
        return { ...leg, premium }
      })
      const next = { ...previous, anchor: String(anchor), expiry, legs }
      return JSON.stringify(next) === JSON.stringify(previous) ? previous : next
    })
  }, [
    chain,
    expiry,
    legGeometry,
    draft.anchor,
    setDraft,
    selectedOption?.strike,
    selectedOption?.expiry,
  ])
  const unavailable = Boolean(chain) && (draft.legs ?? []).some((leg) => !leg.premium.trim())
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-3">
        <label className="space-y-1">
          <span>Strike price</span>
          <select
            aria-label="Strike price"
            className={control}
            value={strikes.includes(Number(draft.anchor)) ? draft.anchor : ''}
            disabled={!strikes.length}
            onChange={(event) =>
              setDraft((previous) => ({
                ...previous,
                anchor: event.target.value,
                legs: previous.legs?.map((leg) => ({ ...leg, premium: '' })),
              }))
            }
          >
            <option value="">
              {error
                ? 'Strikes unavailable'
                : strikes.length
                  ? 'Choose listed strike'
                  : 'Loading listed strikes…'}
            </option>
            {strikes.map((strike) => (
              <option key={strike} value={String(strike)}>
                {strike}
                {strike === chain?.atm_strike ? ' · ATM' : ''}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span>Expiry date</span>
          <select
            aria-label="Expiry date"
            className={control}
            value={expiry}
            disabled={!dates?.length}
            onChange={(event) =>
              setDraft((previous) => ({
                ...previous,
                expiry: event.target.value,
                anchor: '',
                legs: previous.legs?.map((leg) => ({ ...leg, premium: '' })),
              }))
            }
          >
            {!dates?.length && (
              <option value="">
                {error ? 'Expiries unavailable' : 'Loading listed expiries…'}
              </option>
            )}
            {dates?.map((date) => (
              <option key={date} value={date}>
                {date}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="text-muted-foreground">
        The nearest expiry and a strike near the current market price are selected for you. Changing
        the strike updates the option prices and example chart. Prices are the latest available
        quotes.
      </p>
      {unavailable && (
        <p className="text-muted-foreground">
          Some proposed leg strikes are not listed or have no usable quote. Their premiums remain
          blank.
        </p>
      )}
      {error && <p className="text-destructive">{error}</p>}
      <button
        type="button"
        className="text-xs underline underline-offset-2"
        onClick={() => setRefresh((value) => value + 1)}
      >
        Refresh listed strikes and quotes
      </button>
    </div>
  )
}
