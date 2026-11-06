import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import { useMarketData } from '@/hooks/useMarketData'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { chartBars, formatIST } from '../neo-desk/tradingViewStudies'
import { NineIndicatorPanel } from './NineIndicatorPanel'
import { INDICATORS, NineIndicatorEngine } from './nineIndicators'
import { LiveIndicatorPreview } from './liveIndicatorPreview'
import { analyzeCandles } from './candleProbability'
import { getCandleSeed } from './candleProbabilitySeeds'
import { CandlestickProbabilityPanel } from './CandlestickProbabilityPanel'

const enabled = INDICATORS.map((item) => item.id)
const ignoreProxy = () => {}
const timeframes = [
  { value: '1m', seconds: 60 },
  { value: '5m', seconds: 300 },
  { value: '15m', seconds: 900 },
]

export function DashboardIndicatorSignals({
  symbol: controlledSymbol,
  onSymbolChange,
}: {
  symbol?: string
  onSymbolChange?: (symbol: string) => void
} = {}) {
  const username = useAuthStore((s) => s.user?.username)
  const mode = useThemeStore((s) => s.appMode)
  const [localSymbol, setSymbol] = useState('NIFTY')
  const symbol = controlledSymbol ?? localSymbol
  const [interval, setInterval] = useState('15m')
  const exchange = symbol === 'SENSEX' ? 'BSE_INDEX' : 'NSE_INDEX'
  const seconds = timeframes.find((item) => item.value === interval)!.seconds
  const stream = useMarketData({ symbols: [{ symbol, exchange }], mode: 'LTP' })
  const [clock, setClock] = useState(Date.now)
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const history = useQuery({
    queryKey: ['dashboard-indicator-history', username, mode, symbol, exchange, interval],
    queryFn: async ({ signal }) => {
      const response = await scalpingApi.getHistory(symbol, exchange, interval, undefined, {
        signal,
        timeoutMs: 60000,
      })
      if (response.status !== 'success')
        throw Error(response.message || 'Broker history unavailable')
      const bars = chartBars(response.candles)
      if (!bars.length) throw Error('No valid broker candles')
      // Preserve invalid/conflicting observations for the probability engine to
      // reject. The legacy chart helper drops bad OHLC and deduplicates last-wins.
      const probabilityBars = response.candles.map((bar) => ({
        time: Number(bar.time) - 19800,
        open: Number(bar.open),
        high: Number(bar.high),
        low: Number(bar.low),
        close: Number(bar.close),
        volume: Number(bar.volume ?? 0),
      }))
      return { bars, probabilityBars, observedAt: Date.now() / 1000 }
    },
    staleTime: 20000,
    refetchInterval: 30000,
    retry: false,
  })
  const engine = useMemo(
    () => new NineIndicatorEngine(),
    [symbol, exchange, interval, username, mode]
  )
  // A cached forming candle cannot become final merely because the clock advanced.
  const asOf = history.data?.observedAt ?? 0
  const candleStudy = useMemo(() => {
    if (!history.data) return null
    const scope = { symbol, exchange, seconds, indian: true }
    return analyzeCandles(
      history.data.probabilityBars ?? [],
      { ...scope, asOf },
      getCandleSeed(scope)
    )
  }, [history.data, symbol, exchange, seconds, asOf])
  const result = useMemo(
    () => (history.data ? engine.update(history.data.bars, { seconds, asOf, indian: true }) : null),
    [history.data, engine, seconds, asOf]
  )
  const previewScope = useMemo(
    () => ({ engine: new LiveIndicatorPreview(), startedAt: Date.now() }),
    [symbol, exchange, interval, username, mode, stream.connectionEpoch]
  )
  const quote = stream.data.get(`${exchange}:${symbol}`)
  const wallMs = Math.max(clock, Date.now())
  const preview = useMemo(
    () =>
      history.data && (quote?.lastUpdate ?? 0) > previewScope.startedAt
        ? previewScope.engine.update(history.data.bars, asOf, quote, {
            symbol,
            exchange,
            interval,
            seconds,
            now: wallMs,
            isAuthenticated: stream.isAuthenticated,
            connectionEpoch: stream.connectionEpoch,
          })
        : null,
    [
      history.data,
      previewScope,
      asOf,
      quote,
      symbol,
      exchange,
      interval,
      seconds,
      wallMs,
      stream.isAuthenticated,
      stream.connectionEpoch,
    ]
  )
  const refreshAttempt = useMemo(() => ({ at: 0 }), [symbol, exchange, interval, username, mode])
  // Stream updates are local calculations. Only a new interval or a missing broker
  // forming bar asks for history, with a bounded retry instead of per-tick HTTP.
  useEffect(() => {
    const local = new Date(wallMs + 19800000)
    const minute = local.getUTCHours() * 60 + local.getUTCMinutes()
    if (
      !history.data ||
      history.isFetching ||
      local.getUTCDay() === 0 ||
      local.getUTCDay() === 6 ||
      minute < 555 ||
      minute > 930
    )
      return
    const boundary = Math.floor(wallMs / 1000 / seconds) * seconds
    const newInterval = boundary > asOf && wallMs / 1000 >= boundary + 1
    const needsForming =
      stream.isAuthenticated &&
      quote?.updateSource === 'websocket' &&
      quote.connectionEpoch === stream.connectionEpoch &&
      (quote.lastUpdate ?? 0) > asOf * 1000 &&
      wallMs - (quote.lastUpdate ?? 0) <= 15000 &&
      !preview &&
      (history.data.bars.at(-1)?.time ?? 0) < boundary
    if ((newInterval || needsForming) && wallMs - refreshAttempt.at >= 5000) {
      refreshAttempt.at = wallMs
      void history.refetch({ cancelRefetch: false })
    }
  }, [
    wallMs,
    asOf,
    seconds,
    history.data,
    history.isFetching,
    history.refetch,
    refreshAttempt,
    stream.isAuthenticated,
    stream.connectionEpoch,
    quote,
    preview,
  ])
  const tickTime = preview
    ? new Date(preview.time * 1000).toLocaleTimeString('en-IN', {
        timeZone: 'Asia/Kolkata',
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        fractionalSecondDigits: 3,
      })
    : null
  return (
    <>
      <section
        aria-label="Dashboard indicator signals"
        className="rounded-xl border bg-card p-4 md:p-5"
      >
        <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">Indicator signals</h2>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label className="sr-only" htmlFor="dashboard-signal-index">
              Signal index
            </label>
            <select
              id="dashboard-signal-index"
              value={symbol}
              onChange={(event) => {
                setSymbol(event.target.value)
                onSymbolChange?.(event.target.value)
              }}
              className="h-11 rounded-md border bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              <option value="NIFTY">Nifty</option>
              <option value="SENSEX">Sensex</option>
            </select>
            <label className="sr-only" htmlFor="dashboard-signal-timeframe">
              Signal timeframe
            </label>
            <select
              id="dashboard-signal-timeframe"
              value={interval}
              onChange={(event) => setInterval(event.target.value)}
              className="h-11 rounded-md border bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              {timeframes.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.value}
                </option>
              ))}
            </select>
          </div>
        </div>
        <p role="status" className="mb-4 text-xs text-muted-foreground">
          {history.isError
            ? history.data
              ? 'Broker history unavailable. Retained signals show historical events only.'
              : 'Broker history unavailable. Signals stay WAIT until verified candles arrive.'
            : history.isPending
              ? 'Loading broker candles…'
              : result?.lastTime
                ? `Completed candle ${formatIST(result.lastTime, true)} IST · signals confirm at candle close`
                : 'Waiting for a completed candle.'}
          <span className="mt-1 block">
            {preview
              ? `Live values on incoming ticks · received ${tickTime} IST`
              : stream.isAuthenticated
                ? 'Live feed connected · waiting for a fresh tick and current candle'
                : stream.isFallbackMode
                  ? 'Live feed unavailable · using polled data'
                  : 'Connecting to live feed · showing verified candle values'}
          </span>
          {history.isError ? (
            <button
              type="button"
              onClick={() => void history.refetch()}
              className="ml-2 underline"
              disabled={history.isFetching}
            >
              Retry signal history
            </button>
          ) : null}
        </p>
        <NineIndicatorPanel
          embedded
          enabled={enabled}
          result={result}
          symbol={symbol}
          exchange={exchange}
          interval={interval}
          seconds={seconds}
          asOf={asOf}
          replay={false}
          ready={!!history.data && !history.isError}
          liveValues={preview?.values}
          liveValueTime={preview?.time}
          onMfiProxy={ignoreProxy}
        />
      </section>
      <div className="rounded-xl border bg-card p-4 md:p-5">
        <CandlestickProbabilityPanel
          study={candleStudy}
          symbol={symbol}
          exchange={exchange}
          seconds={seconds}
          ready={!!history.data && !history.isError}
          now={wallMs / 1000}
        />
      </div>
    </>
  )
}
