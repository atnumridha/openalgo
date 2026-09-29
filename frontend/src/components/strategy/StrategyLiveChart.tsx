/**
 * Live candlesticks for one managed strategy: venue-aware candles, the
 * strategy's own completed-bar overlays, BUY/SELL markers, and Entry/SL/Target.
 *
 * Display only. Never starts, arms, or places an order.
 */

import { useQuery } from '@tanstack/react-query'
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  LineSeries,
  LineStyle,
  type SeriesMarker,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useMemo, useRef, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import { listEvents } from '@/api/strategy_module'
import { useMarketData } from '@/hooks/useMarketData'
import { priceDecimals } from '@/lib/scalpingPrice'
import {
  CHART_IST_OFFSET,
  confirmedSignalMarkers,
  fillMarkers,
  legLevels,
  snapToCandle,
  visibleLogicalRange,
} from '@/lib/strategyChartMarkers'
import {
  bollingerSeries,
  emaSeries,
  isPlausibleLivePrice,
  plausibleHistoryTail,
  lastBarBiasMarker,
  type OverlayBar,
  openingRange,
  smaSeries,
} from '@/lib/strategyChartOverlays'
import { strategyChartProfile } from '@/lib/strategyChartProfile'
import { useThemeStore } from '@/stores/themeStore'
import type { LegState, Order, StrategyEvent } from '@/types/strategy_module'

const INTERVAL_SEC: Record<string, number> = { '1m': 60, '5m': 300, '15m': 900 }
const UP = '#26a69a'
const DOWN = '#ef5350'
const VOL_UP = 'rgba(38,166,154,0.45)'
const VOL_DOWN = 'rgba(239,83,80,0.45)'
const OVERLAY_COLOR: Record<string, string> = {
  ema9: '#f59e0b',
  ema15: '#3b82f6',
  ema5: '#a855f7',
  ema50: '#22c55e',
  ema200: '#ef4444',
  sma5: '#f59e0b',
  sma34: '#3b82f6',
  middle: '#64748b',
  upper: '#94a3b8',
  lower: '#94a3b8',
}
const LEVEL_COLOR = {
  entry: '#e2e8f0',
  sl: '#ef4444',
  target: '#22c55e',
  ltp: '#94a3b8',
}

interface Candle extends OverlayBar {
  volume: number
}

function latestEvaluation(events: StrategyEvent[]): StrategyEvent | null {
  return events.find((event) => event.kind === 'signal_evaluation') ?? null
}

export function StrategyLiveChart({
  strategyId,
  underlying,
  underlyingExchange,
  scalpProfile,
  orders = [],
  legs = [],
  compact = false,
}: {
  strategyId: number
  underlying?: string | null
  underlyingExchange?: string | null
  scalpProfile?: string | null
  orders?: Order[]
  legs?: LegState[]
  compact?: boolean
}) {
  const profile = useMemo(
    () =>
      strategyChartProfile({
        underlying,
        underlying_exchange: underlyingExchange,
        scalp_profile: scalpProfile,
      }),
    [underlying, underlyingExchange, scalpProfile]
  )
  const eventsQuery = useQuery({
    queryKey: ['strategy-live-chart-events', strategyId],
    queryFn: () => listEvents(strategyId, 80),
    enabled: strategyId > 0,
    refetchInterval: 15000,
  })
  const events = eventsQuery.data ?? []
  const interval = profile?.interval ?? '5m'
  const intervalSec = INTERVAL_SEC[interval] ?? 300
  const fills = useMemo(() => fillMarkers(orders, intervalSec), [orders, intervalSec])
  const signals = useMemo(() => confirmedSignalMarkers(events, intervalSec), [events, intervalSec])
  const markers = useMemo(() => (fills.length ? fills : signals), [fills, signals])
  const levels = useMemo(() => legLevels(legs), [legs])
  const staleHistory = Boolean(
    latestEvaluation(events)?.payload &&
      /unavailable|no usable|collecting/i.test(
        String(latestEvaluation(events)?.payload?.reason ?? latestEvaluation(events)?.message ?? '')
      )
  )

  if (!profile) {
    return (
      <div
        data-testid="strategy-live-chart"
        className="flex h-64 items-center justify-center rounded-lg border bg-card text-sm text-muted-foreground"
      >
        This strategy has no chartable underlying.
      </div>
    )
  }

  return (
    <LivePane
      profile={profile}
      markers={markers}
      levels={levels}
      staleHistory={staleHistory}
      compact={compact}
      monitoring={legs.length === 0 && fills.length === 0}
    />
  )
}

