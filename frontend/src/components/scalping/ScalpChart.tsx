import { useBrokerCurrencyFormatter, useBrokerPriceFormatter } from '@/hooks/useBrokerCurrencyFormatter'
/**
 * ScalpChart - a self-contained live candlestick + volume chart for the
 * scalping terminal.
 *
 * Given a symbol/exchange/interval it:
 *   - loads history from /scalping/api/history (1m=1d, 5m=3d, 15m=9d lookback),
 *   - draws candles + a volume histogram with an OHLC legend,
 *   - streams the forming candle live via the shared useMarketData feed, and
 *   - reconciles completed bars to the broker's official OHLC on a staggered
 *     20-30s timer (so multiple charts never hit the API at the same instant).
 *
 * Works for any exchange (options/futures/equity/indices). Index symbols carry
 * volume 0. Uses the bundled lightweight-charts v5 (no CDN).
 */

import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type AutoscaleInfo,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import { useMarketData } from '@/hooks/useMarketData'
import { priceDecimals } from '@/lib/scalpingPrice'
import { chartIndicators, type ChartIndicatorValues } from '@/lib/scalpingIndicators'
import { grossLabel, type ChartPosition } from '@/lib/scalpingChartPosition'
import { useThemeStore } from '@/stores/themeStore'

// Matches the IST shift the backend bakes into bar times so live bars line up
// with history bars. 5h30m = 19800s, a whole multiple of 60/300/900s.
const IST_OFFSET = 19800
const INTERVAL_SEC: Record<string, number> = { '1m': 60, '5m': 300, '15m': 900 }

const UP = '#26a69a'
const DOWN = '#ef5350'
const VOL_UP = 'rgba(38,166,154,0.45)'
const VOL_DOWN = 'rgba(239,83,80,0.45)'
const INDICATORS = [
  { key: 'ema9', title: 'EMA9', color: '#0284c7', pane: 0 },
  { key: 'ema20', title: 'EMA20', color: '#d97706', pane: 0 },
  { key: 'ema50', title: 'EMA50', color: '#db2777', pane: 0 },
] as const
type IndicatorKey = typeof INDICATORS[number]['key']
const visibleIndicator = (key: IndicatorKey, interval: string) =>
  interval === '1m' ? key === 'ema9' : key !== 'ema9'

interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

function nativeFmtPrice(n: number, decimals = 2): string {
  return n.toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}
function fmtVol(n: number): string {
  const a = Math.abs(n)
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (a >= 1e3) return `${(n / 1e3).toFixed(2)}K`
  return String(Math.round(n))
}

