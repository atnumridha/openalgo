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
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
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
import { readDeltaHistory, useDeltaCandle } from '../chart-toolkit/deltaFeed'
import {
  ToolkitEngine,
  completedReferences,
  type Result,
  type Reference,
} from '../chart-toolkit/model'
import { ToolkitLayer } from '../chart-toolkit/ToolkitLayer'
import { INDICATORS, NineIndicatorEngine, type NineResult } from '../chart-toolkit/nineIndicators'
import { NineIndicatorLayer } from '../chart-toolkit/NineIndicatorLayer'
import { NineIndicatorPanel } from '../chart-toolkit/NineIndicatorPanel'
import { BBChikouLayer } from '../chart-toolkit/BBChikouLayer'
import { calculateBBChikou } from '../chart-toolkit/bbChikou'
import { readHistorySnapshot, saveHistorySnapshot } from '../chart-toolkit/historySnapshot'
import {
  ToolkitPanel,
  type DisplaySettings,
  type OptionReference,
} from '../chart-toolkit/ToolkitPanel'

const choices = [
  ['neo-toolkit', 'Option buying · RSI + MACD'],
  ['bb-chikou', 'BB + Chikou · BULL / BEAR'],
  ['neo-donchian', 'Donchian / EMA'],
  ['neo-structure', 'Fair Value Gaps / levels'],
  ['rsi', 'RSI 14'],
  ...INDICATORS.map(item => [item.id, `${item.short} · CALL / PUT`] as const),
] as const
type History = Awaited<ReturnType<typeof scalpingApi.getHistory>>
const readHistory = async (
  symbol: string,
  exchange: string,
  interval: string,
  date?: string,
  signal?: AbortSignal
) => {
  try {
    return exchange === 'DELTA'
      ? await readDeltaHistory(
          symbol,
          interval,
          date,
          signal
            ? AbortSignal.any([signal, AbortSignal.timeout(12000)])
            : AbortSignal.timeout(12000)
        )
      : await scalpingApi.getHistory(symbol, exchange, interval, date, { signal, timeoutMs: 12000 })
  } catch (error) {
    if (
      (error as { code?: string }).code === 'ECONNABORTED' ||
      (error as Error).name === 'TimeoutError'
    )
      throw Error('Broker candles are delayed. Retry history in a moment.')
    throw error
  }
}
interface Scene {
  chart: IChartApi
  price: ISeriesApi<'Candlestick'>
  upper: ISeriesApi<'Line'>
  lower: ISeriesApi<'Line'>
  ema: ISeriesApi<'Line'>
  rsi: ISeriesApi<'Line'> | null
  zones: TradingViewZones
  structure: IPriceLine[]
  toolkit: ToolkitLayer
  bbChikou: BBChikouLayer
  nine: NineIndicatorLayer
  legacyActive: boolean
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
  optionReference,
  recentContext = false,
  focusMode = false,
  darkOverride,
}: {
  symbol: string
  exchange: string
  interval: string
  title?: string
  studies?: string[]
  initialHistory?: History
  compact?: boolean
  savedRange?: { start: string; end: string }
  optionReference?: OptionReference
  recentContext?: boolean
  focusMode?: boolean
  darkOverride?: boolean
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
        : choices.filter((c) => c[0] !== 'neo-toolkit' && c[0] !== 'bb-chikou' && !c[0].startsWith('nine-')).map((c) => c[0])
    } catch {
      return choices.filter((c) => c[0] !== 'neo-toolkit' && c[0] !== 'bb-chikou' && !c[0].startsWith('nine-')).map((c) => c[0])
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
  const [recentStart, setRecentStart] = useState(today)
  const sessionDate = selectedRange?.start ?? (recentContext ? recentStart : today)
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
  const [toolkitSettings, setToolkitSettings] = useState<DisplaySettings>({
    slow: 15,
    bands: false,
    markerLimit: 4,
    liquidity: false,
    trends: false,
    references: false,
    events: false,
  })
  const engine = useMemo(
    () =>
      new ToolkitEngine({ slow: toolkitSettings.slow, markerLimit: toolkitSettings.markerLimit }),
    [toolkitSettings.slow, toolkitSettings.markerLimit, symbol, exchange, interval]
  )
  const [toolkitResult, setToolkitResult] = useState<Result | null>(null)
  const [referenceLevels, setReferenceLevels] = useState<Reference[]>([])
  const toolkitOn = enabled.includes('neo-toolkit')
  const nineOn = enabled.some(id => id.startsWith('nine-'))
  const nineEngine = useMemo(() => new NineIndicatorEngine(), [symbol, exchange, interval])
  const [nineResult, setNineResult] = useState<NineResult | null>(null)
  const nineAsOf = useRef(0)
  const nineScope = `${symbol}:${exchange}:${interval}`
  const mfiProxy = useRef<{ scope: string; result: NineResult | null }>({ scope: nineScope, result: null })
  const onMfiProxy = useCallback((next: NineResult | null) => {
    if (mfiProxy.current.scope === nineScope && mfiProxy.current.result === next) return
    mfiProxy.current = { scope: nineScope, result: next }
    if (scene.current) drawRef.current(scene.current)
  }, [nineScope])
  const referenceReplayDate = replay
    ? new Date(replay.until * 1000).toISOString().slice(0, 10)
    : undefined
  const indian = ['NSE', 'NSE_INDEX', 'NFO', 'BSE', 'BSE_INDEX', 'BFO'].includes(exchange)
  const referenceHistory = useQuery({
    queryKey: [
      'toolkit-reference-history',
      username,
      appMode,
      symbol,
      exchange,
      savedRange?.start,
      savedRange?.end,
      selectedRange?.start,
      selectedRange?.end,
      referenceReplayDate,
    ],
    enabled: toolkitOn && !!toolkitSettings.references && !!symbol && !!exchange,
    queryFn: async ({ signal }) => {
      if (savedRange) {
        const result = await neoReportsApi.chart(
          symbol,
          exchange,
          '1h',
          new Date(Date.parse(savedRange.start) - 7 * 86400000).toISOString().slice(0, 10),
          savedRange.end
        )
        if (result.status !== 'success')
          throw Error(result.message || 'Reference candles unavailable')
        return chartBars(result.candles)
      }
      if (selectedRange || referenceReplayDate) {
        const range = {
          start: new Date(Date.parse(referenceReplayDate ?? selectedRange!.start) - 7 * 86400000)
            .toISOString()
            .slice(0, 10),
          end: referenceReplayDate ?? selectedRange!.end,
        }
        const result = await loadChartRangeHistory(
          range,
          (date) =>
            queryClient.fetchQuery({
              queryKey: ['toolkit-reference-day', username, appMode, symbol, exchange, date],
              queryFn: () => readHistory(symbol, exchange, '1h', date),
              staleTime: date === today ? 60000 : Infinity,
            }),
          [],
          signal,
          exchange === 'DELTA'
        )
        return chartBars(result.candles)
      }
      const result = await readHistory(symbol, exchange, '1h')
      if (result.status !== 'success')
        throw Error(result.message || 'Reference candles unavailable')
      return chartBars(result.candles)
    },
    staleTime: 60000,
    refetchInterval: savedRange ? false : 60000,
    retry: false,
  })
  const warmupHistory = useQuery({
    queryKey: ['toolkit-warmup', username, appMode, symbol, exchange, today],
    enabled:
      toolkitOn &&
      exchange !== 'DELTA' &&
      interval === '1m' &&
      !savedRange &&
      !!symbol &&
      !!exchange,
    queryFn: async () => {
      const dates = [1, 2, 3].map((days) =>
        new Date(Date.parse(today) - days * 86400000).toISOString().slice(0, 10)
      )
      const results = await Promise.allSettled(
        dates.map((date) => readHistory(symbol, exchange, '1m', date))
      )
      return results.flatMap((r) =>
        r.status === 'fulfilled' && r.value.status === 'success' ? r.value.candles : []
      )
    },
    staleTime: 300000,
    refetchOnWindowFocus: false,
    retry: false,
  })
  const publishLive = () =>
    publishChartCandles(
      replayKey,
      bars.current.map((bar) => ({ ...bar, time: bar.time + 19800 }))
    )

  const market = useMarketData({
    symbols: symbol ? [{ symbol, exchange }] : [],
    mode: 'Quote',
    enabled: Boolean(symbol) && !savedRange && exchange !== 'DELTA',
    autoReconnect: true,
  })
  const delta = useDeltaCandle(symbol, interval, exchange === 'DELTA' && !savedRange)
  const snapshot = useMemo(
    () =>
      savedRange ? undefined : readHistorySnapshot(username, appMode, symbol, exchange, interval),
    [username, appMode, symbol, exchange, interval, savedRange]
  )
  const history = useQuery({
    queryKey: ['neo-tv-history', exchange, symbol, interval, savedRange?.start, savedRange?.end],
    enabled: Boolean(symbol && exchange),
    queryFn: async ({ signal }) => {
      const result: History = savedRange
        ? await neoReportsApi.chart(symbol, exchange, interval, savedRange.start, savedRange.end)
        : await readHistory(symbol, exchange, interval, undefined, signal)
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
    placeholderData: snapshot,
    staleTime: 20000,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => (savedRange || query.state.status === 'error' ? false : 25000),
    retry: false,
  })
  const usingSnapshot = history.isPlaceholderData || (!history.data && !!snapshot)
  useEffect(() => {
    if (!savedRange && history.isSuccess && !history.isPlaceholderData)
      saveHistorySnapshot(username, appMode, history.data)
  }, [username, appMode, savedRange, history.data, history.isSuccess, history.isPlaceholderData])
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
            queryFn: () => readHistory(symbol, exchange, interval, date),
            staleTime: date === today ? 20000 : 60000,
            retry: false,
          })
        },
        warmup,
        signal,
        exchange === 'DELTA'
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
    enabled: Boolean(symbol && exchange) && !savedRange && exchange !== 'DELTA',
    queryFn: () => neoDeskApi.chart(`${exchange}:${symbol}`, interval),
    refetchInterval: 2000,
  })
  const desk = useQuery({
    queryKey: ['neo-desk'],
    enabled: !savedRange && exchange !== 'DELTA' && !toolkitOn,
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
    const asOf = replayRef.current
      ? replayRef.current.until - 19800
      : savedRange
        ? chartRangeBounds(savedRange.start, savedRange.end)!.end
        : selectedRange
          ? Math.min(Date.now() / 1000, chartRangeBounds(sessionDate, sessionEndDate)!.end)
          : Date.now() / 1000
    const first = shownBars.current[0]?.time ?? 0,
      last = shownBars.current.at(-1)?.time ?? 0
    nineAsOf.current = asOf
    const independent = enabledRef.current.some(id => id.startsWith('nine-')) && first && ['NSE_INDEX', 'BSE_INDEX'].includes(exchange)
      ? nineEngine.update(calculationBars.current, { seconds: replaySeconds(interval), asOf, indian }) : null
    s.nine.update(independent, enabledRef.current, first, last, mfiProxy.current.scope === nineScope ? mfiProxy.current.result : null, shownBars.current)
    setNineResult(independent)
    s.bbChikou.update(
      enabledRef.current.includes('bb-chikou') && first
        ? calculateBBChikou(calculationBars.current, { seconds: replaySeconds(interval), asOf })
        : null,
      first,
      last
    )
    const result =
      enabledRef.current.includes('neo-toolkit') && first
        ? engine.update(calculationBars.current, { seconds: replaySeconds(interval), asOf, indian })
        : null
    const references =
      result && toolkitSettings.references
        ? completedReferences(referenceHistory.data ?? [], 3600, asOf, indian)
        : []
    s.toolkit.update(result, references, first, last, {
      ...toolkitSettings,
      labelTop: focusMode ? 104 : 0,
    })
    if (result && toolkitSettings.events)
      for (const event of result.events) {
        if (!event.kind.startsWith('breakout-')) continue
        const candle = shownBars.current.find((bar) => bar.time === event.time)
        if (candle) {
          const color = event.kind === 'breakout-up' ? '#00e5a8' : '#ff4d8d'
          s.price.update(
            {
              ...candle,
              time: candle.time as UTCTimestamp,
              color,
              wickColor: color,
              borderColor: color,
            },
            true
          )
        }
      }
    setToolkitResult(result)
    setReferenceLevels((old) =>
      JSON.stringify(old) === JSON.stringify(references) ? old : references
    )
    const legacyOn = enabledRef.current.some(
      (id) => id === 'neo-donchian' || id === 'neo-structure' || id === 'rsi'
    )
    if (!legacyOn) {
      if (s.legacyActive) {
        for (const series of [s.upper, s.lower, s.ema]) {
          series.setData([])
          series.applyOptions({ visible: false })
        }
        if (s.rsi) {
          s.chart.removeSeries(s.rsi)
          s.rsi = null
        }
        for (const line of s.structure) s.price.removePriceLine(line)
        s.structure = []
        s.zones.setZones([])
        setGapZones([])
        s.legacyActive = false
      }
      return
    }
    s.legacyActive = true
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
    if (structure && !result && shownBars.current.length) {
      level(computed.support, 'Support', '#26a69a')
      level(computed.resistance, 'Resistance', '#ef5350')
    }
    if (
      !result &&
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
    const slots = focusMode
      ? Math.max(30, Math.min(110, Math.floor((host.current?.clientWidth || 800) / 10)))
      : Math.max(30, Math.floor((host.current?.clientWidth || 800) / 8))
    scene.current?.chart.timeScale().setVisibleLogicalRange({
      from: focusMode ? Math.max(-2, count - slots) : count - slots,
      to: count + (enabledRef.current.includes('neo-toolkit') ? (focusMode ? 12 : 18) : 8),
    })
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
      const dark = darkOverride ?? (mode === 'dark' || appMode === 'analyzer'),
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
          scaleMargins: { top: focusMode ? 0.2 : 0.13, bottom: focusMode ? 0.08 : 0.12 },
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
          visible: false,
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
        toolkit: new ToolkitLayer(chart, price, dark),
        bbChikou: new BBChikouLayer(chart, price),
        nine: new NineIndicatorLayer(price),
        legacyActive: false,
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
  }, [mode, appMode, symbol, exchange, interval, username, darkOverride])

  // biome-ignore lint/correctness/useExhaustiveDependencies: imperative chart and study changes must replay into the current scene
  useEffect(() => {
    const s = scene.current
    if (!s || (!history.data && !rangeHistory.data)) return
    const incoming = reconcileHistory(
      chartBars([
        ...(interval === '1m' && !selectedRange ? (warmupHistory.data ?? []) : []),
        ...(selectedRange ? (rangeHistory.data?.candles ?? []) : []),
        ...(history.data?.candles || []),
      ]),
      viewportSet.current ? liveBar.current : null
    )
    bars.current = incoming
    if (recentContext && !selectedRange && incoming.length) {
      const start = incoming[Math.max(0, incoming.length - 120)]
      setRecentStart(new Date((start.time + 19800) * 1000).toISOString().slice(0, 10))
    }
    publishLive()
    if (replayRef.current) return
    paintRef.current(!viewportSet.current)
    if (incoming.length) viewportSet.current = true
  }, [ready, history.data, rangeHistory.data, warmupHistory.data, selectedRange])
  // biome-ignore lint/correctness/useExhaustiveDependencies: imperative chart and study changes must replay into the current scene
  useEffect(() => {
    if (scene.current) drawRef.current(scene.current)
  }, [ready, enabled, profile, referenceHistory.data])
  // Repaint candle colors when optional breakout highlighting is switched off.
  useEffect(() => {
    if (scene.current) paintRef.current(false)
  }, [toolkitSettings])
  // biome-ignore lint/correctness/useExhaustiveDependencies: imperative chart and study changes must replay into the current scene
  useEffect(() => {
    const s = scene.current
    if (!s || !info.data || savedRange || replayRef.current || sessionEndDate !== today) return
    const lines = (Array.isArray(info.data.overlays) ? info.data.overlays : [])
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
  const tick = useMemo(
    () =>
      savedRange
        ? undefined
        : exchange === 'DELTA'
          ? delta.bar
            ? { ltp: delta.bar.close, timestamp: (delta.published ?? 0) * 1000 }
            : undefined
          : market.data.get(`${exchange}:${symbol}`)?.data,
    [savedRange, exchange, symbol, delta.bar, delta.published, market.data]
  )
  useEffect(() => {
    const s = scene.current
    if (!s || !tick?.ltp || !bars.current.length || usingSnapshot) return
    const previous = bars.current.at(-1),
      raw =
        exchange === 'DELTA'
          ? (delta.bar ?? null)
          : nextLiveBar(
              previous,
              Number(tick.ltp),
              tick.timestamp,
              interval,
              Date.now(),
              market.data.get(`${exchange}:${symbol}`)?.data
            )
    const next = raw ? { ...raw, volume: raw.volume ?? 0 } : null
    if (!next || (previous && next.time < previous.time)) return
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
  }, [
    tick,
    delta.bar,
    interval,
    sessionDate,
    sessionEndDate,
    rangeLoading,
    rangeError,
    usingSnapshot,
  ])
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
      className={`relative flex h-full ${focusMode ? 'min-h-0' : 'min-h-[420px]'} flex-col overflow-hidden bg-background ${focusMode ? '' : 'rounded-md border'}`}
    >
      {focusMode ? (
        <div className="pointer-events-none absolute left-4 top-3 z-10 max-w-[calc(100%_-_2rem)] sm:max-w-[calc(100%_-_360px)] space-y-1">
          <div className="flex flex-wrap items-baseline gap-2 text-xs">
            <strong className="text-sm font-semibold">{title || symbol}</strong>
            <span className="text-muted-foreground">
              {interval} · {exchange === 'DELTA' ? 'Delta' : exchange.replace('_INDEX', '')}
            </span>
            {usingSnapshot ? (
              <span className="text-amber-500">
                Saved candles · {history.isError ? 'broker delayed' : 'updating'}
              </span>
            ) : null}
            {tick?.ltp && (usingSnapshot || !last) ? (
              <span className="tabular-nums">Live {Number(tick.ltp).toFixed(2)}</span>
            ) : null}
            {replay ? (
              <span className="text-amber-500">REPLAY · {replayStamp(replay.until)}</span>
            ) : null}
          </div>
          <section
            aria-label="Candle prices"
            className="flex flex-wrap gap-x-2 text-[11px] tabular-nums text-muted-foreground"
          >
            {candle ? (
              <>
                <span>O {candle.open.toFixed(2)}</span>
                <span>H {candle.high.toFixed(2)}</span>
                <span>L {candle.low.toFixed(2)}</span>
                <span className={candle.close >= candle.open ? 'text-emerald-500' : 'text-red-400'}>
                  C {candle.close.toFixed(2)}
                </span>
              </>
            ) : (
              <span>
                {history.isPending || rangeLoading ? 'Loading candles…' : 'No candles available'}
              </span>
            )}
          </section>
          {toolkitOn ? (
            <section
              aria-label="Active chart studies"
              className="flex flex-wrap gap-x-3 text-[11px] tabular-nums"
            >
              <span className="text-blue-500">
                EMA 9{' '}
                <b className="font-medium">{toolkitResult?.current.ema9?.toFixed(2) ?? '—'}</b>
              </span>
              <span className="text-amber-500">
                EMA 15{' '}
                <b className="font-medium">{toolkitResult?.current.emaSlow?.toFixed(2) ?? '—'}</b>
              </span>
            </section>
          ) : null}
          {enabled.includes('bb-chikou') ? (
            <section aria-label="BB + Chikou study" className="text-[11px] text-violet-400">
              BB + Chikou · 20 / 2 / 26 · closed candles · 1R references
            </section>
          ) : null}
        </div>
      ) : (
        <div className="shrink-0 border-b px-3 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <strong className="text-sm">{title || symbol}</strong>
              <span className="ml-2 text-xs text-muted-foreground">
                {exchange} · {interval} ·{' '}
                {replay
                  ? `REPLAY · ${replayStamp(replay.until)}`
                  : exchange === 'DELTA'
                    ? 'Delta public feed'
                    : 'Kotak Neo'}
              </span>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground">
                {savedRange ? 'Saved close' : exchange === 'DELTA' ? 'Delta USD' : 'Broker LTP'}
              </span>
              <strong className="tabular-nums">
                {savedRange
                  ? last
                    ? `${exchange === 'DELTA' ? '$' : '₹'}${last.close.toFixed(2)}`
                    : 'No saved candles'
                  : tick?.ltp
                    ? `${exchange === 'DELTA' ? '$' : '₹'}${Number(tick.ltp).toFixed(2)}`
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
            {enabled.includes('bb-chikou') ? (
              <span className="text-violet-400">
                BB + Chikou · 20 / 2 / 26 · closed candles · 1R
              </span>
            ) : null}
            {enabled.includes('neo-toolkit') ? (
              <>
                <span className="text-blue-500">
                  EMA 9 · {toolkitResult?.current.ema9?.toFixed(2) ?? '—'}
                </span>
                <span className="text-amber-500">
                  EMA {toolkitSettings.slow} · {toolkitResult?.current.emaSlow?.toFixed(2) ?? '—'}
                </span>
                <span>Green: support · Red: resistance</span>
              </>
            ) : null}
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
            {!toolkitOn &&
            symbol === 'NIFTY' &&
            profile.startsWith('orb') &&
            ['1m', '3m', '5m', '15m'].includes(interval) ? (
              <span>Opening range 09:15–09:30</span>
            ) : null}
          </section>
        </div>
      )}
      {selectedRange && rangeHistory.data?.emptyDates.length ? (
        <output
          aria-label="Date range coverage"
          className="border-b px-3 py-1 text-xs text-muted-foreground"
        >
          No candles on {rangeHistory.data.emptyDates.join(', ')}.
          {exchange !== 'DELTA' ? ' Weekends are skipped.' : ''}
        </output>
      ) : null}
      {nineOn ? (
        <NineIndicatorPanel result={nineResult} enabled={enabled} symbol={symbol} exchange={exchange} interval={interval}
          seconds={replaySeconds(interval)} asOf={nineAsOf.current} replay={!!replay || !!savedRange || !!selectedRange}
          ready={!usingSnapshot && !!history.data && !history.isError} reference={optionReference} onMfiProxy={onMfiProxy} />
      ) : null}
      {toolkitOn ? (
        <div
          className={
            focusMode
              ? 'absolute bottom-20 left-3 z-20 w-[255px] max-w-[calc(100%_-_2rem)] sm:bottom-auto sm:left-auto sm:right-[82px] sm:top-3'
              : ''
          }
        >
          <ToolkitPanel
            compact={focusMode}
            historyReady={!usingSnapshot && !!history.data && !history.isError}
            signalMarket={
              exchange === 'DELTA'
                ? 'perpetual'
                : ['NSE_INDEX', 'BSE_INDEX'].includes(exchange)
                  ? 'index'
                  : 'option'
            }
            result={toolkitResult}
            references={referenceLevels}
            settings={toolkitSettings}
            onSettings={setToolkitSettings}
            reference={optionReference}
            replay={!!replay || !!savedRange || !!selectedRange}
            referenceError={referenceHistory.isError}
            referenceLoading={referenceHistory.isPending || referenceHistory.isFetching}
            showIV={exchange !== 'DELTA'}
            feedFresh={
              exchange === 'DELTA'
                ? delta.connected && age != null && age <= 15
                : market.isConnected && age != null && age <= 15
            }
          />
        </div>
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
      {!savedRange && (
        <details
          open={focusMode ? undefined : true}
          className={focusMode ? 'shrink-0 border-b text-xs' : 'contents'}
        >
          {focusMode ? (
            <summary className="cursor-pointer px-3 py-1 text-muted-foreground focus-visible:outline focus-visible:outline-ring">
              History & replay
            </summary>
          ) : null}
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
                !recentContext && range.start === istSessionDate() && range.end === range.start
                  ? null
                  : range
              )
            }
            loading={rangeLoading}
            unavailable={rangeError}
          />
        </details>
      )}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t px-3 py-1 text-[11px] text-muted-foreground">
        <span>
          {savedRange
            ? `SQL saved history · ${savedRange.start} → ${savedRange.end}`
            : (exchange === 'DELTA' ? delta.connected : market.isConnected)
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