function LivePane({
  profile,
  markers,
  levels,
  staleHistory,
  compact,
  monitoring,
}: {
  profile: NonNullable<ReturnType<typeof strategyChartProfile>>
  markers: ReturnType<typeof fillMarkers>
  levels: ReturnType<typeof legLevels>
  staleHistory: boolean
  compact: boolean
  monitoring: boolean
}) {
  const { mode } = useThemeStore()
  const isDark = mode === 'dark'
  const { symbol, exchange, interval, indicators } = profile
  const containerRef = useRef<HTMLDivElement | null>(null)
  const legendRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const overlayRefs = useRef<Map<string, ISeriesApi<'Line'>>>(new Map())
  const markersPluginRef = useRef<{
    setMarkers: (markers: SeriesMarker<UTCTimestamp>[]) => void
  } | null>(null)
  const priceLinesRef = useRef<IPriceLine[]>([])
  const renderLegendRef = useRef<(time?: number) => void>(() => {})
  const colorsRef = useRef({ title: '#d6dde6', muted: '#8a97a5' })
  const candlesRef = useRef<Map<number, Candle>>(new Map())
  const sortedRef = useRef<Candle[]>([])
  const idxByTimeRef = useRef<Map<number, number>>(new Map())
  const currentBucketRef = useRef<number | null>(null)
  const tradingDateRef = useRef<string | null>(null)
  const intervalSecRef = useRef(INTERVAL_SEC[interval] ?? 300)
  const intervalRef = useRef(interval)
  const barStartVolRef = useRef<number | null>(null)
  const readyRef = useRef(false)
  const [status, setStatus] = useState('')
  const [historyReady, setHistoryReady] = useState(false)
  const [barVersion, setBarVersion] = useState(0)
  const [biasLabel, setBiasLabel] = useState('')

  const enabled = !!(symbol && exchange)
  const { data } = useMarketData({
    symbols: enabled ? [{ symbol, exchange }] : [],
    mode: 'Quote',
    enabled,
    autoReconnect: true,
  })

  useEffect(() => {
    const container = containerRef.current
    if (!container || !enabled) return
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
      },
      crosshair: { mode: CrosshairMode.Normal },
    })
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderVisible: false,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceFormat: { type: 'price', precision: decimals, minMove: 10 ** -decimals },
      autoscaleInfoProvider: () => {
        const arr = sortedRef.current
        if (!arr.length) return null
        let min = arr[0].low
        let max = arr[0].high
        for (const bar of arr) {
          min = Math.min(min, bar.low)
          max = Math.max(max, bar.high)
        }
        const pad = Math.max((max - min) * 0.08, min * 0.001)
        return { priceRange: { minValue: min - pad, maxValue: max + pad } }
      },
    })
    const vol = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
      visible: false,
    })
    chartRef.current = chart
    candleRef.current = candle
    volRef.current = vol
    markersPluginRef.current = createSeriesMarkers(candle, [])
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
      const liveClose = sortedRef.current[sortedRef.current.length - 1]
      const { title: titleColor, muted } = colorsRef.current
      const liveBit =
        liveClose && liveClose.time !== bar.time
          ? ` <span style="color:${muted}">Live ${liveClose.close.toFixed(decimals)}</span>`
          : ''
      el.innerHTML =
        `<div style="color:${titleColor};font-weight:600">${symbol} ` +
        `<span style="color:${muted};font-weight:500">· ${intervalRef.current} · ${exchange}</span></div>` +
        `<div style="color:${bar.close >= bar.open ? UP : DOWN};margin-top:1px">` +
        `O ${bar.open.toFixed(decimals)} H ${bar.high.toFixed(decimals)} ` +
        `L ${bar.low.toFixed(decimals)} C ${bar.close.toFixed(decimals)}${liveBit}</div>`
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
      overlayRefs.current.clear()
      markersPluginRef.current = null
      priceLinesRef.current = []
    }
  }, [symbol, exchange, enabled, isDark])

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
    intervalSecRef.current = INTERVAL_SEC[interval] ?? 300
    intervalRef.current = interval
    readyRef.current = false
    setHistoryReady(false)
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
        arr.map((k) => ({
          time: k.time as UTCTimestamp,
          open: k.open,
          high: k.high,
          low: k.low,
          close: k.close,
        }))
      )
      vol.setData(
        arr.map((k) => ({
          time: k.time as UTCTimestamp,
          value: k.volume,
          color: k.close >= k.open ? VOL_UP : VOL_DOWN,
        }))
      )
      applyOverlays(arr)
      if (range) {
        try {
          ts.setVisibleLogicalRange(range)
        } catch {
          /* range no longer valid */
        }
      } else {
        const view = visibleLogicalRange(arr.length, compact)
        ts.setVisibleLogicalRange(view)
      }
      renderLegendRef.current()
      setBarVersion((value) => value + 1)
    }

    const applyOverlays = (arr: Candle[]) => {
      const completed = currentBucketRef.current
        ? arr.filter((bar) => bar.time < currentBucketRef.current!)
        : arr
      const wanted = new Map<string, { time: number; value: number }[]>()
      if (indicators.includes('ema9')) wanted.set('ema9', emaSeries(completed, 9, 75))
      if (indicators.includes('ema15')) wanted.set('ema15', emaSeries(completed, 15, 75))
      if (indicators.includes('ema5')) wanted.set('ema5', emaSeries(completed, 5, 5))
      if (indicators.includes('ema50')) wanted.set('ema50', emaSeries(completed, 50, 50))
      if (indicators.includes('ema200')) wanted.set('ema200', emaSeries(completed, 200, 200))
      if (indicators.includes('sma5')) wanted.set('sma5', smaSeries(completed, 5))
      if (indicators.includes('sma34')) wanted.set('sma34', smaSeries(completed, 34))
      if (indicators.includes('bollinger')) {
        const bands = bollingerSeries(completed, 20, 2)
        wanted.set('middle', bands.middle)
        wanted.set('upper', bands.upper)
        wanted.set('lower', bands.lower)
      }
      for (const [key, seriesApi] of overlayRefs.current) {
        if (!wanted.has(key)) {
          chart.removeSeries(seriesApi)
          overlayRefs.current.delete(key)
        }
      }
      for (const [key, points] of wanted) {
        let seriesApi = overlayRefs.current.get(key)
        if (!seriesApi) {
          seriesApi = chart.addSeries(LineSeries, {
            color: OVERLAY_COLOR[key] ?? '#94a3b8',
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: true,
            title: key,
          })
          overlayRefs.current.set(key, seriesApi)
        }
        seriesApi.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })))
      }
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
        const fetched = plausibleHistoryTail(
          d.candles || [],
          0.25,
          data.get(`${exchange}:${symbol}`)?.data?.ltp ?? null
        )
        if (!fetched.length) return
        let changed = false
        const nowBucket =
          Math.floor((Math.floor(Date.now() / 1000) + CHART_IST_OFFSET) / intervalSecRef.current) *
          intervalSecRef.current
        for (const k of fetched) {
          if (k.time >= nowBucket) continue
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
        /* next cycle retries */
      } finally {
        inflight = false
      }
    }

    const schedule = () => {
      timer = setTimeout(async () => {
        await reconcile()
        if (!disposed) schedule()
      }, 5000)
    }

    scalpingApi
      .getHistory(symbol, exchange, interval)
      .then((d) => {
        if (disposed) return
        if (d.status !== 'success') {
          setStatus(d.message || 'Market history unavailable')
          schedule()
          return
        }
        const candles = plausibleHistoryTail(
          d.candles || [],
          0.25,
          data.get(`${exchange}:${symbol}`)?.data?.ltp ?? null
        )
        const todayIst = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
        tradingDateRef.current = d.date && d.date === todayIst ? d.date : null
        if (!candles.length) {
          readyRef.current = true
          currentBucketRef.current = null
          setStatus('waiting for live ticks…')
          schedule()
          return
        }
        candlesRef.current = new Map(candles.map((k) => [k.time, { ...k }]))
        const lastTime = candles[candles.length - 1].time
        const nowBucket =
          Math.floor((Math.floor(Date.now() / 1000) + CHART_IST_OFFSET) / intervalSecRef.current) *
          intervalSecRef.current
        currentBucketRef.current = lastTime === nowBucket ? lastTime : null
        applyModel(false)
        setStatus('')
        setHistoryReady(true)
        readyRef.current = true
        schedule()
      })
      .catch(() => {
        if (!disposed) {
          setStatus('Market history unavailable')
          schedule()
        }
      })

    return () => {
      disposed = true
      readyRef.current = false
      if (timer) clearTimeout(timer)
    }
  }, [symbol, exchange, interval, enabled, indicators, compact])

  // historyReady is the candle series becoming available; markers cannot attach before that.
  // biome-ignore lint/correctness/useExhaustiveDependencies: historyReady gates first attach after history load
  useEffect(() => {
    const plugin = markersPluginRef.current
    if (!plugin) return
    const candleTimes = sortedRef.current.map((bar) => bar.time)
    const completed = sortedRef.current.filter(
      (bar) => currentBucketRef.current == null || bar.time < currentBucketRef.current
    )
    const bias = !markers.length ? lastBarBiasMarker(completed, indicators) : null
    const plotted = bias ? [...markers, bias] : markers
    const seriesMarkers: SeriesMarker<UTCTimestamp>[] = []
    for (const marker of plotted) {
      const time = snapToCandle(marker.time, candleTimes, INTERVAL_SEC[interval] ?? 300)
      if (time == null) continue
      seriesMarkers.push({
        time: time as UTCTimestamp,
        position: marker.kind.includes('sell') ? 'aboveBar' : 'belowBar',
        color: marker.kind.includes('sell') ? DOWN : UP,
        shape: marker.kind.includes('sell') ? 'arrowDown' : 'arrowUp',
        text: marker.label,
        size: 2,
      })
    }
    plugin.setMarkers(seriesMarkers)
    setBiasLabel(plotted.at(-1)?.label ?? '')
  }, [markers, historyReady, indicators, interval, barVersion])

  const tick = data.get(`${exchange}:${symbol}`)?.data
  const ltp = tick?.ltp
  const ts = tick?.timestamp
  const tickVol = typeof tick?.volume === 'number' ? tick.volume : null

  // biome-ignore lint/correctness/useExhaustiveDependencies: historyReady gates first attach after history load
  useEffect(() => {
    const candle = candleRef.current
    if (!candle) return
    for (const line of priceLinesRef.current) candle.removePriceLine(line)
    priceLinesRef.current = []
    const range = indicators.includes('openingRange')
      ? openingRange(
          sortedRef.current,
          profile.session === 'mcx' ? 9 : 9,
          profile.session === 'mcx' ? 0 : 15
        )
      : null
    const extra = range
      ? [
          { price: range.high, kind: 'target' as const, label: 'OR High' },
          { price: range.low, kind: 'sl' as const, label: 'OR Low' },
        ]
      : []
    const liveQuote = data.get(`${exchange}:${symbol}`)?.data?.ltp
    const lastClose = sortedRef.current.at(-1)?.close ?? null
    const liveLevel =
      liveQuote != null && isPlausibleLivePrice(liveQuote, lastClose)
        ? [{ price: liveQuote, kind: 'ltp' as const, label: 'Live' }]
        : []
    for (const level of [...levels, ...extra, ...liveLevel]) {
      const line = candle.createPriceLine({
        price: level.price,
        color: LEVEL_COLOR[level.kind] ?? '#94a3b8',
        lineWidth: 1,
        lineStyle: level.kind === 'entry' ? LineStyle.Solid : LineStyle.Dashed,
        axisLabelVisible: true,
        title: level.label,
      })
      priceLinesRef.current.push(line)
    }
  }, [levels, historyReady, indicators, profile.session, ltp])

  useEffect(() => {
    const candle = candleRef.current
    const vol = volRef.current
    if (!candle || !vol || !readyRef.current || ltp == null || !Number.isFinite(ltp)) return
    const lastBar = sortedRef.current.at(-1)
    const forming = lastBar != null && lastBar.time === currentBucketRef.current
    const reference = forming ? sortedRef.current.at(-2) : lastBar
    if (!isPlausibleLivePrice(ltp, reference?.close ?? lastBar?.close ?? null)) return
    const sec = intervalSecRef.current
    const nowBucket = Math.floor((Math.floor(Date.now() / 1000) + CHART_IST_OFFSET) / sec) * sec
    const parsed = ts ? Date.parse(ts) : Number.NaN
    const tickBucket = Number.isNaN(parsed)
      ? nowBucket
      : Math.floor((Math.floor(parsed / 1000) + CHART_IST_OFFSET) / sec) * sec
    const bucket = tickBucket === nowBucket ? tickBucket : nowBucket
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
      return
    }
    candlesRef.current.set(bucket, bar)
    const arr = sortedRef.current
    if (isNew) {
      arr.push(bar)
      idxByTimeRef.current.set(bucket, arr.length - 1)
    } else if (arr.length) {
      arr[arr.length - 1] = bar
    }
    candle.update({
      time: bar.time as UTCTimestamp,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    })
    vol.update({
      time: bar.time as UTCTimestamp,
      value: bar.volume,
      color: bar.close >= bar.open ? VOL_UP : VOL_DOWN,
    })
    if (isNew) {
      setBarVersion((value) => value + 1)
      try {
        chartRef.current?.timeScale().scrollToRealTime()
      } catch {
        /* viewport unchanged */
      }
    }
    renderLegendRef.current()
    setStatus((s) => (s ? '' : s))
  }, [ltp, ts, tickVol])

  const banner = staleHistory
    ? 'Not plotting a signal: market history is incomplete or stale.'
    : status
      ? status
      : monitoring
        ? 'Monitoring, no position.'
        : ''

  return (
    <div
      data-testid="strategy-live-chart"
      className={`relative w-full overflow-hidden rounded-lg border bg-card ${compact ? 'h-56' : 'h-80'}`}
    >
      <div ref={containerRef} className="absolute inset-0" />
      <div
        ref={legendRef}
        className="pointer-events-none absolute left-2.5 top-2 z-10 font-mono text-[11px] leading-tight"
      />
      {(biasLabel || levels.length > 0) && (
        <div className="pointer-events-none absolute right-2 top-2 z-10 max-w-[50%] text-right font-mono text-[10px] leading-tight text-muted-foreground">
          {biasLabel && (
            <div className={biasLabel === 'SELL' ? 'text-red-500' : 'text-emerald-500'}>
              {biasLabel}
            </div>
          )}
          {levels.map((level) => (
            <div key={`${level.kind}-${level.label}`}>
              {level.label} {level.price.toFixed(2)}
            </div>
          ))}
        </div>
      )}
      {banner && (
        <div className="pointer-events-none absolute bottom-2 left-2 right-2 z-10 rounded bg-background/80 px-2 py-1 text-xs text-muted-foreground">
          {banner}
        </div>
      )}
    </div>
  )
}