export function ScalpChart({
  symbol,
  exchange,
  interval,
  title,
  position,
}: {
  symbol: string
  exchange: string
  interval: string
  title?: string
  position?: ChartPosition
}) {
  const display = useBrokerCurrencyFormatter('deltaexchange')
  const quote = useBrokerPriceFormatter('deltaexchange')
  const quoteRef = useRef(quote)
  quoteRef.current = quote
  const displayRef = useRef(display)
  displayRef.current = display
  const fmtPrice = (n: number, decimals = 2) => exchange === 'CRYPTO' ? quoteRef.current(n) : nativeFmtPrice(n, decimals)
  const { mode } = useThemeStore()
  const isDark = mode === 'dark'

  const containerRef = useRef<HTMLDivElement | null>(null)
  const legendRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const indicatorSeriesRef = useRef<Partial<Record<IndicatorKey, ISeriesApi<'Line'>>>>({})
  const indicatorValuesRef = useRef<ChartIndicatorValues[]>([])
  const renderIndicatorsRef = useRef<(replace: boolean) => void>(() => {})
  const renderLegendRef = useRef<(time?: number) => void>(() => {})
  const colorsRef = useRef({ title: '#d6dde6', muted: '#8a97a5' })
  const positionRef = useRef(position)
  positionRef.current = position

  // Authoritative model: bucket time -> candle. Completed bars are reconciled
  // from broker history; the current bucket is built live from ticks.
  const candlesRef = useRef<Map<number, Candle>>(new Map())
  const sortedRef = useRef<Candle[]>([])
  const idxByTimeRef = useRef<Map<number, number>>(new Map())
  const currentBucketRef = useRef<number | null>(null)
  const tradingDateRef = useRef<string | null>(null)
  const intervalSecRef = useRef<number>(INTERVAL_SEC[interval] ?? 60)
  const intervalRef = useRef<string>(interval)
  const barStartVolRef = useRef<number | null>(null)
  const readyRef = useRef(false)

  const [status, setStatus] = useState('')

  const enabled = !!(symbol && exchange)
  const { data } = useMarketData({
    symbols: enabled ? [{ symbol, exchange }] : [],
    mode: 'Quote',
    enabled,
    autoReconnect: true,
  })

  // Create the chart once per symbol/exchange (candles + volume + legend).
  // isDark is used only for the initial colors; theme changes are applied by the
  // separate re-theme effect below, so it is intentionally not a dependency.
  // biome-ignore lint/correctness/useExhaustiveDependencies: isDark excluded; theme handled by the re-theme effect
  useEffect(() => {
    const container = containerRef.current
    if (!container || !enabled) return

    // Currency derivatives (CDS/BCD) price to 4 decimals; everything else to 2.
    const decimals = priceDecimals(exchange)

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: colorsRef.current.muted,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: isDark ? 'rgba(120,130,145,0.06)' : 'rgba(0,0,0,0.05)' },
        horzLines: { color: isDark ? 'rgba(120,130,145,0.06)' : 'rgba(0,0,0,0.05)' },
      },
      rightPriceScale: { borderColor: isDark ? '#1b2330' : '#e2e8f0' },
      timeScale: {
        borderColor: isDark ? '#1b2330' : '#e2e8f0',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 3,
        shiftVisibleRangeOnNewBar: true,
      },
      // Keep page scrolling from panning/zooming the chart into old candles.
      handleScroll: false,
      handleScale: { mouseWheel: false },
      crosshair: { mode: CrosshairMode.Normal },
    })
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderVisible: false,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceFormat: exchange === 'CRYPTO' ? {type:'custom',minMove:10 ** -decimals,formatter:(n: number) => quoteRef.current(n)} : { type: 'price', precision: decimals, minMove: 10 ** -decimals },
    })
    const vol = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    })
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
    candle.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.23 } })

    for (const indicator of INDICATORS) {
      const line = chart.addSeries(LineSeries, {
        title: indicator.title,
        color: indicator.color,
        lineWidth: 2,
        visible: visibleIndicator(indicator.key, intervalRef.current),
        priceLineVisible: false,
        priceFormat: exchange === 'CRYPTO' ? {type:'custom',minMove:10 ** -decimals,formatter:(n: number) => quoteRef.current(n)} : { type: 'price', precision: decimals, minMove: 10 ** -decimals },
      }, indicator.pane)
      indicatorSeriesRef.current[indicator.key] = line
    }

    renderIndicatorsRef.current = (replace) => {
      const values = chartIndicators(sortedRef.current)
      indicatorValuesRef.current = values
      for (const indicator of INDICATORS) {
        const series = indicatorSeriesRef.current[indicator.key]
        if (!series) continue
        if (replace) {
          series.setData(values.flatMap((row) => row[indicator.key] == null ? [] : [{
            time: row.time as UTCTimestamp, value: row[indicator.key]!,
          }]))
        } else {
          // Tick updates only replace/append the newest point on each series.
          const row = values.at(-1)
          const value = row?.[indicator.key]
          if (row && value != null) series.update({ time: row.time as UTCTimestamp, value })
        }
      }
    }

    chartRef.current = chart
    candleRef.current = candle
    volRef.current = vol

    // OHLC legend overlay: hovered bar, or the last bar when not hovering.
    const renderLegend = (time?: number) => {
      const el = legendRef.current
      const arr = sortedRef.current
      if (!el) return
      if (!arr.length) {
        el.innerHTML = ''
        return
      }
      let idx = arr.length - 1
      if (time != null) {
        const i = idxByTimeRef.current.get(time)
        if (i != null) idx = i
      }
      const bar = arr[idx]
      const ref = idx > 0 ? arr[idx - 1].close : bar.open
      const chg = bar.close - ref
      const pct = ref ? (chg / ref) * 100 : 0
      const col = chg >= 0 ? UP : DOWN
      const sign = chg >= 0 ? '+' : ''
      const { title: titleColor, muted } = colorsRef.current
      const indicators = indicatorValuesRef.current[idx]
      const indicatorLegend = INDICATORS.filter(({ key }) => visibleIndicator(key, intervalRef.current)).map(({ key, title, color }) =>
        `<span style="color:${color};display:inline-block;margin-right:12px">${title} ${indicators?.[key] == null ? '—' : fmtPrice(indicators[key], decimals)}</span>`
      ).join('')
      el.innerHTML =
        `<div style="color:${titleColor};font-weight:600">${symbol} ` +
        `<span style="color:${muted};font-weight:500">· ${intervalRef.current} · ${exchange} · candle ${new Date(bar.time * 1000).toISOString().slice(11, 16)} IST</span></div>` +
        `<div style="color:${col};margin-top:1px">O${fmtPrice(bar.open, decimals)} H${fmtPrice(bar.high, decimals)} ` +
        `L${fmtPrice(bar.low, decimals)} C${fmtPrice(bar.close, decimals)} ${sign}${fmtPrice(chg, decimals)} (${sign}${pct.toFixed(2)}%)</div>` +
        `<div style="color:${muted};margin-top:1px">Volume <span style="color:${col}">${fmtVol(bar.volume)}</span></div>` +
        `<div style="margin-top:3px">${indicatorLegend}</div>`
    }
    renderLegendRef.current = renderLegend
    chart.subscribeCrosshairMove((param) => {
      renderLegend(typeof param.time === 'number' ? param.time : undefined)
    })

    return () => {
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      volRef.current = null
      indicatorSeriesRef.current = {}
      indicatorValuesRef.current = []
      renderIndicatorsRef.current = () => {}
    }
  }, [symbol, exchange, enabled])

  useEffect(() => {
    if (exchange === 'CRYPTO') {
      candleRef.current?.applyOptions({priceFormat:{type:'custom',minMove:10 ** -priceDecimals(exchange),formatter:(n: number) => quoteRef.current(n)}})
      renderLegendRef.current()
    }
  }, [display, exchange])

  // These are display lines from actual fills and acknowledged server protection.
  // They do not place, modify or cancel exchange orders.
  useEffect(() => {
    const candle = candleRef.current
    if (!candle) return
    candle.applyOptions({ autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
      const info = original()
      const current = positionRef.current
      if (!info?.priceRange || current?.status !== 'open') return info
      const prices = [current.entry, current.sl, current.target].filter((p): p is number => p != null && Number.isFinite(p) && p > 0)
      return { ...info, priceRange: {
        minValue: Math.min(info.priceRange.minValue, ...prices),
        maxValue: Math.max(info.priceRange.maxValue, ...prices),
      } }
    } })
    if (position?.status !== 'open' || !position.entry || !position.quantity) return
    const lines = [
      { price: position.entry, title: `${position.quantity > 0 ? 'LONG' : 'SHORT'} ${Math.abs(position.quantity)} · Entry`, color: '#0284c7' },
      ...(position.sl ? [{ price: position.sl, title: `SL · ${position.currency === 'USD' ? displayRef.current(position.slGross ?? NaN) : grossLabel(position.slGross, position.currency)}`, color: '#dc2626' }] : []),
      ...(position.target ? [{ price: position.target, title: `Target · ${position.currency === 'USD' ? displayRef.current(position.targetGross ?? NaN) : grossLabel(position.targetGross, position.currency)}`, color: '#16a34a' }] : []),
    ].map((line) => candle.createPriceLine({ ...line, lineWidth: 2, lineStyle: LineStyle.Dashed, axisLabelVisible: true }))
    return () => {
      if (candleRef.current === candle) for (const line of lines) candle.removePriceLine(line)
    }
  }, [symbol, exchange, interval, position?.status, position?.entry, position?.quantity, position?.sl, position?.target, position?.slGross, position?.targetGross, position?.currency, display])


  // Load history for the selected interval and run the reconcile loop. Re-runs
  // on timeframe change (instant flip; chart instance reused).
  useEffect(() => {
    const chart = chartRef.current
    const candle = candleRef.current
    const vol = volRef.current
    if (!chart || !candle || !vol || !enabled) return
    let disposed = false
    let inflight = false
    let timer: ReturnType<typeof setTimeout> | null = null

    candlesRef.current = new Map()
    sortedRef.current = []
    idxByTimeRef.current = new Map()
    currentBucketRef.current = null
    barStartVolRef.current = null
    intervalSecRef.current = INTERVAL_SEC[interval] ?? 60
    intervalRef.current = interval
    for (const indicator of INDICATORS) {
      indicatorSeriesRef.current[indicator.key]?.applyOptions({
        visible: visibleIndicator(indicator.key, interval),
      })
    }
    readyRef.current = false
    tradingDateRef.current = null
    candle.setData([])
    vol.setData([])
    renderIndicatorsRef.current(true)
    renderLegendRef.current()
    setStatus('loading...')

    const applyModel = (preserveRange: boolean) => {
      const arr = Array.from(candlesRef.current.values()).sort((a, b) => a.time - b.time)
      sortedRef.current = arr
      const idxMap = new Map<number, number>()
      arr.forEach((k, i) => idxMap.set(k.time, i))
      idxByTimeRef.current = idxMap

      const ts = chart.timeScale()
      const range = preserveRange ? ts.getVisibleLogicalRange() : null
      candle.setData(
        arr.map((k) => ({ time: k.time as UTCTimestamp, open: k.open, high: k.high, low: k.low, close: k.close }))
      )
      vol.setData(
        arr.map((k) => ({
          time: k.time as UTCTimestamp,
          value: k.volume,
          color: k.close >= k.open ? VOL_UP : VOL_DOWN,
        }))
      )
      renderIndicatorsRef.current(true)
      // Start with recent candles and keep the right edge at the newest bar.
      // Reconciliation preserves zoom width, never an old horizontal position.
      const to = arr.length - 1 + 3
      ts.setVisibleLogicalRange({
        from: range ? to - (range.to - range.from) : Math.max(-1, arr.length - 60),
        to,
      })
      renderLegendRef.current()
    }

    const reconcile = async () => {
      if (disposed || inflight) return
      inflight = true
      try {
        const d = await scalpingApi.getHistory(
          symbol,
          exchange,
          interval,
          tradingDateRef.current || undefined
        )
        if (disposed || d.status !== 'success') return
        const fetched = d.candles || []
        if (!fetched.length) return
        const cur = currentBucketRef.current
        const completed = cur == null ? fetched : fetched.filter((k) => k.time < cur)
        let changed = false
        for (const k of completed.slice(-10)) {
          const prev = candlesRef.current.get(k.time)
          if (
            !prev ||
            prev.open !== k.open ||
            prev.high !== k.high ||
            prev.low !== k.low ||
            prev.close !== k.close ||
            prev.volume !== k.volume
          ) {
            candlesRef.current.set(k.time, { ...k })
            changed = true
          }
        }
        if (changed) applyModel(true)
      } catch {
        /* transient reconcile error; the next cycle retries */
      } finally {
        inflight = false
      }
    }

    const schedule = () => {
      const delay = 20000 + Math.random() * 10000
      timer = setTimeout(async () => {
        await reconcile()
        if (!disposed) schedule()
      }, delay)
    }

    scalpingApi
      .getHistory(symbol, exchange, interval)
      .then((d) => {
        if (disposed) return
        if (d.status !== 'success') {
          setStatus(`error: ${d.message || 'history failed'}`)
          schedule()
          return
        }
        const candles = d.candles || []
        tradingDateRef.current = d.date || null
        if (!candles.length) {
          // No broker history (e.g. TradeSmart serves none for the CDS segment).
          // Build the chart live from the websocket feed instead of stalling on
          // a permanent "no history" — readyRef lets the tick effect form bars.
          readyRef.current = true
          currentBucketRef.current = null
          setStatus('waiting for live ticks…')
          schedule()
          return
        }
        candlesRef.current = new Map(candles.map((k) => [k.time, { ...k }]))
        applyModel(false)
        currentBucketRef.current = candles[candles.length - 1].time
        setStatus('')
        readyRef.current = true
        schedule()
      })
      .catch(() => {
        if (!disposed) {
          setStatus('history fetch failed')
          schedule()
        }
      })

    return () => {
      disposed = true
      readyRef.current = false
      if (timer) clearTimeout(timer)
    }
  }, [symbol, exchange, interval, enabled])

  // Re-theme the chart and legend without recreating it.
  useEffect(() => {
    colorsRef.current = isDark
      ? { title: '#d6dde6', muted: '#8a97a5' }
      : { title: '#0f172a', muted: '#64748b' }
    const chart = chartRef.current
    if (chart) {
      chart.applyOptions({
        layout: { textColor: colorsRef.current.muted },
        grid: {
          vertLines: { color: isDark ? 'rgba(120,130,145,0.06)' : 'rgba(0,0,0,0.05)' },
          horzLines: { color: isDark ? 'rgba(120,130,145,0.06)' : 'rgba(0,0,0,0.05)' },
        },
        rightPriceScale: { borderColor: isDark ? '#1b2330' : '#e2e8f0' },
        timeScale: { borderColor: isDark ? '#1b2330' : '#e2e8f0' },
      })
    }
    renderLegendRef.current()
  }, [isDark])

  // Update the forming candle (and its volume) from each live tick.
  const tick = data.get(`${exchange}:${symbol}`)?.data
  const ltp = tick?.ltp
  const ts = tick?.timestamp
  const tickVol = typeof tick?.volume === 'number' ? tick.volume : null
  useEffect(() => {
    const candle = candleRef.current
    const vol = volRef.current
    if (!candle || !vol || !readyRef.current || ltp == null || !Number.isFinite(ltp)) return

    const parsed = ts ? Date.parse(ts) : Number.NaN
    const epochUtc = Number.isNaN(parsed) ? Math.floor(Date.now() / 1000) : Math.floor(parsed / 1000)
    const sec = intervalSecRef.current
    const bucket = Math.floor((epochUtc + IST_OFFSET) / sec) * sec
    const cur = currentBucketRef.current

    let bar: Candle
    let isNew = false
    if (cur == null || bucket > cur) {
      isNew = true
      barStartVolRef.current = tickVol
      bar = { time: bucket, open: ltp, high: ltp, low: ltp, close: ltp, volume: 0 }
      currentBucketRef.current = bucket
    } else if (bucket === cur) {
      const prev = candlesRef.current.get(bucket)
      const v =
        tickVol != null && barStartVolRef.current != null
          ? Math.max(0, tickVol - barStartVolRef.current)
          : (prev?.volume ?? 0)
      bar = prev
        ? {
            time: bucket,
            open: prev.open,
            high: Math.max(prev.high, ltp),
            low: Math.min(prev.low, ltp),
            close: ltp,
            volume: v,
          }
        : { time: bucket, open: ltp, high: ltp, low: ltp, close: ltp, volume: v }
    } else {
      return // stale tick older than the current bar
    }

    candlesRef.current.set(bucket, bar)
    const arr = sortedRef.current
    if (isNew) {
      arr.push(bar)
      idxByTimeRef.current.set(bucket, arr.length - 1)
    } else if (arr.length) {
      arr[arr.length - 1] = bar
    }

    const color = bar.close >= bar.open ? VOL_UP : VOL_DOWN
    candle.update({ time: bar.time as UTCTimestamp, open: bar.open, high: bar.high, low: bar.low, close: bar.close })
    vol.update({ time: bar.time as UTCTimestamp, value: bar.volume, color })
    renderIndicatorsRef.current(false)
    chartRef.current?.timeScale().scrollToPosition(3, false)
    renderLegendRef.current()
    // Clear the live-only "waiting for ticks" placeholder once a bar exists.
    setStatus((s) => (s ? '' : s))
  }, [ltp, ts, tickVol])

  if (!enabled) {
    return (
      <div className="flex h-full w-full items-center justify-center rounded-lg border bg-card text-xs text-muted-foreground">
        {title ? `${title} — not selected` : 'No instrument'}
      </div>
    )
  }

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden rounded-lg border bg-card"
      role="region" aria-label={`${symbol} ${interval} indicator chart`}>
      <div className="shrink-0 border-b px-2.5 py-1 text-[10px] text-muted-foreground">
        Following latest · {interval} · {interval === '1m' ? 'EMA9' : 'EMA20 / EMA50'} · live/forming candle
      </div>
      {position && <div className="shrink-0 border-b px-2.5 py-1 text-xs" aria-label="Actual position and protection">
        {position.status === 'unavailable' ? 'Position unconfirmed — no verified position data returned.' :
          position.status === 'flat' ? 'No open position for this contract/product.' : <>
            <span className="font-medium">{position.quantity! > 0 ? 'LONG' : 'SHORT'} {Math.abs(position.quantity!)} · Entry {fmtPrice(position.entry!)} · P&L before fees: {position.currency === 'USD' ? display(position.gross ?? NaN) : grossLabel(position.gross, position.currency)}</span>
            <div className="text-muted-foreground">{position.protectionAvailable
              ? `SL ${position.sl == null ? 'not set' : fmtPrice(position.sl)} · Target ${position.target == null ? 'not set' : fmtPrice(position.target)} · saved server protection`
              : 'SL/target data unavailable.'}</div>
          </>}
      </div>}
      <div
        ref={legendRef}
        className="pointer-events-none min-h-[74px] shrink-0 px-2.5 py-1 font-mono text-[11px] leading-tight"
      />
      <div ref={containerRef} className="min-h-0 flex-1" />
      {status && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
          {status}
        </div>
      )}
    </div>
  )
}
