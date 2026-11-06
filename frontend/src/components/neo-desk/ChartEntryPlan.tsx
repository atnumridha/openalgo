import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import type { OptionData } from '@/types/option-chain'
import { useChartContract } from './chartContract'
import { ChartToolPanel } from './ChartToolDock'
import { PremiumRiskPreview, type PremiumPlan } from './PremiumRiskPreview'
import {
  calculateEntryPlan,
  findAutomaticSetup,
  advanceFrozenPlan,
  type EntryPlan,
  type PlanBar,
  type PlanDirection,
  type PlanSession,
} from './chartTradePlan'

const ignoreLevels = () => {}
const format = (price: number) =>
  new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 8 }).format(
    price
  )
type TrendSource = { symbol: string; exchange: string }
export interface ChartEntryPlanProps {
  symbol: string
  exchange: string
  interval: string
  scope: string
  bars: readonly PlanBar[]
  ready: boolean
  tickSize?: number
  session?: PlanSession
  contract?: OptionData
  price?: number
  docked?: boolean
  trendSource?: TrendSource
  loadTrend?: (source: TrendSource, signal: AbortSignal) => Promise<PlanBar[]>
  onLevels: (plan: PremiumPlan | null) => void
}
export function ChartEntryPlan({
  symbol,
  exchange,
  interval,
  scope,
  bars,
  ready,
  tickSize,
  session,
  contract,
  price,
  docked = true,
  trendSource,
  loadTrend,
  onLevels,
}: ChartEntryPlanProps) {
  const owner = useAuthStore((s) => s.user?.username),
    appMode = useThemeStore((s) => s.appMode)
  const option =
      ['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCO'].includes(exchange) && /(CE|PE)$/.test(symbol),
    crypto = exchange === 'DELTA'
  const [mode, setMode] = useState<'external' | 'automatic'>('external')
  const [entry, setEntry] = useState(''),
    [direction, setDirection] = useState<PlanDirection>('long'),
    [show, setShow] = useState(true)
  const [automaticSnapshot, setAutomaticSnapshot] = useState<EntryPlan | null>(null)
  const [applied, setApplied] = useState<{
    entry: string
    direction: PlanDirection
    plan: EntryPlan
  } | null>(null)
  const seconds =
    (
      {
        '1m': 60,
        '3m': 180,
        '5m': 300,
        '15m': 900,
        '30m': 1800,
        '1h': 3600,
        '1d': 86400,
      } as Record<string, number>
    )[interval] ?? 300
  const metadata = useChartContract(
    symbol,
    exchange,
    tickSize && tickSize > 0
      ? { symbol, exchange, tick_size: tickSize, lotsize: contract?.lotsize }
      : undefined
  )
  const tick = metadata?.tick_size
  const feeContract =
    contract ??
    (metadata?.lotsize && metadata.lotsize > 0
      ? ({ symbol, lotsize: metadata.lotsize, tick_size: tick } as OptionData)
      : undefined)
  const trend = useQuery({
    queryKey: ['chart-entry-trend', owner, appMode, trendSource?.symbol, trendSource?.exchange],
    enabled: mode === 'automatic' && ready && !!trendSource && !!loadTrend,
    queryFn: ({ signal }) => loadTrend!(trendSource!, signal),
    staleTime: 20000,
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: mode === 'automatic' && ready ? 30000 : false,
  })
  const preview = useMemo(
    () =>
      calculateEntryPlan(bars, Number(entry), tick ?? 0, direction, seconds, session ?? !crypto),
    [bars, entry, tick, direction, seconds, crypto, session]
  )
  const hasUnderlyingTrend =
    !!trendSource && (trendSource.symbol !== symbol || trendSource.exchange !== exchange)
  const automatic = useMemo(
    () =>
      findAutomaticSetup(
        bars,
        trend.data ?? [],
        tick ?? 0,
        option ? (hasUnderlyingTrend ? (symbol.endsWith('CE') ? 'CE' : 'PE') : 'long') : 'both',
        seconds,
        session ?? !crypto
      ),
    [bars, trend.data, tick, option, symbol, seconds, session, crypto, hasUnderlyingTrend]
  )
  const frozenAutomatic = useMemo(
    () =>
      automaticSnapshot ? advanceFrozenPlan(automaticSnapshot, bars, tick ?? 0, seconds) : null,
    [automaticSnapshot, bars, tick, seconds]
  )
  useEffect(() => {
    if (mode !== 'automatic' || !ready || !automatic.plan || trend.isError) return
    if (
      !automaticSnapshot ||
      (automatic.plan.asOf > automaticSnapshot.asOf &&
        !['Armed', 'Entry touched'].includes(frozenAutomatic?.status ?? ''))
    )
      setAutomaticSnapshot(automatic.plan)
  }, [mode, ready, automatic.plan, automaticSnapshot, frozenAutomatic?.status, trend.isError])
  const automaticResult = frozenAutomatic ?? automatic
  const matches = applied?.entry === entry && applied.direction === direction
  useEffect(() => {
    if (mode !== 'external' || !ready || matches || !preview.plan) return
    const timer = setTimeout(() => setApplied({ entry, direction, plan: preview.plan! }), 150)
    return () => clearTimeout(timer)
  }, [mode, ready, matches, preview.plan, entry, direction])
  const plan = ready
    ? mode === 'external'
      ? matches
        ? applied.plan
        : null
      : !trend.isError
        ? automaticResult.plan
        : null
    : null
  useEffect(() => {
    onLevels(show && plan ? { entry: plan.entry, stop: plan.stop, target: plan.target } : null)
  }, [plan, show, onLevels])
  useEffect(() => () => onLevels(null), [onLevels])
  const reason = !ready
    ? 'Waiting for verified chart history. Planning is paused in replay or a selected historical range.'
    : !tick
      ? 'Waiting for verified contract price increment.'
      : mode === 'external'
        ? !entry
          ? 'Enter the actual entry price from your broker.'
          : !matches
            ? preview.reason || 'Calculating SL and target…'
            : ''
        : trend.isError
          ? 'Underlying / 15-minute trend history unavailable. Retrying with the next update.'
          : trend.isPending
            ? 'Loading confirmed 15-minute trend…'
            : automaticResult.reason
  const status = mode === 'external' ? 'Outside entry' : (automaticResult.status ?? 'Waiting')
  const crossed =
    plan && price && price > 0
      ? (plan.direction === 'long' ? price <= plan.stop : price >= plan.stop)
        ? 'Last available price is already beyond the calculated SL.'
        : (plan.direction === 'long' ? price >= plan.target : price <= plan.target)
          ? 'Last available price has already reached the calculated target.'
          : null
      : null
  const currency = crypto ? '$' : option ? '₹' : ''
  return (
    <ChartToolPanel
      floating={docked}
      label="Entry, SL and target"
      title={
        <>
          <span className="font-medium">Entry · SL · Target 1:2</span>
          {plan ? (
            <span className="ml-3 inline-flex gap-3 tabular-nums">
              <span className="text-blue-700 dark:text-blue-400">
                {currency}
                {format(plan.entry)}
              </span>
              <span className="text-red-700 dark:text-red-400">
                SL {currency}
                {format(plan.stop)}
              </span>
              <span className="text-emerald-700 dark:text-emerald-400">
                Target {currency}
                {format(plan.target)}
              </span>
            </span>
          ) : (
            <span className="ml-2 text-muted-foreground">
              {mode === 'external' ? 'Set your entry' : status}
            </span>
          )}
        </>
      }
    >
      <div className="space-y-3 p-3 text-xs">
        <div role="group" aria-label="Entry source" className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant={mode === 'external' ? 'secondary' : 'outline'}
            aria-pressed={mode === 'external'}
            onClick={() => setMode('external')}
          >
            Your entry / outside buy
          </Button>
          <Button
            size="sm"
            variant={mode === 'automatic' ? 'secondary' : 'outline'}
            aria-pressed={mode === 'automatic'}
            onClick={() => setMode('automatic')}
          >
            Automatic setup
          </Button>
        </div>
        <p className="text-muted-foreground">
          {symbol} · {interval} confirmed candles · ATR 14 · minimum stop distance 1.5 × ATR.{' '}
          {option
            ? 'Bought CE and PE both use a stop below premium entry.'
            : crypto
              ? 'BTC/ETH prices are in USD; this panel does not estimate INR fees or leveraged account risk.'
              : ['NSE_INDEX', 'BSE_INDEX'].includes(exchange)
                ? 'Index reference levels; option premiums have separate plans.'
                : 'Prices are for this symbol; contract size and fees are not inferred.'}
        </p>
        {mode === 'external' ? (
          <div className="flex flex-wrap items-end gap-3">
            <label className="space-y-1">
              <span className="block">Your entry price {currency}</span>
              <Input
                aria-label="Your entry price"
                type="number"
                min={tick ?? 0}
                step={tick ?? 'any'}
                value={entry}
                onChange={(e) => setEntry(e.target.value)}
                placeholder="Actual filled price"
                className="h-8 w-40 text-xs tabular-nums md:text-xs"
              />
            </label>
            {!option ? (
              <label className="space-y-1">
                <span className="block">Position direction</span>
                <select
                  aria-label="Position direction"
                  value={direction}
                  onChange={(e) => setDirection(e.target.value as PlanDirection)}
                  className="h-8 rounded-md border bg-background px-2"
                >
                  <option value="long">Long / buy</option>
                  <option value="short">Short / sell</option>
                </select>
              </label>
            ) : null}
            <Button
              size="sm"
              variant="outline"
              disabled={!ready || !preview.plan}
              onClick={() => preview.plan && setApplied({ entry, direction, plan: preview.plan })}
            >
              Recalculate SL and target
            </Button>
          </div>
        ) : (
          <p className="text-muted-foreground">
            Breakout → retest within 3 candles → entry one increment beyond retest. Unfilled setups
            expire after 2 candles. Uses confirmed 15-minute{' '}
            {hasUnderlyingTrend ? 'underlying' : 'chart price'} trend; chart touches are not broker
            fills.
          </p>
        )}
        <output role="status" className="block font-medium">
          {plan
            ? `${status} · ${plan.direction === 'long' ? 'Long' : 'Short'} · exact price risk/reward 1:2`
            : reason || status}
        </output>
        {crossed ? (
          <p role="note" className="text-amber-600 dark:text-amber-400">
            {crossed} Your entry and frozen plan have not been moved.
          </p>
        ) : null}
        {plan ? (
          <>
            <dl
              aria-label="Calculated chart levels"
              className="grid grid-cols-2 gap-3 rounded-md border bg-background p-3 tabular-nums sm:grid-cols-4"
            >
              <div>
                <dt className="text-muted-foreground">Entry</dt>
                <dd className="mt-1 font-semibold text-blue-700 dark:text-blue-400">
                  {currency}
                  {format(plan.entry)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">SL</dt>
                <dd className="mt-1 font-semibold text-red-700 dark:text-red-400">
                  {currency}
                  {format(plan.stop)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Target 1:2</dt>
                <dd className="mt-1 font-semibold text-emerald-700 dark:text-emerald-400">
                  {currency}
                  {format(plan.target)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Risk distance / unit</dt>
                <dd className="mt-1 font-semibold">
                  {currency}
                  {format(plan.risk)}
                </dd>
              </div>
            </dl>
            <p className="text-muted-foreground">
              ATR {format(plan.atr)} · structure {format(plan.structure)} · buffer{' '}
              {format(plan.buffer)}. Calculated from chart structure available now; the original
              outside trade time is not inferred. Levels stay fixed until you change entry/direction
              or recalculate.
            </p>
            <label className="flex min-h-8 items-center gap-2">
              <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
              Show entry, SL and target on chart
            </label>
            {option && ['NFO', 'BFO'].includes(exchange) ? (
              <PremiumRiskPreview
                key={`${scope}:${mode}:${plan.id}`}
                symbol={symbol}
                exchange={exchange}
                contract={feeContract}
                ready={ready}
                price={plan.entry}
                stops={[]}
                lockedPlan={plan}
                embedded
                entryLabel={
                  mode === 'external'
                    ? 'User provided outside entry'
                    : 'Confirmed breakout / retest entry'
                }
                onLevels={ignoreLevels}
              />
            ) : null}
          </>
        ) : null}
        <p className="text-muted-foreground">
          Planning levels only. No protective order is placed; a price gap or an unfilled exit can
          exceed the estimated loss. Capital / daily risk limits are not configured here.
        </p>
      </div>
    </ChartToolPanel>
  )
}
