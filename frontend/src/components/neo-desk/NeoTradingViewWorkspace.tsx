import { INDICATORS } from '../chart-toolkit/nineIndicators'
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Maximize2, Minimize2, SlidersHorizontal, MoreHorizontal } from 'lucide-react'
import { Link } from 'react-router'
import { scalpingApi } from '@/api/scalping'
import { Navbar } from '@/components/layout/Navbar'
import { NeoStrategyControls } from '@/components/scalping/NeoStrategyControls'
import { Button } from '@/components/ui/button'
import { NeoMarketChart } from './NeoMarketChart'
import { NeoStrategyResearch } from './NeoStrategyResearch'
import { type NeoChartTarget, NeoTradingTools } from './NeoTradingTools'
import { readDeltaHistory } from '../chart-toolkit/deltaFeed'
import type { OptionReference } from '../chart-toolkit/ToolkitPanel'

type Instrument = { symbol: string; exchange: string }
type History = Awaited<ReturnType<typeof scalpingApi.getHistory>>
const defaults = [...INDICATORS.map(item => item.id), 'bb-chikou', 'neo-toolkit', 'neo-donchian', 'neo-structure', 'rsi']
export function NeoTradingViewWorkspace() {
  const queryClient = useQueryClient()
  const workspace = useRef<HTMLElement>(null)
  const [chartFocus, setChartFocus] = useState(true)
  const [chartDark, setChartDark] = useState(true)
  const [optionsOpen, setOptionsOpen] = useState(false)
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
  const [underlying, setUnderlying] = useState('NIFTY')
  const crypto = underlying === 'BTCUSD' || underlying === 'ETHUSD'
  const [optionReference, setOptionReference] = useState<OptionReference>()
  const [instrument, setInstrument] = useState<Instrument>({
      symbol: 'NIFTY',
      exchange: 'NSE_INDEX',
    }),
    [interval, setInterval] = useState('15m'),
    [history, setHistory] = useState<History>(),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(''),
    [revision, setRevision] = useState(0)
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
  const [studies, setStudies] = useState<string[]>(() => {
    try {
      const stored = JSON.parse(localStorage.getItem('neo.native.chart.indicators') || 'null')
      if (localStorage.getItem('neo.chart.toolkit.version') !== '2') return ['neo-toolkit']
      return Array.isArray(stored) ? stored.filter((id) => defaults.includes(id)) : ['neo-toolkit']
    } catch {
      return ['neo-toolkit']
    }
  })
  useEffect(() => {
    localStorage.setItem('neo.native.chart.indicators', JSON.stringify(studies))
    localStorage.setItem('neo.chart.toolkit.version', '2')
  }, [studies])
  const state = useRef({ instrument, interval, history, studies }),
    sequence = useRef(0)
  state.current = { instrument, interval, history, studies }
  const load = useCallback(
    async (selected: Instrument) => {
      const version = ++sequence.current
      setLoading(true)
      setError('')
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
                    { signal, timeoutMs: 12000 }
                  )
            if (value.status !== 'success')
              throw Error(value.message || 'Chart history unavailable')
            return value
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
        if (version === sequence.current)
          setError(
            (e as { code?: string }).code === 'ECONNABORTED'
              ? 'Broker candles are delayed. Retry chart in a moment.'
              : (e as Error).message
          )
        throw e
      } finally {
        if (version === sequence.current) setLoading(false)
      }
    },
    [queryClient]
  )
  // biome-ignore lint/correctness/useExhaustiveDependencies: a timeframe change must request the current contract again
  useEffect(() => {
    void load(state.current.instrument).catch(() => {})
  }, [interval, load])
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
    [load]
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
                '--popover': '#181c27',
                '--border': '#2a2e39',
                '--muted': '#242936',
                '--muted-foreground': '#959bad',
                '--foreground': '#d1d4dc',
              } as CSSProperties)
            : undefined
        }
        className={`${chartFocus && chartDark ? 'dark' : ''} flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden ${fullscreen ? 'h-dvh' : ''} bg-background text-foreground`}
      >
        <div className="flex min-h-11 shrink-0 flex-wrap items-center gap-3 border-b px-3 py-1">
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
                  exchange: ['BTCUSD', 'ETHUSD'].includes(value)
                    ? 'DELTA'
                    : value === 'SENSEX'
                      ? 'BSE_INDEX'
                      : 'NSE_INDEX',
                }).catch(() => {})
              }}
            >
              {['NIFTY', 'BANKNIFTY', 'SENSEX', 'BTCUSD', 'ETHUSD'].map((value) => (
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
            <span className="min-w-0 flex-1" />
            {!crypto ? (
              <Button
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
        {!crypto ? (
          <div hidden={chartFocus && !optionsOpen}>
            <NeoTradingTools
              key={underlying}
              target={target}
              revision={revision}
              initialize={false}
              active={optionsOpen}
              shownSymbol={instrument.symbol}
              underlying={underlying}
              toolkit
              onOptionReference={setOptionReference}
            />
          </div>
        ) : !chartFocus ? (
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
              ? 'flex min-h-0 flex-1'
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
              initialHistory={history}
              optionReference={crypto ? undefined : optionReference}
              compact
              recentContext
              focusMode={chartFocus}
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
      </main>
    </div>
  )
}
