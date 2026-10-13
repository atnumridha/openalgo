import { feedTimeMs, nextLiveBar } from './liveBars'
import { priceDecimals } from '@/lib/scalpingPrice'
import type { Bar, Chart, SeriesApi } from 'openalgo-charts'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { neoDeskApi } from '@/api/neoDesk'
import { scalpingApi } from '@/api/scalping'
import { useMarketData } from '@/hooks/useMarketData'
import { useThemeStore } from '@/stores/themeStore'
import { loadCustomIndicators } from '@/lib/trading/customIndicators'
const choices = [
  ['neo-donchian', 'Donchian 20 / EMA 200'],
  ['neo-structure', 'FVG / structure'],
  ['rsi', 'RSI 14'],
] as const
export function NeoMarketChart({
  symbol,
  exchange,
  interval,
  title,
}: {
  symbol: string
  exchange: string
  interval: string
  title?: string
}) {
  const host = useRef<HTMLDivElement>(null),
    chart = useRef<Chart | null>(null),
    series = useRef<SeriesApi | null>(null),
    bars = useRef<Bar[]>([])
  const [ready, setReady] = useState(0),
    [enabled, setEnabled] = useState<string[]>(() => {
      try {
        const stored = JSON.parse(localStorage.getItem('neo.chart.indicators') || 'null')
        return Array.isArray(stored)
          ? stored.filter((x) => choices.some((c) => c[0] === x))
          : choices.map((c) => c[0])
      } catch {
        return choices.map((c) => c[0])
      }
    }),
    [error, setError] = useState(''),
    [indicatorError, setIndicatorError] = useState('')
  const mode = useThemeStore((s) => s.mode),
    appMode = useThemeStore((s) => s.appMode)
  const market = useMarketData({
    symbols: symbol && exchange ? [{ symbol, exchange }] : [],
    mode: 'Quote',
    enabled: Boolean(symbol && exchange),
    autoReconnect: true,
  })
  const info = useQuery({
    queryKey: ['neo-chart', exchange, symbol, interval],
    queryFn: () => neoDeskApi.chart(exchange + ':' + symbol, interval),
    enabled: Boolean(symbol),
    refetchInterval: 2000,
  })
  useEffect(() => {
    localStorage.setItem('neo.chart.indicators', JSON.stringify(enabled))
  }, [enabled])
  useEffect(() => {
    if (!host.current || !symbol) return
    setError('')
    let disposed = false
    let instance: Chart | null = null
    let inflight = false
    async function refresh() {
      if (inflight || disposed || !series.current) return
      inflight = true
      try {
        const result = await scalpingApi.getHistory(symbol, exchange, interval)
        if (disposed) return
        if (result.status !== 'success')
          throw new Error(result.message || 'Broker history unavailable')
        const fresh = (result.candles || []).map((b) => ({ ...b, time: b.time - 19800 }))
        bars.current = fresh
        series.current.setData(fresh)
        setError('')
      } catch (e) {
        if (!disposed) setError((e as Error).message)
      } finally {
        inflight = false
      }
    }
    async function build() {
      try {
        const [core, theme] = await Promise.all([
          import('openalgo-charts'),
          import('@/lib/trading/chartTheme'),
          import('openalgo-charts/indicators'),
        ])
        await loadCustomIndicators({
          onProblem: (message) => {
            if (!disposed) setIndicatorError(message)
          },
        })
        if (disposed || !host.current) return
        instance = core.createChart(host.current, {
          theme: theme.buildChartTheme(mode, appMode),
          timezone: 'Asia/Kolkata',
          ariaLabel: `${symbol} actual price chart`,
          shortcuts: false,
          timeNavigator: false,
          branding: false,
        })
        chart.current = instance
        instance.setDataContext({ symbol, exchange, interval })
        series.current = instance.addSeries('candlestick')
        series.current.priceScale().setOptions({ minMove: 10 ** -priceDecimals(exchange) })
        await refresh()
        if (disposed) return
        instance.fitContent()
        setReady((n) => n + 1)
      } catch (e) {
        if (!disposed) setError((e as Error).message)
      }
    }
    void build()
    const timer = setInterval(() => void refresh(), 25000)
    return () => {
      disposed = true
      clearInterval(timer)
      instance?.destroy()
      if (chart.current === instance) {
        chart.current = null
        series.current = null
        bars.current = []
      }
    }
  }, [symbol, exchange, interval, mode, appMode])
  // biome-ignore lint/correctness/useExhaustiveDependencies: ready tracks replacement of the imperative chart instance
  useEffect(() => {
    const c = chart.current
    if (!c) return
    const ids: string[] = []
    const problems: string[] = []
    for (const id of enabled) {
      try {
        ids.push(c.addIndicator(id, id === 'rsi' ? { length: 14 } : {}).id)
      } catch (e) {
        problems.push(`Indicator ${id} unavailable: ${(e as Error).message}`)
      }
    }
    setIndicatorError(problems.join('; '))
    return () => {
      for (const id of ids) c.removeIndicator(id)
    }
  }, [ready, enabled])
  // biome-ignore lint/correctness/useExhaustiveDependencies: ready tracks replacement of the imperative chart instance
  useEffect(() => {
    const c = chart.current
    if (!c || !info.data) return
    const lines = info.data.overlays.map((line, i) =>
      c.addPriceLine({
        id: `neo-${line.run_id}-${i}`,
        price: Number(line.price),
        color: line.label.includes('SL')
          ? '#ef5350'
          : line.label.includes('target') || line.label.includes('TARGET')
            ? '#26a69a'
            : '#3b82f6',
        label: line.label,
        leftLabel: line.label,
        extentFromRight: 0.35,
        lineStyle: 'dashed',
      })
    )
    return () => {
      for (const line of lines) c.removePrimitive(line)
    }
  }, [ready, info.data])
  const tick = market.data.get(exchange + ':' + symbol)?.data
  useEffect(() => {
    if (!series.current || !tick?.ltp) return
    const last = bars.current.at(-1),
      bar = nextLiveBar(last, Number(tick.ltp), tick.timestamp, interval, Date.now())
    if (!bar) return
    if (last && bar.time === last.time) bars.current[bars.current.length - 1] = bar
    else bars.current.push(bar)
    series.current.update(bar)
  }, [tick, interval])
  const tickTime = feedTimeMs(tick?.timestamp),
    tickAge = tickTime == null ? null : Math.max(0, (Date.now() - tickTime) / 1000)

  return (
    <section
      className="flex h-full min-h-[330px] flex-col rounded border bg-card"
      aria-label={`${title || symbol} chart`}
    >
      <div className="px-3 pt-2 text-xs">
        <strong>
          {title} · {symbol}
        </strong>
        <p className="text-muted-foreground">
          {exchange} · {interval} · actual contract prices
        </p>
        <div className="flex flex-wrap gap-2 py-2">
          {choices.map(([id, label]) => (
            <label key={id} className="flex gap-1">
              <input
                type="checkbox"
                checked={enabled.includes(id)}
                onChange={(e) =>
                  setEnabled((old) =>
                    e.target.checked ? [...old, id] : old.filter((x) => x !== id)
                  )
                }
              />
              {label}
            </label>
          ))}
        </div>
      </div>
      <div ref={host} className="min-h-0 flex-1" />
      {error || indicatorError || info.error ? (
        <p role="alert" className="px-3 py-2 text-xs text-destructive">
          {[error, indicatorError, (info.error as Error)?.message].filter(Boolean).join('; ')}
        </p>
      ) : null}
      <p className="px-3 pb-2 text-[10px] text-muted-foreground">
        {market.isConnected ? 'Feed connected' : 'Feed disconnected; last historical prices'}
        {tickAge != null
          ? ` · server feed age ${tickAge.toFixed(1)}s`
          : ' · no timestamped tick yet'}{' '}
        · Pivot zones are potential liquidity, not order-book evidence. Strategy executes on NIFTY
        15m.
      </p>
    </section>
  )
}
