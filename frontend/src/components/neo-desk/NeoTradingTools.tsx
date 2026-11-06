import { StrikeRsiData } from './StrikeRsiData'
import { mergeStrikeQuotes, useStrikeQuotes } from './useStrikeQuotes'
import { StrikePicker } from './StrikePicker'
import { SelectedOptionQuality } from './SelectedOptionQuality'
import { premiumMovement, premiumTone } from './PremiumQuote'
import { strikeRsiLabel, type StrikeRsiSnapshot } from './strikeRsi'
import { optionChainApi } from '@/api/option-chain'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import {
  rankOptionStrikes,
  strikeActivity,
  strikePremium,
  strikeSpread,
  totalStrikeActivity,
  type StrikeChoiceRow,
} from './strikeRanking'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { activeExpiries, nearestExpiry } from '@/lib/neoOptionSelection'
import type { OptionType } from '@/types/scalping'
import { INDICATORS } from '../chart-toolkit/nineIndicators'
import type { OptionReference } from '../chart-toolkit/ToolkitPanel'
export interface NeoChartTarget {
  loadSymbol: (instrument: { symbol: string; exchange: string }) => Promise<unknown>
  replayActive: () => boolean
  replayPickingBar: () => boolean
  dataUnavailable: () => boolean
  listIndicators: () => Array<{ id: string; indicatorId: string; name: string }>
  addIndicatorById: (id: string) => Promise<unknown>
  removeIndicatorById: (id: string) => unknown
}

