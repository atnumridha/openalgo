import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CandlestickSeries,
  CrosshairMode,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  LineSeries,
  LineStyle,
  TickMarkType,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { ChartReplayControls } from '../kotak-assistant/ChartReplayControls'
import { candleKey, publishChartCandles } from '../kotak-assistant/chartCandleStore'
import {
  replayBars,
  istSessionDate,
  chartRangeBars,
  chartRangeBounds,
  type ChartDateRange,
  replaySeconds,
  replayStamp,
  type ReplayFrame,
} from '../kotak-assistant/chartReplay'
import { loadChartRangeHistory } from '../kotak-assistant/chartRangeHistory'
import { FairValueGapLegend } from '../kotak-assistant/FairValueGapLegend'
import { neoDeskApi } from '@/api/neoDesk'
import { neoReportsApi } from '@/api/neoReports'
import { scalpingApi } from '@/api/scalping'
import { Button } from '@/components/ui/button'
import { useMarketData } from '@/hooks/useMarketData'
import { useThemeStore } from '@/stores/themeStore'
import { feedTimeMs, nextLiveBar } from './liveBars'
import {
  chartBars,
  computeStudies,
  formatIST,
  openingRange,
  type PriceBar,
  type GapZone,
  reconcileHistory,
} from './tradingViewStudies'
import { TradingViewZones } from './tradingViewZones'

