import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { chartBars, formatIST } from '../neo-desk/tradingViewStudies'
import { NineIndicatorPanel } from './NineIndicatorPanel'
import { INDICATORS, NineIndicatorEngine } from './nineIndicators'

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
      return { bars, observedAt: Date.now() / 1000 }
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
  const result = useMemo(
    () => (history.data ? engine.update(history.data.bars, { seconds, asOf, indian: true }) : null),
    [history.data, engine, seconds, asOf]
  )
  return (
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
              ? `Completed candle ${formatIST(result.lastTime, true)} IST · refreshes every 30s`
              : 'Waiting for a completed candle.'}
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
        onMfiProxy={ignoreProxy}
      />
    </section>
  )
}