const studies = ['neo-donchian', 'neo-structure', 'rsi']
const studyLabels: Record<string, string> = {
  'neo-toolkit': 'Option buying · RSI + MACD',
  'bb-chikou': 'BB + Chikou · BULL / BEAR',
  'candle-patterns': 'Candle patterns · BULL / BEAR',
  'candle-probability': 'Candlestick probability · 2R / 10 candles',
  ...Object.fromEntries(INDICATORS.map((item) => [item.id, `${item.short} · CALL / PUT`])),
  'neo-donchian': 'Donchian / EMA',
  'neo-structure': 'Fair Value Gaps / levels',
  rsi: 'RSI 14',
}
export function NeoTradingTools({
  target,
  revision,
  initialize = true,
  active = true,
  historyPending = false,
  shownSymbol,
  underlying = 'NIFTY',
  interval = '15m',
  toolkit = false,
  onOptionReference,
}: {
  target: () => NeoChartTarget | null
  revision: number
  initialize?: boolean
  active?: boolean
  historyPending?: boolean
  shownSymbol?: string
  underlying?: string
  interval?: string
  toolkit?: boolean
  onOptionReference?: (reference: OptionReference) => void
}) {
  const apiKey = useAuthStore((state) => state.apiKey)
  const username = useAuthStore((state) => state.user?.username)
  const appMode = useThemeStore((state) => state.appMode)
  const optionExchange = underlying === 'SENSEX' ? 'BFO' : 'NFO'
  const indexExchange = underlying === 'SENSEX' ? 'BSE_INDEX' : 'NSE_INDEX'
  const availableStudies = toolkit
    ? [
        'neo-toolkit',
        'bb-chikou',
        'candle-patterns',
        'candle-probability',
        ...studies,
        ...INDICATORS.map((item) => item.id),
      ]
    : studies
  const [expiry, setExpiry] = useState(''),
    [ce, setCe] = useState(''),
    [pe, setPe] = useState('')
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [shown, setShown] = useState('')
  const lastReadyRevision = useRef(revision)
  useEffect(() => {
    if (lastReadyRevision.current === revision) return
    lastReadyRevision.current = revision
    const pane = target()
    if (pane && !pane.dataUnavailable()) setError('')
  }, [revision, target])
  const [enabledStudies, setEnabledStudies] = useState<string[]>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('neo.native.chart.indicators') || 'null')
      if (toolkit && localStorage.getItem('neo.chart.toolkit.version') !== '2')
        return ['neo-toolkit']
      return Array.isArray(saved)
        ? saved.filter((id) => availableStudies.includes(id))
        : toolkit
          ? ['neo-toolkit']
          : studies
    } catch {
      return studies
    }
  })
  useEffect(() => {
    if (shownSymbol) setShown(shownSymbol)
  }, [shownSymbol])
  const initial = useRef(false),
    loading = useRef(false)
  const chartSequence = useRef(0)
  useEffect(
    () => () => {
      chartSequence.current++
    },
    []
  )
  const pendingExpiryChart = useRef<{ expiry: string; side: OptionType; strike: string } | null>(
    null
  )
  const expiriesQuery = useQuery({
    queryKey: ['scalping', 'expiry', optionExchange, underlying],
    enabled: active,
    queryFn: () => scalpingApi.getExpiry(underlying, optionExchange, 'options'),
    staleTime: 60000,
    refetchInterval: active ? 60000 : false,
    refetchOnWindowFocus: 'always',
  })
  const dates = useMemo(() => activeExpiries(expiriesQuery.data?.data || []), [expiriesQuery.data])
  useEffect(() => {
    if (dates.length && !dates.includes(expiry)) setExpiry(nearestExpiry(dates))
  }, [dates, expiry])
  const chainQuery = useQuery({
    queryKey: ['scalping', 'strikes', optionExchange, underlying, expiry],
    queryFn: () => scalpingApi.getStrikes(underlying, optionExchange, expiry, 20),
    enabled: active && Boolean(expiry),
    staleTime: 30000,
  })
  const fullChainQuery = useQuery({
    queryKey: ['chart-full-strikes', username, appMode, optionExchange, underlying, expiry],
    enabled: active && Boolean(expiry) && Boolean(apiKey),
    queryFn: async () => {
      const result = await optionChainApi.getOptionChain(
        apiKey!,
        underlying,
        optionExchange,
        expiry,
        null,
        { withGreeks: true }
      )
      if (
        result.status !== 'success' ||
        result.underlying !== underlying ||
        result.expiry_date !== expiry ||
        !Array.isArray(result.chain)
      )
        throw Error(result.message || 'Full option chain unavailable')
      return result
    },
    staleTime: 10000,
    refetchInterval: active ? 15000 : false,
    refetchOnWindowFocus: 'always',
    retry: false,
  })
  const catalog = fullChainQuery.data ?? chainQuery.data
  const quoteScope = JSON.stringify([username, appMode, underlying, optionExchange, expiry])
  const quoteSymbols = useMemo(() => (catalog?.chain ?? []).flatMap(row =>
    [row.ce?.symbol, row.pe?.symbol].filter((symbol): symbol is string => !!symbol)), [catalog])
  const quotes = useStrikeQuotes(quoteScope, optionExchange, quoteSymbols, active && !!apiKey)
  const rows: StrikeChoiceRow[] = useMemo(
    () => mergeStrikeQuotes([...(catalog?.chain || [])].sort((a, b) => a.strike - b.strike),
      quotes, fullChainQuery.data ? fullChainQuery.dataUpdatedAt : chainQuery.dataUpdatedAt),
    [catalog, quotes, fullChainQuery.data, fullChainQuery.dataUpdatedAt, chainQuery.dataUpdatedAt]
  )
  const rsiScope = JSON.stringify([username, appMode, underlying, optionExchange, expiry, interval])
  const [rsiSnapshot, setRsiSnapshot] = useState<StrikeRsiSnapshot | null>(null)
  const rsi = rsiSnapshot?.scope === rsiScope ? rsiSnapshot : null
  const rsiSymbols = useMemo(() => {
    const selected = [
      rows.find((row) => String(row.strike) === ce)?.ce?.symbol,
      rows.find((row) => String(row.strike) === pe)?.pe?.symbol,
    ]
    const ranked = rankOptionStrikes(rows, catalog?.atm_strike)
    return [
      ...new Set(
        [...selected, ...ranked.flatMap((row) => [row.ce?.symbol, row.pe?.symbol])].filter(
          (symbol): symbol is string => !!symbol
        )
      ),
    ]
  }, [rows, ce, pe, catalog?.atm_strike])
  useEffect(() => {
    if (!rows.length) return
    const atm = String(catalog?.atm_strike ?? rows[0].strike)
    setCe((old) => (rows.some((r) => String(r.strike) === old && r.ce?.symbol) ? old : atm))
    setPe((old) => (rows.some((r) => String(r.strike) === old && r.pe?.symbol) ? old : atm))
  }, [rows, catalog])
  useEffect(() => {
    const call = rows.find((r) => String(r.strike) === ce),
      put = rows.find((r) => String(r.strike) === pe)
    onOptionReference?.({
      underlying,
      exchange: indexExchange,
      optionExchange,
      expiry,
      ce: call?.ce?.symbol
        ? {
            symbol: call.ce.symbol,
            strike: call.strike,
            contract:
              fullChainQuery.data?.chain.find((row) => row.strike === call.strike)?.ce ?? undefined,
          }
        : undefined,
      pe: put?.pe?.symbol
        ? {
            symbol: put.pe.symbol,
            strike: put.strike,
            contract:
              fullChainQuery.data?.chain.find((row) => row.strike === put.strike)?.pe ?? undefined,
          }
        : undefined,
    })
  }, [
    rows,
    ce,
    pe,
    expiry,
    underlying,
    indexExchange,
    optionExchange,
    onOptionReference,
    fullChainQuery.data,
  ])
  // Match the broker chain's nearest-ATM convention, not the option premium.
  function strikeLabel(row: StrikeChoiceRow, side: OptionType): string {
    const atm = catalog?.atm_strike
    if (atm == null || !Number.isFinite(atm) || atm <= 0) return 'Unclassified'
    const reported = (side === 'CE' ? row.ce : row.pe)?.label
    if (reported && /^(ATM|ITM[0-9]*|OTM[0-9]*)$/.test(reported)) return reported
    if (row.strike === atm) return 'ATM'
    return (side === 'CE' ? row.strike < atm : row.strike > atm) ? 'ITM' : 'OTM'
  }
  async function applyStudies(pane: NeoChartTarget) {
    for (const id of availableStudies) {
      const existing = pane.listIndicators().filter((s) => s.indicatorId === id)
      if (enabledStudies.includes(id)) {
        if (!existing.length) await pane.addIndicatorById(id)
      } else {
        for (const item of existing) pane.removeIndicatorById(item.id)
      }
    }
  }
  async function toggleStudy(id: string, on: boolean) {
    if (loading.current) return
    const pane = target()
    if (!pane || pane.dataUnavailable()) {
      setError('Wait for chart prices before changing overlays.')
      return
    }
    loading.current = true
    setBusy(true)
    setError('')
    try {
      if (on && !pane.listIndicators().some((s) => s.indicatorId === id))
        await pane.addIndicatorById(id)
      if (!on)
        for (const item of pane.listIndicators().filter((s) => s.indicatorId === id))
          pane.removeIndicatorById(item.id)
      const next = on
        ? [...new Set([...enabledStudies, id])]
        : enabledStudies.filter((item) => item !== id)
      setEnabledStudies(next)
      try {
        localStorage.setItem('neo.native.chart.indicators', JSON.stringify(next))
      } catch {
        /* This browser still keeps the choice for the current view. */
      }
    } catch {
      setError('This overlay could not be changed. Open Indicators or retry after reconnecting.')
    } finally {
      loading.current = false
      setBusy(false)
    }
  }
  async function chart(which: 'INDEX' | 'CE' | 'PE', selectedStrike?: string) {
    const pane = target()
    if (!pane || pane.replayActive() || pane.replayPickingBar()) {
      setError('Finish loading or stop chart replay before changing the contract.')
      return
    }
    const leg =
      which === 'INDEX'
        ? { symbol: underlying, exchange: indexExchange }
        : (() => {
            const row = rows.find(
              (r) => String(r.strike) === (selectedStrike ?? (which === 'CE' ? ce : pe))
            )
            const symbol = which === 'CE' ? row?.ce?.symbol : row?.pe?.symbol
            return symbol ? { symbol, exchange: optionExchange } : null
          })()
    if (!leg) {
      setError('Choose a listed strike for this expiry.')
      return
    }
    // An explicit valid selection owns initialization, even after restored history failed.
    initial.current = true
    const version = ++chartSequence.current
    loading.current = true
    setBusy(true)
    setError('')
    try {
      await pane.loadSymbol(leg)
      if (version !== chartSequence.current) return
      await applyStudies(pane)
      if (version !== chartSequence.current) return
      if (pane.dataUnavailable())
        throw Error(
          'Prices are unavailable for this contract. Choose another listed strike or refresh broker data.'
        )
      setShown(leg.symbol)
    } catch {
      if (version !== chartSequence.current) return
      setError(
        'The chart could not load this contract and studies. Refresh the connection or choose another listed strike.'
      )
    } finally {
      if (version === chartSequence.current) {
        loading.current = false
        setBusy(false)
      }
    }
  }
  // Reload a premium only after the newly selected expiry's contract list arrives.
  // biome-ignore lint/correctness/useExhaustiveDependencies: chart reads the current catalog; only explicit expiry selection queues this action
  useEffect(() => {
    const pending = pendingExpiryChart.current
    if (!pending || pending.expiry !== expiry || catalog?.expiry_date !== expiry) return
    const listed = rankOptionStrikes(rows, catalog.atm_strike, pending.side)
    const chosen =
      listed.find((row) => String(row.strike) === pending.strike) ??
      listed.find((row) => row.strike === catalog.atm_strike) ??
      listed[0]
    if (!chosen) return
    pendingExpiryChart.current = null
    const strike = String(chosen.strike)
    if (pending.side === 'CE') setCe(strike)
    else setPe(strike)
    void chart(pending.side, strike)
  }, [expiry, catalog, rows, busy])
  // Initial native chart readiness is delivered by the workspace revision.
  // biome-ignore lint/correctness/useExhaustiveDependencies: revision follows native pane readiness; initialize once
  useEffect(() => {
    if (!initialize || initial.current) return
    const tryDefault = () => {
      const pane = target()
      if (
        !initial.current &&
        pane &&
        !pane.dataUnavailable() &&
        !pane.replayActive() &&
        !pane.replayPickingBar()
      ) {
        initial.current = true
        void chart('INDEX')
      }
    }
    tryDefault()
    if (!initialize || initial.current) return
    const timer = setInterval(() => {
      tryDefault()
      if (initial.current) clearInterval(timer)
    }, 250)
    return () => clearInterval(timer)
  }, [revision, target, initialize])
  const problem =
    error ||
    ((expiriesQuery.error || chainQuery.error) && !catalog
      ? `Could not load ${underlying} expiries or strikes. Refresh broker data.`
      : '')
  return (
    <section
      aria-label={`${underlying} chart selection`}
      className="shrink-0 border-b bg-card px-3 py-2"
    >
      <StrikeRsiData
        key={rsiScope}
        scope={rsiScope}
        exchange={optionExchange}
        interval={interval}
        symbols={rsiSymbols}
        active={active && Boolean(apiKey) && Boolean(expiry)}
        loadPaused={busy || historyPending}
        onSnapshot={setRsiSnapshot}
      />
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="neo-chart-expiry" className="text-xs text-muted-foreground">
            {underlying} expiry
          </Label>
          <select
            id="neo-chart-expiry"
            value={expiry}
            onChange={(e) => {
              const next = e.target.value
              const side = shown.endsWith('CE') ? 'CE' : shown.endsWith('PE') ? 'PE' : null
              pendingExpiryChart.current = side
                ? { expiry: next, side, strike: side === 'CE' ? ce : pe }
                : null
              setExpiry(next)
            }}
            disabled={!dates.length}
            className="block h-9 min-w-28 rounded-md border bg-background px-2 text-sm"
          >
            {dates.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        {(['CE', 'PE'] as const).map((side) => (
          <div key={side} className="min-w-0 max-w-full space-y-1">
            <Label htmlFor={`neo-chart-${side}`} className="text-xs text-muted-foreground">
              {side} strike
            </Label>
            <StrikePicker
              id={`neo-chart-${side}`}
              side={side}
              value={side === 'CE' ? ce : pe}
              onValueChange={(strike) => {
                pendingExpiryChart.current = null
                if (side === 'CE') setCe(strike)
                else setPe(strike)
                void chart(side, strike)
              }}
              disabled={!rows.length}
              options={rankOptionStrikes(rows, catalog?.atm_strike, side).map((r) => ({
                value: String(r.strike),
                moneyness: strikeLabel(r, side),
                premium: strikePremium(
                  fullChainQuery.data ? (side === 'CE' ? r.ce : r.pe)?.ltp : undefined
                ),
                spread: strikeSpread(
                  fullChainQuery.data ? (side === 'CE' ? r.ce : r.pe) : undefined
                ),
                change: premiumMovement(
                  (side === 'CE' ? r.ce : r.pe)?.ltp,
                  (side === 'CE' ? r.ce : r.pe)?.prev_close
                ).percentLabel,
                changeTone: premiumTone(
                  premiumMovement(
                    (side === 'CE' ? r.ce : r.pe)?.ltp,
                    (side === 'CE' ? r.ce : r.pe)?.prev_close
                  ).change
                ),
                rsi: strikeRsiLabel(rsi?.values[(side === 'CE' ? r.ce : r.pe)?.symbol ?? '']),
                volume: strikeActivity(
                  fullChainQuery.data ? totalStrikeActivity(r, 'volume') : undefined
                ),
                oi: strikeActivity(fullChainQuery.data ? totalStrikeActivity(r, 'oi') : undefined),
              }))}
            />
          </div>
        ))}
        <div
          className="flex items-center gap-1 rounded-md border bg-background p-0.5"
          role="toolbar"
          aria-label="Chart instrument"
        >
          {(['INDEX', 'CE', 'PE'] as const).map((which) => {
            const active = which === 'INDEX' ? shown === 'NIFTY' : shown.endsWith(which)
            return (
              <Button
                key={which}
                size="sm"
                variant={active ? 'secondary' : 'ghost'}
                className="h-8"
                aria-label={which === 'INDEX' ? 'Chart NIFTY' : `Chart ${which}`}
                aria-pressed={active}
                disabled={
                  which !== 'INDEX' && (!(which === 'CE' ? ce : pe) || chainQuery.isFetching)
                }
                onClick={() => void chart(which)}
              >
                {which === 'INDEX' ? underlying : which}
              </Button>
            )
          })}
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="h-9"
          aria-label="Refresh broker data"
          disabled={busy}
          onClick={() => {
            void expiriesQuery.refetch()
            void chainQuery.refetch()
            if (apiKey && expiry) void fullChainQuery.refetch()
          }}
        >
          Refresh
        </Button>
        <details className="relative text-xs text-muted-foreground">
          <summary className="flex h-9 cursor-pointer items-center rounded-md px-2 focus-visible:outline focus-visible:outline-ring">
            Chart guide
          </summary>
          <div className="absolute right-0 top-10 z-50 w-72 space-y-2 rounded-md border bg-popover p-3 text-popover-foreground shadow-md">
            <p>
              ATM is the nearest strike. ITM and OTM numbers count listed strikes from ATM; call and
              put directions differ. All listed strikes are ranked by combined CE + PE volume, then
              combined OI, with nearest ATM breaking exact ties. Premiums show each contract's
              latest broker quote. Streaming prices update about once a second; spread, volume, OI and ATM labels refresh every 15 seconds. RSI 14 follows the
              selected timeframe and each contract's own candles. Live RSI uses fresh streamed
              quotes; Closed is the last completed-candle RSI. Missing or short histories show —.
              Histories load in batches, selected / most traded first.
            </p>
            <p>
              Faint green / red zones show the three nearest unfilled FVGs. Compact arrows keep
              candles clear; open the FVG legend for prices and partial fills. Dashed support and
              resistance lines mark confirmed pivots, which may attract liquidity.
            </p>
            <p>
              {shown || 'NIFTY charts'} · nearest active expiry by default; expiry list newest
              first. Donchian 20 / EMA 200, FVG / structure and RSI 14. These buttons select charts;
              strategy execution uses confirmed NIFTY 15m signals.
            </p>
          </div>
        </details>
        {busy ? <output className="text-xs text-muted-foreground">Loading chart…</output> : null}
      </div>
      <p className="mt-1 text-xs text-muted-foreground" aria-live="polite">
        {fullChainQuery.data
          ? `${rows.length} strikes · most traded first · volume, then OI (CE + PE totals)`
          : fullChainQuery.isFetching
            ? 'Loading all strikes and OI / volume… Nearby strikes remain selectable.'
            : 'Nearby strikes · full OI / volume unavailable'}
        {fullChainQuery.data ? ` · snapshot ${new Date(fullChainQuery.dataUpdatedAt).toLocaleTimeString('en-IN', { hour12: false })} · auto 15s` : ''}
        {fullChainQuery.isFetching && fullChainQuery.data ? ' · updating activity…' : ''}
        {fullChainQuery.isError ? ' · Could not refresh all strikes; use Refresh to retry.' : ''}
      </p>
      {rsiSymbols.length ? (
        <p className="mt-1 text-xs text-muted-foreground" aria-label="Strike RSI status">
          RSI 14 · {interval} ·{' '}
          {Object.values(rsi?.values ?? {}).filter((value) => value.value != null).length}/
          {rsiSymbols.length} ready · Live = current candle; Closed = completed candles
        </p>
      ) : null}
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
        {rows.length ? (
          <fieldset
            aria-label="Selected option moneyness"
            className="flex flex-wrap items-center gap-2 text-xs"
          >
            <span className="text-muted-foreground">
              ATM {catalog?.atm_strike ?? 'unavailable'}
            </span>
            {(['CE', 'PE'] as const).map((side) => {
              const row = rows.find((r) => String(r.strike) === (side === 'CE' ? ce : pe))
              return row ? (
                <Badge key={side} variant="outline" className="font-normal tabular-nums">
                  {side} {row.strike} · {strikeLabel(row, side)} ·{' '}
                  <span
                    className={premiumTone(
                      premiumMovement(
                        (side === 'CE' ? row.ce : row.pe)?.ltp,
                        (side === 'CE' ? row.ce : row.pe)?.prev_close
                      ).change
                    )}
                  >
                    {strikePremium(
                      fullChainQuery.data ? (side === 'CE' ? row.ce : row.pe)?.ltp : undefined
                    )}{' '}
                    {
                      premiumMovement(
                        (side === 'CE' ? row.ce : row.pe)?.ltp,
                        (side === 'CE' ? row.ce : row.pe)?.prev_close
                      ).percentLabel
                    }
                  </span>{' '}
                  · {strikeRsiLabel(rsi?.values[(side === 'CE' ? row.ce : row.pe)?.symbol ?? ''])}
                </Badge>
              ) : null
            })}
          </fieldset>
        ) : null}
        <fieldset aria-label="Chart overlays" className="flex flex-wrap items-center gap-3">
          {availableStudies.map((id) => (
            <Label
              key={id}
              htmlFor={`neo-study-${id}`}
              className="flex min-h-8 cursor-pointer items-center gap-2 text-xs font-normal text-muted-foreground"
            >
              <Checkbox
                id={`neo-study-${id}`}
                checked={enabledStudies.includes(id)}
                disabled={busy || !shown || target()?.dataUnavailable()}
                onCheckedChange={(on) => void toggleStudy(id, on === true)}
              />
              {studyLabels[id]}
            </Label>
          ))}
        </fieldset>
      </div>
      <SelectedOptionQuality
        key={`${optionExchange}:${underlying}:${expiry}`}
        data={fullChainQuery.data}
        ce={fullChainQuery.data?.chain.find((row) => String(row.strike) === ce)?.ce ?? undefined}
        pe={fullChainQuery.data?.chain.find((row) => String(row.strike) === pe)?.pe ?? undefined}
        exchange={optionExchange}
        receivedAt={fullChainQuery.dataUpdatedAt}
      />
      {problem ? (
        <p role="alert" className="mt-1 text-sm text-destructive">
          {problem}
        </p>
      ) : null}
    </section>
  )
}
