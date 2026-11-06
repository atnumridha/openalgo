import { ChartIndexQuote } from './ChartIndexQuote'
import { canAutoRetryHistory, chartHistoryRetryDelay } from './chartHistoryRecovery'
import { INDICATORS } from '../chart-toolkit/nineIndicators'
import { useQueryClient } from '@tanstack/react-query'
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  lazy,
  Suspense,
} from 'react'
import { Maximize2, Minimize2, SlidersHorizontal, MoreHorizontal, Search } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router'
import { parseChartTarget, type ChartTarget } from '../screener/chartTarget'
import { resolveIndicatorChart } from '../chart-toolkit/indicatorChartContext'
import { scalpingApi } from '@/api/scalping'
import { Navbar } from '@/components/layout/Navbar'
import { NeoStrategyControls } from '@/components/scalping/NeoStrategyControls'
import { Button } from '@/components/ui/button'
import { webClient } from '@/api/client'
import { Checkbox } from '@/components/ui/checkbox'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { NeoMarketChart } from './NeoMarketChart'
import {
  CHART_STUDIES,
  chartStudyLabel,
  readDeltaStudyPreferences,
  saveDeltaStudyPreferences,
  withStandardEmaDefault,
  saveStandardStudyPreferences,
} from './chartStudyChoices'
import { NeoStrategyResearch } from './NeoStrategyResearch'
import { type NeoChartTarget, NeoTradingTools } from './NeoTradingTools'
import { readDeltaHistory } from '../chart-toolkit/deltaFeed'
import { readDeltaProducts } from '../chart-toolkit/deltaProducts'
import type { SearchRow } from '@/lib/trading/terminal'
import type { OptionReference } from '../chart-toolkit/ToolkitPanel'