const choices = [
  ['neo-donchian', 'Donchian / EMA'],
  ['neo-structure', 'Fair Value Gaps / levels'],
  ['rsi', 'RSI 14'],
] as const
type History = Awaited<ReturnType<typeof scalpingApi.getHistory>>
interface Scene {
  chart: IChartApi
  price: ISeriesApi<'Candlestick'>
  upper: ISeriesApi<'Line'>
  lower: ISeriesApi<'Line'>
  ema: ISeriesApi<'Line'>
  rsi: ISeriesApi<'Line'> | null
  zones: TradingViewZones
  structure: IPriceLine[]
}
export function NeoMarketChart({
  symbol,
  exchange,
  interval,
  title,
  studies,
  initialHistory,
  compact = false,
  savedRange,
}: {
  symbol: string
  exchange: string
  interval: string
  title?: string
  studies?: string[]
  initialHistory?: History
  compact?: boolean
  savedRange?: { start: string; end: string }
}) {
  const host = useRef<HTMLDivElement>(null),
    scene = useRef<Scene | null>(null),
    bars = useRef<PriceBar[]>([]),
    shownBars = useRef<PriceBar[]>([]),
    calculationBars = useRef<PriceBar[]>([]),
    viewportSet = useRef(false),
    liveBar = useRef<PriceBar | null>(null)
  const [ready, setReady] = useState(0),
    [renderError, setRenderError] = useState(''),
    [hover, setHover] = useState<PriceBar | null>(null),
    [last, setLast] = useState<PriceBar | null>(null)
  const [localStudies, setLocalStudies] = useState<string[]>(() => {
    try {
      const stored = JSON.parse(localStorage.getItem('neo.native.chart.indicators') || 'null')
      return Array.isArray(stored)
        ? stored.filter((id) => choices.some((c) => c[0] === id))
        : choices.map((c) => c[0])
    } catch {
      return choices.map((c) => c[0])
    }
  })
  const enabled = studies ?? localStudies,
    enabledRef = useRef(enabled)
  enabledRef.current = enabled
  const mode = useThemeStore((s) => s.mode)
  const appMode = useThemeStore((s) => s.appMode)
  const username = useAuthStore((s) => s.user?.username)
  const replayKey = useMemo(
    () =>
      `neo-trading:${candleKey(username, appMode, symbol, exchange, interval)}:${JSON.stringify(savedRange ?? null)}`,
    [username, appMode, symbol, exchange, interval, savedRange?.start, savedRange?.end]
  )
  const [today, setToday] = useState(() => istSessionDate())
  // A null selection follows the IST calendar when this page stays open overnight.
  const [selectedRange, setSelectedRange] = useState<ChartDateRange | null>(null)
  const sessionDate = selectedRange?.start ?? today
  const sessionEndDate = selectedRange?.end ?? today
  const dateLabel =
    sessionDate === sessionEndDate ? sessionDate : `${sessionDate} → ${sessionEndDate}`
  const replayScope = `${replayKey}:${sessionDate}:${sessionEndDate}`
  const queryClient = useQueryClient()
  const replayKeys = useMemo(() => [replayKey], [replayKey])
  const [frame, setFrame] = useState<ReplayFrame | null>(null)
  const replay = frame?.scope === replayScope ? frame : null
  const replayRef = useRef(replay)
  replayRef.current = replay
  const [gapZones, setGapZones] = useState<GapZone[]>([])
  const publishLive = () =>
    publishChartCandles(
      replayKey,
      bars.current.map((bar) => ({ ...bar, time: bar.time + 19800 }))
    )

  const market = useMarketData({
    symbols: symbol ? [{ symbol, exchange }] : [],
    mode: 'Quote',
    enabled: Boolean(symbol) && !savedRange,
    autoReconnect: true,
  })
  const history = useQuery({
    queryKey: ['neo-tv-history', exchange, symbol, interval, savedRange?.start, savedRange?.end],
    enabled: Boolean(symbol && exchange),
    queryFn: async () => {
      const result: History = savedRange
        ? await neoReportsApi.chart(symbol, exchange, interval, savedRange.start, savedRange.end)
        : await scalpingApi.getHistory(symbol, exchange, interval)
      if (result.status !== 'success')
        throw Error(result.message || 'Kotak history unavailable. Refresh the broker connection.')
      return result
    },
    initialData:
      !savedRange &&
      initialHistory?.symbol === symbol &&
      initialHistory.exchange === exchange &&
      initialHistory.interval === interval
        ? initialHistory
        : undefined,
    staleTime: 20000,
    refetchInterval: savedRange ? false : 25000,
    retry: 1,
  })
  const rangeHistory = useQuery({
    queryKey: [
      'neo-tv-range',
      username,
      appMode,
      exchange,
      symbol,
      interval,
      sessionDate,
      sessionEndDate,
    ],
    enabled: Boolean(selectedRange && symbol && exchange && !savedRange),
    queryFn: async ({ signal }) => {
      const range = { start: sessionDate, end: sessionEndDate }
      const warmupDays =
        interval === '1d' ? 400 : Math.ceil(((200 * replaySeconds(interval)) / 22500) * 1.6) + 7
      const warmupStart = new Date(Date.parse(`${range.start}T00:00:00Z`) - warmupDays * 86400000)
        .toISOString()
        .slice(0, 10)
      let warmup = history.data?.candles ?? []
      try {
        const archived = await neoReportsApi.chart(
          symbol,
          exchange,
          interval,
          warmupStart,
          range.start
        )
        warmup = [...(archived?.candles ?? []), ...warmup]
      } catch {
        // Broker day history below remains authoritative for the requested dates.
      }
      return loadChartRangeHistory(
        range,
        (date) => {
          const loaded = chartRangeBars(history.data?.candles ?? [], date, date, 19800)
          if (loaded.length) return Promise.resolve({ status: 'success', candles: loaded })
          return queryClient.fetchQuery({
            queryKey: ['neo-tv-day', username, appMode, exchange, symbol, interval, date],
            queryFn: () => scalpingApi.getHistory(symbol, exchange, interval, date),
            staleTime: date === today ? 20000 : 60000,
            retry: false,
          })
        },
        warmup,
        signal
      )
    },
    staleTime: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  })
  const rangeLoading = !!selectedRange && !savedRange && rangeHistory.isPending
  const rangeError = !!selectedRange && !savedRange && rangeHistory.isError
  const info = useQuery({
    queryKey: ['neo-chart', exchange, symbol, interval],
    enabled: Boolean(symbol && exchange) && !savedRange,
    queryFn: () => neoDeskApi.chart(`${exchange}:${symbol}`, interval),
    refetchInterval: 2000,
  })
  const desk = useQuery({
    queryKey: ['neo-desk'],
    enabled: !savedRange,
    queryFn: neoDeskApi.state,
    refetchInterval: 2000,
  })
  const profile = savedRange ? '' : (desk.data?.profile ?? '')
  const profileRef = useRef(profile)
  profileRef.current = profile
  useEffect(() => {
    if (!studies) {
      try {
        localStorage.setItem('neo.native.chart.indicators', JSON.stringify(localStudies))
      } catch {
        /* Keep this view's choice. */
      }
    }
  }, [localStudies, studies])

  function drawStudies(s: Scene) {
    const computed = computeStudies(
        calculationBars.current,
        interval,
        replayRef.current ? replayRef.current.until - 19800 : Date.now() / 1000
      ),
      on = enabledRef.current.includes('neo-donchian')
    const forSession = (values: typeof computed.ema) =>
      savedRange ? values : chartRangeBars(values, sessionDate, sessionEndDate)
    for (const [series, values] of [
      [s.upper, computed.upper],
      [s.lower, computed.lower],
      [s.ema, computed.ema],
    ] as const) {
      series.setData(forSession(values))
      series.applyOptions({ visible: on })
    }
    if (enabledRef.current.includes('rsi')) {
      if (!s.rsi) {
        s.rsi = s.chart.addSeries(
          LineSeries,
          {
            color: '#b39ddb',
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: true,
            priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
          },
          1
        )
        s.rsi.createPriceLine({
          price: 70,
          color: '#686d7a',
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: false,
          title: '',
        })
        s.rsi.createPriceLine({
          price: 30,
          color: '#686d7a',
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: false,
          title: '',
        })
        s.chart.panes()[0]?.setStretchFactor(4)
        s.chart.panes()[1]?.setStretchFactor(1)
      }
      s.rsi.setData(forSession(computed.rsi))
    } else if (s.rsi) {
      s.chart.removeSeries(s.rsi)
      s.rsi = null
    }
    for (const line of s.structure) s.price.removePriceLine(line)
    s.structure = []
    const structure = enabledRef.current.includes('neo-structure')
    const visibleGaps =
      structure && shownBars.current.length
        ? computed.zones.map((gap) => ({
            ...gap,
            time: Math.max(gap.time, shownBars.current[0].time),
          }))
        : []
    s.zones.setZones(visibleGaps)
    setGapZones((old) => (JSON.stringify(old) === JSON.stringify(visibleGaps) ? old : visibleGaps))
    function level(price: number | null, title: string, color: string) {
      if (price != null)
        s.structure.push(
          s.price.createPriceLine({
            price,
            title,
            color,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: false,
          })
        )
    }
    if (structure && shownBars.current.length) {
      level(computed.support, 'Support', '#26a69a')
      level(computed.resistance, 'Resistance', '#ef5350')
    }
    if (
      symbol === 'NIFTY' &&
      exchange === 'NSE_INDEX' &&
      profileRef.current.startsWith('orb') &&
      ['1m', '3m', '5m', '15m'].includes(interval)
    ) {
      const range = openingRange(
        shownBars.current,
        replayRef.current ? replayRef.current.until - 19800 : undefined
      )
      if (range) {
        level(range.high, 'Opening high', '#78909c')
        level(range.low, 'Opening low', '#78909c')
      }
    }
  }
  const drawRef = useRef(drawStudies)
  drawRef.current = drawStudies
  function focusLatest() {
    const count = shownBars.current.length
    const slots = Math.max(30, Math.floor((host.current?.clientWidth || 800) / 8))
    scene.current?.chart.timeScale().setVisibleLogicalRange({ from: count - slots, to: count + 8 })
  }
  const paintRef = useRef<(reset: boolean) => void>(() => {})
  paintRef.current = (reset) => {
    const s = scene.current
    if (!s) return
    const replay = replayRef.current
    const available = replay
      ? replayBars(replay.series[replayKey] || [], replay.seconds, replay.until).map((bar) => ({
          ...bar,
          time: bar.time - 19800,
        }))
      : rangeLoading || rangeError
        ? []
        : bars.current
    const bounds = savedRange ? null : chartRangeBounds(sessionDate, sessionEndDate)
    const warmup = bounds ? available.filter((bar) => bar.time < bounds.end) : available
    const visible = savedRange ? warmup : chartRangeBars(warmup, sessionDate, sessionEndDate)
    calculationBars.current = visible.length ? warmup : []
    shownBars.current = visible
    s.price.setData(visible.map((bar) => ({ ...bar, time: bar.time as UTCTimestamp })))
    drawRef.current(s)
    setLast(visible.at(-1) ?? null)
    setHover(null)
    if (reset && visible.length) focusLatest()
  }
  useLayoutEffect(() => {
    paintRef.current(true)
  }, [replay, ready, sessionDate, sessionEndDate, rangeLoading, rangeError])
  useEffect(() => {
    if (savedRange) return
    const seconds = replaySeconds(interval)
    if (!seconds) return
    let previous = Math.floor(Date.now() / 1000 / seconds)
    const timer = setInterval(() => {
      setToday(istSessionDate())
      const bucket = Math.floor(Date.now() / 1000 / seconds)
      if (bucket !== previous) {
        previous = bucket
        if (!replayRef.current && scene.current) drawRef.current(scene.current)
      }
    }, 1000)
    return () => clearInterval(timer)
  }, [interval, savedRange?.start, savedRange?.end])

  useEffect(() => {
    if (!host.current || !symbol || !exchange) return
    let s: Scene | null = null
    try {
      const dark = mode === 'dark' || appMode === 'analyzer',
        background = dark ? '#131722' : '#ffffff',
        text = dark ? '#b2b5be' : '#434651'
      const chart = createChart(host.current, {
        autoSize: true,
        layout: {
          background: { color: background },
          textColor: text,
          fontFamily: 'Inter, system-ui, sans-serif',
          fontSize: 12,
          attributionLogo: true,
          panes: {
            separatorColor: dark ? '#2a2e39' : '#e1e3eb',
            separatorHoverColor: '#434651',
            enableResize: true,
          },
        },
        grid: {
          vertLines: { color: dark ? '#1e222d' : '#f0f3fa' },
          horzLines: { color: dark ? '#1e222d' : '#f0f3fa' },
        },
        crosshair: {
          mode: CrosshairMode.Normal,
          vertLine: { color: '#787b86', labelBackgroundColor: '#363a45' },
          horzLine: { color: '#787b86', labelBackgroundColor: '#363a45' },
        },
        rightPriceScale: {
          borderColor: dark ? '#2a2e39' : '#e1e3eb',
          scaleMargins: { top: 0.13, bottom: 0.12 },
        },
        timeScale: {
          borderColor: dark ? '#2a2e39' : '#e1e3eb',
          timeVisible: interval !== '1d',
          secondsVisible: false,
          rightOffset: 8,
          barSpacing: 8,
          minBarSpacing: 3,
          tickMarkFormatter: (time: Time, type: TickMarkType) =>
            typeof time === 'number'
              ? type === TickMarkType.Time || type === TickMarkType.TimeWithSeconds
                ? formatIST(time)
                : new Intl.DateTimeFormat('en-GB', {
                    timeZone: 'Asia/Kolkata',
                    day: '2-digit',
                    month: 'short',
                  }).format(new Date(time * 1000))
              : null,
        },
        localization: {
          locale: 'en-IN',
          timeFormatter: (time: Time) =>
            typeof time === 'number'
              ? interval === '1d'
                ? new Intl.DateTimeFormat('en-GB', {
                    timeZone: 'Asia/Kolkata',
                    day: '2-digit',
                    month: 'short',
                    year: 'numeric',
                  }).format(new Date(time * 1000))
                : `${formatIST(time, true)} IST`
              : String(time),
        },
      })
      const price = chart.addSeries(CandlestickSeries, {
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
        priceLineColor: '#787b86',
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      })
      const line = (color: string, width: 1 | 2 = 1) =>
        chart.addSeries(LineSeries, {
          color,
          lineWidth: width,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
      const zones = new TradingViewZones(dark)
      price.attachPrimitive(zones)
      s = {
        chart,
        price,
        upper: line('#5b8def'),
        lower: line('#5b8def'),
        ema: line('#dca94c', 2),
        rsi: null,
        zones,
        structure: [],
      }
      scene.current = s
      viewportSet.current = false
      liveBar.current = null
      bars.current = []
      shownBars.current = []
      calculationBars.current = []
      publishLive()
      setLast(null)
      chart.subscribeCrosshairMove((param) => {
        const point = param.seriesData.get(price)
        setHover(
          point && 'close' in point ? { ...point, time: Number(param.time), volume: 0 } : null
        )
      })
      setRenderError('')
      setReady((n) => n + 1)
    } catch (e) {
      setRenderError((e as Error).message || 'TradingView chart could not initialize.')
    }
    return () => {
      s?.chart.remove()
      if (scene.current === s) scene.current = null
    }
  }, [mode, appMode, symbol, exchange, interval, username])

  // biome-ignore lint/correctness/useExhaustiveDependencies: imperative chart and study changes must replay into the current scene
  useEffect(() => {
    const s = scene.current
    if (!s || (!history.data && !rangeHistory.data)) return
    const incoming = reconcileHistory(
      chartBars([
        ...(selectedRange ? (rangeHistory.data?.candles ?? []) : []),
        ...(history.data?.candles || []),
      ]),
      viewportSet.current ? liveBar.current : null
    )
    bars.current = incoming
    publishLive()
    if (replayRef.current) return
    paintRef.current(!viewportSet.current)
    if (incoming.length) viewportSet.current = true
  }, [ready, history.data, rangeHistory.data, selectedRange])
  // biome-ignore lint/correctness/useExhaustiveDependencies: imperative chart and study changes must replay into the current scene
  useEffect(() => {
    if (scene.current) drawRef.current(scene.current)
  }, [ready, enabled, profile])
  // biome-ignore lint/correctness/useExhaustiveDependencies: imperative chart and study changes must replay into the current scene
  useEffect(() => {
    const s = scene.current
    if (!s || !info.data || savedRange || replayRef.current || sessionEndDate !== today) return
    const lines = info.data.overlays
      .filter((line) => Number.isFinite(Number(line.price)))
      .map((line) =>
        s.price.createPriceLine({
          price: Number(line.price),
          title: line.label,
          color: line.label.toUpperCase().includes('SL')
            ? '#ef5350'
            : line.label.toUpperCase().includes('TARGET')
              ? '#26a69a'
              : '#2962ff',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
        })
      )
    return () => {
      for (const line of lines) s.price.removePriceLine(line)
    }
  }, [ready, info.data, savedRange, !!replay, sessionEndDate, today])
  const tick = savedRange ? undefined : market.data.get(`${exchange}:${symbol}`)?.data
  useEffect(() => {
    const s = scene.current
    if (!s || !tick?.ltp || !bars.current.length) return
    const previous = bars.current.at(-1),
      raw = nextLiveBar(previous, Number(tick.ltp), tick.timestamp, interval, Date.now())
    const next = raw ? { ...raw, volume: raw.volume ?? 0 } : null
    if (!next) return
    if (previous?.time === next.time) bars.current[bars.current.length - 1] = next
    else bars.current.push(next)
    liveBar.current = next
    publishLive()
    if (
      replayRef.current ||
      rangeLoading ||
      rangeError ||
      !chartRangeBars([next], sessionDate, sessionEndDate).length
    )
      return
    const bounds = chartRangeBounds(sessionDate, sessionEndDate)!
    calculationBars.current = bars.current.filter((bar) => bar.time < bounds.end)
    shownBars.current = chartRangeBars(calculationBars.current, sessionDate, sessionEndDate)
    s.price.update({ ...next, time: next.time as UTCTimestamp })
    drawRef.current(s)
    liveBar.current = next
    setLast(next)
  }, [tick, interval, sessionDate, sessionEndDate, rangeLoading, rangeError])
  const candle = hover ?? last,
    timestamp = feedTimeMs(tick?.timestamp),
    age = timestamp ? Math.max(0, (Date.now() - timestamp) / 1000) : null
  const problems = [
    renderError,
    (history.error as Error)?.message,
    selectedRange ? (rangeHistory.error as Error)?.message : undefined,
    savedRange ? undefined : (info.error as Error)?.message,
  ].filter(Boolean)
  return (
    <section
      aria-label={`${title || symbol} TradingView chart`}
      className="flex h-full min-h-[420px] flex-col overflow-hidden rounded-md border bg-card"
    >
      <div className="shrink-0 border-b px-3 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <strong className="text-sm">{title || symbol}</strong>
            <span className="ml-2 text-xs text-muted-foreground">
              {exchange} · {interval} ·{' '}
              {replay ? `REPLAY · ${replayStamp(replay.until)}` : 'Kotak Neo'}
            </span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">
              {savedRange ? 'Saved close' : 'Broker LTP'}
            </span>
            <strong className="tabular-nums">
              {savedRange
                ? last
                  ? `₹${last.close.toFixed(2)}`
                  : 'No saved candles'
                : tick?.ltp
                  ? `₹${Number(tick.ltp).toFixed(2)}`
                  : 'Waiting for quote'}
            </strong>
          </div>
        </div>
        <section
          className="mt-1 flex flex-wrap gap-x-3 text-xs tabular-nums text-muted-foreground"
          aria-label="Candle prices"
        >
          {candle ? (
            <>
              <span>
                {interval === '1d'
                  ? new Intl.DateTimeFormat('en-GB', {
                      timeZone: 'Asia/Kolkata',
                      day: '2-digit',
                      month: 'short',
                      year: 'numeric',
                    }).format(new Date(candle.time * 1000))
                  : `${formatIST(candle.time, true)} IST`}
              </span>
              <span>O {candle.open.toFixed(2)}</span>
              <span>H {candle.high.toFixed(2)}</span>
              <span>L {candle.low.toFixed(2)}</span>
              <span className={candle.close >= candle.open ? 'text-emerald-500' : 'text-red-400'}>
                C {candle.close.toFixed(2)}
              </span>
            </>
          ) : (
            <span>
              {!symbol || !exchange
                ? 'Choose an expiry and strike to load prices.'
                : history.isPending || rangeLoading
                  ? 'Loading Kotak candles…'
                  : savedRange
                    ? 'No saved candles for these dates. Choose a recorded date range.'
                    : `No candles for ${dateLabel}. Choose other dates or refresh history.`}
            </span>
          )}
        </section>
        {!compact ? (
          <div className="mt-2 flex flex-wrap gap-3 text-xs">
            {choices.map(([id, label]) => (
              <label key={id} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={enabled.includes(id)}
                  onChange={(e) =>
                    setLocalStudies((old) =>
                      e.target.checked ? [...old, id] : old.filter((x) => x !== id)
                    )
                  }
                />
                {label}
              </label>
            ))}
          </div>
        ) : null}
        <section
          className="mt-1 flex gap-3 text-[11px] text-muted-foreground"
          aria-label="Active chart studies"
        >
          {enabled.includes('neo-donchian') ? (
            <>
              <span className="text-blue-400">Donchian 20</span>
              <span className="text-amber-500">EMA 200</span>
            </>
          ) : null}
          {enabled.includes('neo-structure') ? (
            <>
              <span>Support / resistance</span>
              <FairValueGapLegend
                gaps={gapZones.map((gap) => ({
                  direction: gap.bullish ? 'bullish' : 'bearish',
                  lower: gap.low,
                  upper: gap.high,
                  touched: gap.touched,
                }))}
              />
            </>
          ) : null}
          {enabled.includes('rsi') ? <span className="text-violet-400">RSI 14</span> : null}
          {symbol === 'NIFTY' &&
          profile.startsWith('orb') &&
          ['1m', '3m', '5m', '15m'].includes(interval) ? (
            <span>Opening range 09:15–09:30</span>
          ) : null}
        </section>
      </div>
      {!savedRange && (
        <ChartReplayControls
          key={replayScope}
          scope={replayScope}
          keys={replayKeys}
          interval={interval}
          onChange={setFrame}
          sessionDate={sessionDate}
          sessionEndDate={sessionEndDate}
          onSessionRangeChange={(range) =>
            setSelectedRange(
              range.start === istSessionDate() && range.end === range.start ? null : range
            )
          }
          loading={rangeLoading}
          unavailable={rangeError}
        />
      )}
      {selectedRange && rangeHistory.data?.emptyDates.length ? (
        <p
          role="status"
          aria-label="Date range coverage"
          className="border-b px-3 py-1 text-xs text-muted-foreground"
        >
          No candles on {rangeHistory.data.emptyDates.join(', ')}. Weekends are skipped.
        </p>
      ) : null}
      <div
        ref={host}
        className="relative min-h-0 flex-1"
        role="img"
        aria-label="TradingView candlesticks"
      />
      {problems.length ? (
        <div
          role="alert"
          className="flex shrink-0 items-center justify-between gap-2 border-t px-3 py-2 text-xs text-destructive"
        >
          <span>{problems.join('; ')}</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void history.refetch()
              if (selectedRange) void rangeHistory.refetch()
            }}
          >
            Retry history
          </Button>
        </div>
      ) : null}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t px-3 py-1 text-[11px] text-muted-foreground">
        <span>
          {savedRange
            ? `SQL saved history · ${savedRange.start} → ${savedRange.end}`
            : market.isConnected
              ? 'Feed connected'
              : 'Feed disconnected'}
          {age != null ? ` · last quote ${age.toFixed(0)}s ago` : ''} · {shownBars.current.length}{' '}
          candles · IST
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 text-xs"
          onClick={() => {
            focusLatest()
            scene.current?.price.priceScale().applyOptions({ autoScale: true })
          }}
        >
          Latest candles
        </Button>
      </div>
    </section>
  )
}