const SymbolSearchDialog = lazy(() =>
  import('@/components/trading/SymbolSearchDialog').then((m) => ({ default: m.SymbolSearchDialog }))
)
export const searchChartSymbols = async (
  query: string,
  exchange?: string
): Promise<SearchRow[]> => {
  const normalized = query.trim().toUpperCase()
  if (normalized.length < 2) return []
  const delta = async (): Promise<SearchRow[]> =>
    (await readDeltaProducts())
      .filter((product) => product.symbol.includes(normalized))
      .map((product) => ({
        symbol: product.symbol,
        exchange: 'DELTA',
        name: product.name,
        instrumenttype: 'PERP',
        tick_size: product.tick_size,
      }))
  const broker = async (): Promise<SearchRow[]> => {
    const response = await webClient.get('/neodesk/api/chart/search', {
      params: { query, exchange },
      timeout: 10000,
    })
    return response.data.data ?? []
  }
  if (exchange === 'DELTA' || exchange === 'CRYPTO') return delta()
  if (exchange) return broker()
  // Search every chart venue from the existing dialog, even while an index is selected.
  const results = await Promise.allSettled([broker(), delta()])
  return results.flatMap((result) => (result.status === 'fulfilled' ? result.value : []))
}
type Instrument = { symbol: string; exchange: string }
type History = Awaited<ReturnType<typeof scalpingApi.getHistory>> & { observedAt?: number }
const defaults = [
  'strategies-51-guide',
  'book-pattern-risk-guide',
  'candle-patterns',
  ...INDICATORS.map((item) => item.id),
  'bb-chikou',
  'candle-probability',
  'neo-toolkit',
  'neo-donchian',
  'neo-structure',
  'rsi',
  'volume',
  'ema-9-15',
  'fibonacci-pivots',
]
export function NeoTradingViewWorkspace() {
  const location = useLocation(),
    navigate = useNavigate(),
    target = parseChartTarget(location.search)
  // Internal selection updates replace the address while retaining this workspace.
  // External links and Back still remount to restore their exact chart target.
  const workspaceKey =
    location.state?.neoChartWorkspace ?? (target ? JSON.stringify(target) : 'default')
  const syncTarget = useCallback(
    (instrument: Instrument, interval: string) => {
      const params = new URLSearchParams(location.search)
      if (
        params.get('symbol') === instrument.symbol &&
        params.get('exchange') === instrument.exchange &&
        params.get('interval') === interval
      )
        return
      params.set('symbol', instrument.symbol)
      params.set('exchange', instrument.exchange)
      params.set('interval', interval)
      void navigate(
        { pathname: location.pathname, search: `?${params}`, hash: location.hash },
        {
          replace: true,
          state: { ...location.state, neoChartWorkspace: workspaceKey },
        }
      )
    },
    [location.pathname, location.search, location.hash, location.state, navigate, workspaceKey]
  )
  return <TradingWorkspace key={workspaceKey} target={target} syncTarget={syncTarget} />
}
function TradingWorkspace({
  target: initialTarget,
  syncTarget,
}: {
  target: ChartTarget | null
  syncTarget: (instrument: Instrument, interval: string) => void
}) {
  const queryClient = useQueryClient()
  const workspace = useRef<HTMLElement>(null)
  const [chartFocus, setChartFocus] = useState(true)
  const [chartDark, setChartDark] = useState(true)
  const [optionsOpen, setOptionsOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const optionsDrawer = useRef<HTMLElement>(null)
  const optionsButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (optionsOpen) optionsDrawer.current?.focus()
  }, [optionsOpen])
  const closeOptions = useCallback(() => {
    if (optionsDrawer.current && !optionsDrawer.current.hidden) optionsButton.current?.focus()
    setOptionsOpen(false)
  }, [])
  const [loadingSeconds, setLoadingSeconds] = useState(0)
  const [fullscreen, setFullscreen] = useState(false)
  useEffect(() => {
    const changed = () => setFullscreen(document.fullscreenElement === workspace.current)
    document.addEventListener('fullscreenchange', changed)
    return () => document.removeEventListener('fullscreenchange', changed)
  }, [])
  const toggleFullscreen = async () => {
    setChartFocus(true)
    if (document.fullscreenElement) await document.exitFullscreen?.()
    else await workspace.current?.requestFullscreen?.()
  }
  const [underlying, setUnderlying] = useState(() =>
    initialTarget
      ? (resolveIndicatorChart(initialTarget.symbol, initialTarget.exchange).underlying?.symbol ??
        initialTarget.symbol)
      : 'NIFTY'
  )
  const optionMarket = ['NIFTY', 'BANKNIFTY', 'SENSEX'].includes(underlying)
  const [optionReference, setOptionReference] = useState<OptionReference>()
  const [instrument, setInstrument] = useState<Instrument>({
      symbol: initialTarget?.symbol ?? 'NIFTY',
      exchange: initialTarget?.exchange ?? 'NSE_INDEX',
    }),
    [interval, setInterval] = useState<string>(initialTarget?.interval ?? '15m'),
    [history, setHistory] = useState<History>(),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(''),
    [retryable, setRetryable] = useState(false),
    [recoveryAttempt, setRecoveryAttempt] = useState(0),
    [revision, setRevision] = useState(0)
  const crypto = instrument.exchange === 'DELTA'
  useEffect(() => {
    syncTarget(instrument, interval)
  }, [syncTarget, instrument, interval])
  useEffect(() => {
    if (!loading) {
      setLoadingSeconds(0)
      return
    }
    const started = Date.now()
    const timer = window.setInterval(
      () => setLoadingSeconds(Math.floor((Date.now() - started) / 1000)),
      1000
    )
    return () => window.clearInterval(timer)
  }, [loading])
  const [standardStudies, setStandardStudies] = useState<string[]>(() => {
    if (initialTarget?.candleStudy) return ['candle-probability']
    try {
      const stored = JSON.parse(localStorage.getItem('neo.native.chart.indicators') || 'null')
      if (localStorage.getItem('neo.chart.toolkit.version') !== '2')
        return withStandardEmaDefault(['neo-toolkit', 'candle-patterns'])
      return withStandardEmaDefault(Array.isArray(stored)
        ? stored.filter((id) => defaults.includes(id))
        : ['neo-toolkit', 'candle-patterns'])
    } catch {
      return withStandardEmaDefault(['neo-toolkit', 'candle-patterns'])
    }
  })
  const [deltaStudies, setDeltaStudies] = useState<string[]>(() => {
    const selected = readDeltaStudyPreferences(standardStudies)
    return initialTarget?.candleStudy ? [...new Set([...selected, 'candle-probability'])] : selected
  })
  const studies = crypto ? deltaStudies : standardStudies
  const setStudies = crypto ? setDeltaStudies : setStandardStudies
  useEffect(() => {
    if (crypto) saveDeltaStudyPreferences(studies)
    else saveStandardStudyPreferences(studies)
    localStorage.setItem('neo.chart.toolkit.version', '2')
  }, [studies, crypto])
  const state = useRef({ instrument, interval, history, studies }),
    sequence = useRef(0)
  state.current = { instrument, interval, history, studies }
  const load = useCallback(
    async (selected: Instrument, recovering = false) => {
      if (!recovering) closeOptions()
      if (!recovering) setRecoveryAttempt(0)
      const version = ++sequence.current
      setLoading(true)
      setError('')
      setRetryable(false)
      setInstrument(selected)
      setHistory(undefined)
      state.current = { ...state.current, instrument: selected, history: undefined }
      try {
        const selectedInterval = state.current.interval
        const result = await queryClient.fetchQuery({
          queryKey: [
            'neo-tv-history',
            selected.exchange,
            selected.symbol,
            selectedInterval,
            undefined,
            undefined,
          ],
          queryFn: async ({ signal }) => {
            const requestObservedAt = Date.now() / 1000
            const value =
              selected.exchange === 'DELTA'
                ? await readDeltaHistory(
                    selected.symbol,
                    selectedInterval,
                    undefined,
                    AbortSignal.any([signal, AbortSignal.timeout(12000)])
                  )
                : await scalpingApi.getHistory(
                    selected.symbol,
                    selected.exchange,
                    selectedInterval,
                    undefined,
                    // Full option history can take 15–20s even when Neo succeeds.
                    { signal, timeoutMs: 30000 }
                  )
            if (value.status !== 'success')
              throw Error(value.message || 'Chart history unavailable')
            return { ...value, observedAt: requestObservedAt }
          },
          staleTime: 20000,
          retry: false,
        })
        if (version !== sequence.current) return
        if (result.status !== 'success' || !result.candles?.length)
          throw Error(
            result.message ||
              'No candles for this instrument. Choose another strike or refresh history.'
          )
        setInstrument(selected)
        setHistory(result)
        state.current = { ...state.current, instrument: selected, history: result }
        setRevision((n) => n + 1)
      } catch (e) {
        if (version === sequence.current) {
          setRetryable(canAutoRetryHistory(e))
          setError(
            canAutoRetryHistory(e)
              ? 'Broker candles are delayed. Retrying automatically.'
              : (e as Error).message
          )
        }
        throw e
      } finally {
        if (version === sequence.current) setLoading(false)
      }
    },
    [queryClient, closeOptions]
  )
  // biome-ignore lint/correctness/useExhaustiveDependencies: a timeframe change must request the current contract again
  useEffect(() => {
    void load(state.current.instrument).catch(() => {})
  }, [interval, load])
  // biome-ignore lint/correctness/useExhaustiveDependencies: timeframe changes must cancel the prior recovery timer
  useEffect(() => {
    if (!error || !retryable || loading) return
    const version = sequence.current
    const timer = window.setTimeout(() => {
      if (version !== sequence.current) return
      setRecoveryAttempt((attempt) => attempt + 1)
      void load(instrument, true).catch(() => {})
    }, chartHistoryRetryDelay(recoveryAttempt))
    return () => window.clearTimeout(timer)
  }, [error, retryable, loading, instrument, interval, load, recoveryAttempt])
  useEffect(
    () => () => {
      sequence.current++
    },
    []
  )
  const adapter = useMemo<NeoChartTarget>(
    () => ({
      loadSymbol: load,
      replayActive: () => false,
      replayPickingBar: () => false,
      dataUnavailable: () => !state.current.history?.candles.length,
      listIndicators: () => state.current.studies.map((id) => ({ id, indicatorId: id, name: id })),
      addIndicatorById: async (id) => {
        const next = [...new Set([...state.current.studies, id])]
        state.current.studies = next
        setStudies(next)
      },
      removeIndicatorById: (id) => {
        const next = state.current.studies.filter((x) => x !== id)
        state.current.studies = next
        setStudies(next)
      },
    }),
    [load, setStudies]
  )
  const target = useCallback(() => adapter, [adapter])
  return (
    <div className="flex h-dvh min-h-0 flex-col overflow-hidden bg-background">
      {!fullscreen ? (
        <div className="shrink-0">
          <Navbar fluid />
        </div>
      ) : null}
      <main
        ref={workspace}
        aria-label={
          fullscreen
            ? 'Full-screen chart workspace'
            : chartFocus
              ? 'OpenAlgo chart workspace'
              : 'Market analysis workspace'
        }
        style={
          chartFocus && chartDark
            ? ({
                '--background': '#131722',
                '--card': '#181c27',
                '--card-foreground': '#d1d4dc',
                '--popover': '#181c27',
                '--popover-foreground': '#d1d4dc',
                '--border': '#2a2e39',
                '--muted': '#242936',
                '--muted-foreground': '#959bad',
                '--foreground': '#d1d4dc',
              } as CSSProperties)
            : undefined
        }
        className={`${chartFocus && chartDark ? 'dark' : ''} flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden ${fullscreen ? 'h-dvh' : ''} bg-background text-foreground`}
      >
        <div className="relative z-40 flex min-h-11 shrink-0 flex-wrap items-center gap-3 border-b bg-background px-3 py-1">
          <div>
            <h1 className="pr-3 text-xs font-semibold tracking-tight text-muted-foreground">
              {chartFocus ? 'OpenAlgo' : 'Market analysis workspace'}
            </h1>
          </div>
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
            {loading ? (
              <output className="text-xs text-muted-foreground">
                Loading candles{loadingSeconds ? ` · ${loadingSeconds}s` : '…'}
              </output>
            ) : null}
            <label htmlFor="neo-chart-market" className="sr-only">
              Market
            </label>
            <select
              id="neo-chart-market"
              value={underlying}
              className="h-8 cursor-pointer rounded border-0 bg-background px-2 text-xs font-semibold focus-visible:outline focus-visible:outline-ring"
              onChange={(e) => {
                const value = e.target.value
                setUnderlying(value)
                void load({
                  symbol: value,
                  exchange:
                    value === underlying
                      ? instrument.exchange
                      : ['BTCUSD', 'ETHUSD', 'XAUTUSD'].includes(value)
                        ? 'DELTA'
                        : value === 'SENSEX'
                          ? 'BSE_INDEX'
                          : 'NSE_INDEX',
                }).catch(() => {})
              }}
            >
              {!['NIFTY', 'BANKNIFTY', 'SENSEX', 'BTCUSD', 'ETHUSD', 'XAUTUSD'].includes(
                underlying
              ) ? (
                <option value={underlying}>{underlying}</option>
              ) : null}
              {['NIFTY', 'BANKNIFTY', 'SENSEX', 'BTCUSD', 'ETHUSD', 'XAUTUSD'].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
            <label htmlFor="neo-tv-timeframe" className="sr-only">
              Timeframe
            </label>
            <select
              id="neo-tv-timeframe"
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
              className="h-8 cursor-pointer rounded border-0 border-l bg-background px-2 text-xs focus-visible:outline focus-visible:outline-ring"
            >
              {['1m', '3m', '5m', '15m', '30m', '1h', '1d'].map((value) => (
                <option key={value} value={value}>
                  {value === '1d' ? 'Daily' : value}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="ghost"
              className="h-8 gap-1.5 px-2 text-xs"
              onClick={() => setSearchOpen(true)}
              aria-label="Search any symbol"
            >
              <Search className="size-3.5" aria-hidden="true" />
              Search
            </Button>
            {optionMarket ? (
              <ChartIndexQuote symbol={underlying} />
            ) : (
              <span className="text-xs text-muted-foreground">{instrument.exchange}</span>
            )}
            <Popover>
              <PopoverTrigger asChild>
                <Button size="sm" variant="ghost" className="h-8 px-2 text-xs">
                  Indicators
                </Button>
              </PopoverTrigger>
              <PopoverContent
                align="end"
                className="max-h-[min(28rem,70dvh)] w-80 overflow-auto p-3"
                container={document.fullscreenElement as HTMLElement | null}
              >
                <div className="grid gap-2">
                  {CHART_STUDIES.map(([id, label]) => (
                    <label
                      key={id}
                      className="flex min-h-8 cursor-pointer items-center gap-2 text-xs"
                    >
                      <Checkbox
                        checked={studies.includes(id)}
                        onCheckedChange={(on) =>
                          setStudies((old) =>
                            on ? [...new Set([...old, id])] : old.filter((x) => x !== id)
                          )
                        }
                      />
                      {chartStudyLabel(id, label, crypto)}
                    </label>
                  ))}
                </div>
              </PopoverContent>
            </Popover>
            <span className="min-w-0 flex-1" />
            {optionMarket ? (
              <Button
                ref={optionsButton}
                size="sm"
                variant="ghost"
                className="h-8 gap-1.5 px-2 text-xs"
                aria-expanded={optionsOpen}
                onClick={() => setOptionsOpen((open) => !open)}
              >
                <SlidersHorizontal aria-hidden="true" className="size-3.5" />
                Options
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="ghost"
              className="size-8 p-0"
              aria-label={fullscreen ? 'Exit full screen' : 'Full screen'}
              title={fullscreen ? 'Exit full screen' : 'Full screen'}
              onClick={() => void toggleFullscreen().catch(() => {})}
            >
              {fullscreen ? (
                <Minimize2 aria-hidden="true" className="size-4" />
              ) : (
                <Maximize2 aria-hidden="true" className="size-4" />
              )}
            </Button>
            <details className="relative z-40 text-xs">
              <summary
                aria-label="More"
                title="More"
                className="flex size-8 cursor-pointer list-none items-center justify-center rounded hover:bg-muted focus-visible:outline focus-visible:outline-ring [&::-webkit-details-marker]:hidden"
              >
                <MoreHorizontal aria-hidden="true" className="size-4" />
                <span className="sr-only">More</span>
              </summary>
              <div className="absolute right-0 top-full mt-2 flex min-w-48 flex-col items-stretch gap-1 rounded-md border bg-card p-2 shadow-xl">
                <Button size="sm" variant="ghost" onClick={() => setChartDark((dark) => !dark)}>
                  {chartDark ? 'Light chart' : 'Dark chart'}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setChartFocus((focus) => !focus)}>
                  {chartFocus ? 'Workspace' : 'Chart view'}
                </Button>
                <Button size="sm" variant="outline" asChild>
                  <Link to="/scalping">Positions & controls</Link>
                </Button>
              </div>
            </details>
          </div>
        </div>
        <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
          {optionMarket ? (
            <aside
              ref={optionsDrawer}
              hidden={!optionsOpen}
              role="dialog"
              aria-label="Chart options"
              tabIndex={-1}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.stopPropagation()
                  closeOptions()
                }
              }}
              className="absolute inset-y-0 right-0 z-50 w-[min(40rem,100%)] overflow-y-auto overscroll-contain border-l bg-card text-card-foreground shadow-xl outline-none"
            >
              <div className="sticky top-0 z-10 flex items-center justify-between border-b bg-card px-3 py-2">
                <strong className="text-sm">Chart options</strong>
                <Button size="sm" variant="outline" onClick={closeOptions}>
                  Close options
                </Button>
              </div>
              <NeoTradingTools
                key={underlying}
                target={target}
                revision={revision}
                initialize={false}
                active={optionsOpen}
                historyPending={loading || Boolean(error) || !history?.candles.length}
                shownSymbol={instrument.symbol}
                underlying={underlying}
                interval={interval}
                toolkit
                onOptionReference={setOptionReference}
              />
            </aside>
          ) : crypto && !chartFocus ? (
            <div className="border-b px-4 py-2 text-xs text-muted-foreground">
              Crypto perpetuals · public Delta candle feed · price direction only · no trading
              credentials used
            </div>
          ) : null}
          {error ? (
            <p
              role="alert"
              className="flex items-center justify-between gap-2 border-b px-4 py-2 text-sm text-destructive"
            >
              {error}
              <Button
                size="sm"
                variant="outline"
                onClick={() => void load(state.current.instrument).catch(() => {})}
              >
                Retry chart
              </Button>
            </p>
          ) : null}
          <div
            className={
              chartFocus
                ? 'flex min-h-0 flex-1 overflow-hidden'
                : `grid min-h-0 flex-1 gap-3 overflow-auto p-3 ${underlying === 'NIFTY' ? 'xl:grid-cols-[minmax(0,1fr)_300px]' : ''}`
            }
          >
            <div
              className={chartFocus ? 'min-h-0 min-w-0 flex-1' : 'min-h-[420px] min-w-0 xl:min-h-0'}
            >
              <NeoMarketChart
                symbol={instrument.symbol}
                exchange={instrument.exchange}
                interval={interval}
                studies={studies}
                initialCandlePattern={initialTarget?.candlePattern}
                initialHistory={history}
                optionReference={crypto ? undefined : optionReference}
                compact
                recentContext
                focusMode={chartFocus}
                fitViewport
                darkOverride={chartFocus ? chartDark : undefined}
              />
            </div>
            {!chartFocus && underlying === 'NIFTY' ? (
              <aside aria-label="Strategy workspace" className="space-y-3 overflow-auto">
                <p className="text-xs font-medium text-muted-foreground">
                  NIFTY 15m automation · separate from chart signals
                </p>
                <NeoStrategyControls compact />
                <NeoStrategyResearch />
              </aside>
            ) : null}
          </div>
          <p hidden={chartFocus} className="px-4 pb-3 text-xs text-muted-foreground">
            Chart timeframe and CE / PE selection are for viewing. Automated entries use confirmed
            NIFTY 15-minute setups. BUY, SL and target lines appear for the terminal-owned filled
            position on its matching chart.
          </p>
        </div>
        {searchOpen ? (
          <Suspense
            fallback={
              <output className="absolute right-3 top-12 z-50 rounded-md border bg-card p-3 text-xs">
                Opening symbol search…
              </output>
            }
          >
            <SymbolSearchDialog
              open
              onOpenChange={setSearchOpen}
              search={searchChartSymbols}
              initialQuery={instrument.symbol}
              container={document.fullscreenElement as HTMLElement | null}
              onPick={(row) => {
                setSearchOpen(false)
                setOptionReference(undefined)
                const root = /^([A-Z&-]+)\d{2}[A-Z]{3}\d{2}/.exec(row.symbol)?.[1]
                setUnderlying(
                  root && ['NIFTY', 'BANKNIFTY', 'SENSEX'].includes(root) ? root : row.symbol
                )
                void load({ symbol: row.symbol, exchange: row.exchange }).catch(() => {})
              }}
            />
          </Suspense>
        ) : null}
      </main>
    </div>
  )
}
