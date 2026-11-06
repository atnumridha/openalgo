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
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type AutoscaleInfo,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { optionStructure } from './optionStructure'
import { LEVEL_COLORS } from './PriceLevels'
import { layoutChartLabels } from './chartLabels'
import { chartWindow } from './chartViewport'
import { chartTickEpoch } from './chartSession'
import { useChartSession } from './useChartSession'
import { scalpingApi } from '@/api/scalping'
import { useMarketData } from '@/hooks/useMarketData'
import { priceDecimals } from '@/lib/scalpingPrice'
import { chartIndicators, type ChartIndicatorValues } from './chartIndicators'
import { grossLabel, type ChartPosition } from './chartPosition'
import { useThemeStore } from '@/stores/themeStore'
import { ChartReadouts } from './ChartReadouts'
import { useAuthStore } from '@/stores/authStore'
import { candleKey, publishChartCandles } from './chartCandleStore'
import { replayBars, replayStamp, type ChartReplay } from './chartReplay'
import { fairValueGaps, nearbyFairValueGaps, type FairValueGap } from './fairValueGaps'
import { FairValueGapLegend } from './FairValueGapLegend'
import { FairValueGapOverlay } from './FairValueGapOverlay'

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
  { key: 'rsi14', title: 'RSI14', color: '#a78bfa', pane: 1 },
] as const
type IndicatorKey = (typeof INDICATORS)[number]['key']
const visibleIndicator = (key: IndicatorKey, interval: string) =>
  key === 'rsi14' || (interval === '1m' ? key === 'ema9' : key !== 'ema9')

interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

function fmtPrice(n: number, decimals = 2): string {
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

export const KotakAssistantChart = memo(function KotakAssistantChart({
  symbol,
  exchange,
  interval,
  title,
  position,
  levels,
  markers,
  replay,
  showFvg = true,
  externalSource,
  externalQuote,
  protectionLabel = 'saved server protection',
}: {
  externalSource?: { id: string; getHistory: typeof scalpingApi.getHistory }
  externalQuote?: { ltp?: number; time: number; source?: string; volume?: number }
  symbol: string
  exchange: string
  interval: string
  title?: string
  position?: ChartPosition
  levels?: Array<{ price: number; title: string; color: string }>
  markers?: Array<{ time: number; action: string; price: number; label?: string; side?: 'above'|'below'; color?: string }>
  protectionLabel?: string
  replay?: ChartReplay
  showFvg?: boolean
}) {
  const { mode, appMode } = useThemeStore()
  const username = useAuthStore((s) => s.user?.username)
  const candleScope = useRef('')
  candleScope.current = candleKey(externalSource ? `${username || 'anonymous'}:${externalSource.id}` : username, appMode, symbol, exchange, interval)
  const isDark = appMode !== 'live' || mode === 'dark'

  const containerRef = useRef<HTMLDivElement | null>(null)
  const legendRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const indicatorSeriesRef = useRef<Partial<Record<IndicatorKey, ISeriesApi<'Line'>>>>({})
  const indicatorValuesRef = useRef<ChartIndicatorValues[]>([])
  const renderIndicatorsRef = useRef<(replace: boolean) => void>(() => {})
  const renderLegendRef = useRef<(time?: number) => void>(() => {})
  const hoveredTimeRef = useRef<number | undefined>(undefined)
  const colorsRef = useRef({ title: '#d6dde6', muted: '#8a97a5' })
  const replayRef = useRef(replay)
  replayRef.current = replay
  const isReplaying = !!replay
  const displayPosition = replay ? undefined : position
  const positionRef = useRef(displayPosition)
  positionRef.current = displayPosition
  const levelsRef = useRef(levels)

  // Authoritative model: bucket time -> candle. Completed bars are reconciled
  // from broker history; the current bucket is built live from ticks.
  const candlesRef = useRef<Map<number, Candle>>(new Map())
  const sortedRef = useRef<Candle[]>([])
  const displayedRef = useRef<Candle[]>([])
  const drawModelRef = useRef<(preserve: boolean) => void>(() => {})
  const idxByTimeRef = useRef<Map<number, number>>(new Map())
  const currentBucketRef = useRef<number | null>(null)
  const tradingDateRef = useRef<string | null>(null)
  const intervalSecRef = useRef<number>(INTERVAL_SEC[interval] ?? 60)
  const intervalRef = useRef<string>(interval)
  const barStartVolRef = useRef<number | null>(null)
  const readyRef = useRef(false)

  const optionSide = /CE$/.test(symbol) ? 'CE' : /PE$/.test(symbol) ? 'PE' : ''
  const optionChart = !!optionSide && ['NFO', 'BFO'].includes(exchange)
  const structureScope = `${symbol}:${exchange}:${interval}`
  const [readout, setReadout] = useState<{
    scope: string
    rsi: number | null
    hovered: boolean
    barTime: number | null
  }>({ scope: '', rsi: null, hovered: false, barTime: null })
  const visibleReadout = readout.scope === structureScope ? readout : null
  const [structure, setStructure] = useState<{
    scope: string
    lines: Array<{ price: number; title: string; color: string }>
  }>({ scope: '', lines: [] })
  const structureLines = useMemo(
    () => (structure.scope === structureScope ? structure.lines : []),
    [structure, structureScope]
  )
  const allLevels = useMemo(
    () => [...(isReplaying ? [] : levels || []), ...structureLines],
    [levels, structureLines, isReplaying]
  )
  levelsRef.current = allLevels
  const updateStructure = () => {
    if (!optionChart && !replayRef.current) {
      setStructure((previous) =>
        previous.lines.length ? { scope: structureScope, lines: [] } : previous
      )
      return
    }
    const reference = displayedRef.current.at(-1)?.close || 0
    const found = optionStructure(
      displayedRef.current,
      intervalSecRef.current,
      replayRef.current ? replayRef.current.until - IST_OFFSET : Date.now() / 1000,
      reference
    )
    const lines = [
      ...(found.support == null
        ? []
        : [
            {
              price: found.support,
              title: `${optionSide || symbol} SUPPORT`,
              color: LEVEL_COLORS.support,
            },
          ]),
      ...(found.resistance == null
        ? []
        : [
            {
              price: found.resistance,
              title: `${optionSide || symbol} RESISTANCE`,
              color: LEVEL_COLORS.resistance,
            },
          ]),
    ]
    setStructure((previous) =>
      previous.scope === structureScope && JSON.stringify(previous.lines) === JSON.stringify(lines)
        ? previous
        : { scope: structureScope, lines }
    )
  }
  const updateStructureRef = useRef(updateStructure)
  updateStructureRef.current = updateStructure
  const [gapState, setGapState] = useState<{ scope: string; gaps: FairValueGap[] }>({
    scope: '',
    gaps: [],
  })
  const updateGaps = () => {
    const gaps = showFvg
      ? nearbyFairValueGaps(
          fairValueGaps(
            displayedRef.current,
            intervalSecRef.current,
            replayRef.current ? replayRef.current.until - IST_OFFSET : Date.now() / 1000
          ),
          displayedRef.current.at(-1)?.close || 0
        )
      : []
    setGapState((previous) =>
      previous.scope === structureScope && JSON.stringify(previous.gaps) === JSON.stringify(gaps)
        ? previous
        : { scope: structureScope, gaps }
    )
  }
  const updateGapsRef = useRef(updateGaps)
  updateGapsRef.current = updateGaps
  const positionStatus = displayPosition?.status
  const entry = displayPosition?.entry
  const quantity = displayPosition?.quantity
  const sl = displayPosition?.sl
  const target = displayPosition?.target
  const textLevels = useMemo(() => {
    const filled = positionStatus === 'open' && !!entry && !!quantity
    const values = filled
      ? [
          { price: entry!, title: 'ENTRY (FILLED)', color: '#0284c7' },
          { price: sl || 0, title: 'STOP LOSS', color: '#dc2626' },
          { price: target || 0, title: 'PROFIT TARGET', color: '#16a34a' },
          ...structureLines,
        ]
      : allLevels.map((l) => ({
          ...l,
          title: /support|resistance/i.test(l.title)
            ? l.title.toUpperCase()
            : l.title.toUpperCase(),
        }))
    return values.filter((l) => Number.isFinite(l.price) && l.price > 0)
  }, [positionStatus, entry, quantity, sl, target, allLevels, structureLines])
  const [labelAxisWidth, setLabelAxisWidth] = useState(72)
  const [labelPositions, setLabelPositions] = useState<ReturnType<typeof layoutChartLabels>>([])
  useEffect(() => {
    const update = () => {
      const series = candleRef.current,
        container = containerRef.current
      const positions =
        series && container
          ? layoutChartLabels(
              textLevels.flatMap((l) => {
                const y = series.priceToCoordinate(l.price)
                return y == null ? [] : [{ ...l, y: Number(y) }]
              }),
              Math.max(0, container.clientHeight - 28)
            )
          : []
      const width = Math.ceil(chartRef.current?.priceScale('right').width?.() || 72)
      setLabelAxisWidth(previous => previous === width ? previous : width)
      setLabelPositions((previous) =>
        JSON.stringify(previous) === JSON.stringify(positions) ? previous : positions
      )
    }
    update()
    if (!textLevels.length) return
    const timer = setInterval(update, 200)
    return () => clearInterval(timer)
  }, [textLevels, symbol, exchange, interval])
  const [status, setStatus] = useState('')
  const [following, setFollowing] = useState(true)
  const followRef = useRef(true)
  const movingRef = useRef(false)
  const [lastTick, setLastTick] = useState(0)
  const [now, setNow] = useState(Date.now() / 1000)
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(timer)
  }, [])
  const liveBucket = Math.floor((now + IST_OFFSET) / (INTERVAL_SEC[interval] || 60))
  useEffect(() => {
    if (isReplaying) return
    updateStructureRef.current()
    updateGapsRef.current()
  }, [liveBucket, isReplaying])
  const resetView = () => {
    const chart = chartRef.current
    if (!chart) return
    followRef.current = true
    setFollowing(true)
    chart.priceScale('right').applyOptions({ autoScale: true })
    chart
      .timeScale()
      .setVisibleLogicalRange(
        chartWindow(
          displayedRef.current.length,
          containerRef.current?.clientWidth || 400,
          null,
          true
        )
      )
  }

  const enabled = !!(symbol && exchange)
  const session = useChartSession(exchange, now, enabled)
  const { data } = useMarketData({
    symbols: enabled ? [{ symbol, exchange }] : [],
    mode: 'Quote',
    enabled: enabled && !externalSource,
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
      rightPriceScale: {
        borderColor: isDark ? '#1b2330' : '#e2e8f0',
        alignLabels: true,
        minimumWidth: 64,
      },
      timeScale: {
        borderColor: isDark ? '#1b2330' : '#e2e8f0',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 3,
        shiftVisibleRangeOnNewBar: true,
      },
      // Keep page scrolling from panning/zooming the chart into old candles.
      handleScroll: {
        mouseWheel: false,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        mouseWheel: true,
        pinch: true,
        axisPressedMouseMove: true,
        axisDoubleClickReset: true,
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
    })
    const vol = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '',
      lastValueVisible: false,
      priceLineVisible: false,
    })
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
    candle.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.23 } })

    for (const indicator of INDICATORS) {
      const line = chart.addSeries(
        LineSeries,
        {
          title: '',
          color: indicator.color,
          lineWidth: 2,
          visible: visibleIndicator(indicator.key, intervalRef.current),
          priceLineVisible: false,
          lastValueVisible: indicator.key === 'rsi14',
          priceFormat: {
            type: 'price',
            precision: indicator.key === 'rsi14' ? 2 : decimals,
            minMove: indicator.key === 'rsi14' ? 0.01 : 10 ** -decimals,
          },
          autoscaleInfoProvider:
            indicator.key === 'rsi14'
              ? () => ({ priceRange: { minValue: 0, maxValue: 100 } })
              : undefined,
        },
        indicator.pane
      )
      if (indicator.key === 'rsi14') {
        for (const price of [30, 70])
          line.createPriceLine({
            price,
            color: '#718096',
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: false,
            title: '',
          })
        line.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.08 } })
      }
      indicatorSeriesRef.current[indicator.key] = line
    }

    chart.panes()[1]?.setHeight(140)

    renderIndicatorsRef.current = (replace) => {
      const values = chartIndicators(displayedRef.current)
      indicatorValuesRef.current = values
      for (const indicator of INDICATORS) {
        const series = indicatorSeriesRef.current[indicator.key]
        if (!series) continue
        if (replace) {
          series.setData(
            values.flatMap((row) =>
              row[indicator.key] == null
                ? []
                : [
                    {
                      time: row.time as UTCTimestamp,
                      value: row[indicator.key]!,
                    },
                  ]
            )
          )
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

    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (!range || movingRef.current || !displayedRef.current.length) return
      const nearLatest = range.to >= displayedRef.current.length - 2
      followRef.current = nearLatest
      setFollowing(nearLatest)
    })

    // OHLC legend overlay: hovered bar, or the last bar when not hovering.
    const renderLegend = (time?: number) => {
      const el = legendRef.current
      const arr = displayedRef.current
      if (!el) return
      let idx = arr.length - 1
      if (time != null) {
        const i = idxByTimeRef.current.get(time)
        if (i != null) idx = i
      }
      const next = {
        scope: `${symbol}:${exchange}:${intervalRef.current}`,
        rsi: indicatorValuesRef.current[idx]?.rsi14 ?? null,
        hovered: time != null && idxByTimeRef.current.has(time),
        barTime: arr.at(-1)?.time ?? null,
      }
      setReadout((previous) =>
        previous.scope === next.scope &&
        previous.rsi === next.rsi &&
        previous.hovered === next.hovered &&
        previous.barTime === next.barTime
          ? previous
          : next
      )
      if (!arr.length) {
        el.innerHTML = ''
        return
      }
      const bar = arr[idx]
      const { title: titleColor, muted } = colorsRef.current
      const indicators = indicatorValuesRef.current[idx]
      const indicatorLegend = INDICATORS.filter(({ key }) =>
        key !== 'rsi14' && visibleIndicator(key, intervalRef.current)
      )
        .map(
          ({ key, title, color }) =>
            `<span style="color:${color};display:inline-block;margin-right:12px">${title} ${indicators?.[key] == null ? '—' : fmtPrice(indicators[key], decimals)}</span>`
        )
        .join('')
      const stamp = new Date(bar.time * 1000).toLocaleString('en-GB', {
        timeZone: 'UTC',
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
      el.innerHTML =
        `<div style="color:${muted}">${stamp} IST · ${intervalRef.current}</div>` +
        `<div style="color:${titleColor};display:flex;flex-wrap:wrap;gap:3px 9px;margin-top:3px">` +
        [
          ['O', bar.open],
          ['H', bar.high],
          ['L', bar.low],
          ['C', bar.close],
        ]
          .map(
            ([label, value]) => `<span>${label} <b>${fmtPrice(Number(value), decimals)}</b></span>`
          )
          .join('') +
        `</div>` +
        `<div style="margin-top:3px">${indicatorLegend}<span style="color:${muted}">${bar.volume > 0 ? 'Vol ' + fmtVol(bar.volume) : 'Volume not provided'}</span></div>`
    }
    renderLegendRef.current = () => renderLegend(hoveredTimeRef.current)
    chart.subscribeCrosshairMove((param) => {
      hoveredTimeRef.current = typeof param.time === 'number' ? param.time : undefined
      renderLegend(hoveredTimeRef.current)
    })

    return () => {
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      volRef.current = null
      indicatorSeriesRef.current = {}
      indicatorValuesRef.current = []
      renderIndicatorsRef.current = () => {}
      renderLegendRef.current = () => {}
      hoveredTimeRef.current = undefined
    }
  }, [symbol, exchange, enabled])

  // These are display lines from actual fills and acknowledged server protection.
  // They do not place, modify or cancel exchange orders.
  useEffect(() => {
    const position = { status: positionStatus, entry, quantity, sl, target }
    const candle = candleRef.current
    if (!candle) return
    candle.applyOptions({
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const info = original()
        const current = positionRef.current
        if (!info?.priceRange) return info
        const values =
          current?.status === 'open'
            ? [
                current.entry,
                current.sl,
                current.target,
                ...(levelsRef.current || []).map((l) => l.price),
              ]
            : (levelsRef.current || []).map((l) => l.price)
        const prices = values.filter((p): p is number => p != null && Number.isFinite(p) && p > 0)
        return {
          ...info,
          priceRange: {
            minValue: Math.min(info.priceRange.minValue, ...prices),
            maxValue: Math.max(info.priceRange.maxValue, ...prices),
          },
        }
      },
    })
    if (position?.status !== 'open' || !position.entry || !position.quantity) return
    const lines = [
      {
        price: position.entry,
        title: 'Entry (filled)',
        color: '#0284c7',
      },
      ...(position.sl
        ? [
            {
              price: position.sl,
              title: 'Stop loss',
              color: '#dc2626',
            },
          ]
        : []),
      ...(position.target
        ? [
            {
              price: position.target,
              title: 'Target',
              color: '#16a34a',
            },
          ]
        : []),
    ].map((line) =>
      candle.createPriceLine({
        ...line,
        title: '',
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
      })
    )
    return () => {
      if (candleRef.current === candle) for (const line of lines) candle.removePriceLine(line)
    }
  }, [symbol, exchange, interval, positionStatus, entry, quantity, sl, target])

  useEffect(() => {
    const candle = candleRef.current
    if (!candle || !allLevels.length) return
    const lines = allLevels
      .filter((l) => Number.isFinite(l.price) && l.price > 0)
      .slice(-12)
      .map((l) =>
        candle.createPriceLine({
          ...l,
          title: '',
          lineWidth: 2,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
        })
      )
    return () => {
      if (candleRef.current === candle) for (const line of lines) candle.removePriceLine(line)
    }
  }, [symbol, exchange, interval, allLevels])

  useEffect(() => {
    const candle = candleRef.current
    if (!candle || !markers) return
    const seconds = INTERVAL_SEC[interval] || 60
    const plugin = createSeriesMarkers(
      candle,
      markers
        .filter(
          (m) =>
            Number.isFinite(m.time) &&
            (!replay || (Math.floor(m.time / seconds) + 1) * seconds + IST_OFFSET <= replay.until)
        )
        .map((m) => ({
          time: (Math.floor(m.time / seconds) * seconds + IST_OFFSET) as UTCTimestamp,
          position: m.side === 'below' || (!m.side && m.action === 'BUY') ? ('belowBar' as const) : ('aboveBar' as const),
          color: m.color || (m.action === 'BUY' ? UP : DOWN),
          shape: m.side === 'below' || (!m.side && m.action === 'BUY') ? ('arrowUp' as const) : ('arrowDown' as const),
          text: m.label || `${m.action === 'SELL' ? 'EXIT' : 'BUY'} fill ${fmtPrice(m.price)}`,
        }))
        .sort((a, b) => Number(a.time) - Number(b.time))
    )
    return () => plugin.detach()
  }, [symbol, exchange, interval, markers, replay?.until])

  // This is the only full display draw. Raw live history/cache remain separate.
  drawModelRef.current = (preserveRange) => {
    const chart = chartRef.current,
      candle = candleRef.current,
      vol = volRef.current
    if (!chart || !candle || !vol) return
    const activeReplay = replayRef.current
    const arr = activeReplay
      ? replayBars(activeReplay.bars, activeReplay.seconds, activeReplay.until)
      : sortedRef.current
    displayedRef.current = arr
    idxByTimeRef.current = new Map(arr.map((bar, i) => [bar.time, i]))
    const ts = chart.timeScale()
    const range = preserveRange ? ts.getVisibleLogicalRange() : null
    movingRef.current = true
    candle.setData(
      arr.map((bar) => ({
        time: bar.time as UTCTimestamp,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }))
    )
    vol.setData(
      arr.map((bar) => ({
        time: bar.time as UTCTimestamp,
        value: bar.volume,
        color: bar.close >= bar.open ? VOL_UP : VOL_DOWN,
      }))
    )
    renderIndicatorsRef.current(true)
    if (arr.length)
      ts.setVisibleLogicalRange(
        chartWindow(arr.length, containerRef.current?.clientWidth || 400, range, followRef.current)
      )
    movingRef.current = false
    updateStructure()
    updateGapsRef.current()
    renderLegendRef.current()
  }
  const previousReplayRef = useRef(false)
  useEffect(() => {
    const wasReplaying = previousReplayRef.current
    previousReplayRef.current = !!replay
    hoveredTimeRef.current = undefined
    if (!replay) {
      followRef.current = true
      setFollowing(true)
    }
    drawModelRef.current(wasReplaying && !!replay)
  }, [replay])
  useEffect(() => {
    updateGapsRef.current()
  }, [showFvg])

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
    displayedRef.current = []
    publishChartCandles(candleScope.current, [])
    idxByTimeRef.current = new Map()
    currentBucketRef.current = null
    barStartVolRef.current = null
    intervalSecRef.current = INTERVAL_SEC[interval] ?? 60
    intervalRef.current = interval
    hoveredTimeRef.current = undefined
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
    setLastTick(0)
    followRef.current = true
    setFollowing(true)
    setStructure({ scope: structureScope, lines: [] })
    setStatus('Loading candles…')

    const applyModel = (preserveRange: boolean) => {
      const arr = Array.from(candlesRef.current.values()).sort((a, b) => a.time - b.time)
      sortedRef.current = arr
      publishChartCandles(candleScope.current, arr)
      if (!replayRef.current) drawModelRef.current(preserveRange)
    }

    const reconcile = async () => {
      if (disposed || inflight) return
      inflight = true
      try {
        const d = await (externalSource?.getHistory || scalpingApi.getHistory)(
          symbol,
          exchange,
          interval,
          tradingDateRef.current || undefined
        )
        if (disposed || d.status !== 'success') return
        const fetched = d.candles || []
        if (!fetched.length) return
        if (!readyRef.current || !sortedRef.current.length) {
          candlesRef.current = new Map(fetched.map((k) => [k.time, { ...k }]))
          tradingDateRef.current = d.date || null
          applyModel(false)
          currentBucketRef.current = sortedRef.current.at(-1)?.time ?? null
          readyRef.current = true
          setStatus('')
          return
        }
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

    const historyLoader = externalSource?.getHistory || scalpingApi.getHistory
    historyLoader(symbol, exchange, interval)
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
  }, [symbol, exchange, interval, enabled, username, appMode, externalSource])

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
  const tickData = externalSource
    ? externalQuote
      ? { data: { ltp: externalQuote.ltp, timestamp: String(externalQuote.time * 1000), volume: externalQuote.volume }, updateSource: externalQuote.source === 'Live feed' ? 'websocket' as const : 'rest' as const }
      : undefined
    : data.get(`${exchange}:${symbol}`)
  const tick = tickData?.data
  const tickSource = tickData?.updateSource
  const ltp = tick?.ltp
  const ts = tick?.timestamp
  const tickVol = typeof tick?.volume === 'number' ? tick.volume : null
  useEffect(() => {
    const candle = candleRef.current
    const vol = volRef.current
    if (!candle || !vol || !readyRef.current || ltp == null || !Number.isFinite(ltp)) return

    const epochUtc = chartTickEpoch(session.window, ts, Date.now() / 1000, tickSource)
    if (epochUtc == null) return
    setLastTick(epochUtc)
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
    } else if (arr.length) {
      arr[arr.length - 1] = bar
    }

    publishChartCandles(candleScope.current, arr)
    if (replayRef.current) return
    displayedRef.current = arr
    if (isNew) idxByTimeRef.current.set(bucket, arr.length - 1)

    const color = bar.close >= bar.open ? VOL_UP : VOL_DOWN
    candle.update({
      time: bar.time as UTCTimestamp,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    })
    vol.update({ time: bar.time as UTCTimestamp, value: bar.volume, color })
    renderIndicatorsRef.current(false)
    updateStructure()
    updateGapsRef.current()
    if (followRef.current) chartRef.current?.timeScale().scrollToPosition(3, false)
    renderLegendRef.current()
    // Clear the live-only "waiting for ticks" placeholder once a bar exists.
    setStatus((s) => (s ? '' : s))
  }, [ltp, ts, tickVol, tickSource, session.window])

  if (!enabled) {
    return (
      <div className="flex h-full w-full items-center justify-center rounded-lg border bg-card text-xs text-muted-foreground">
        {title ? `${title} — not selected` : 'No instrument'}
      </div>
    )
  }

  return (
    <div
      className="relative flex h-full w-full flex-col overflow-hidden bg-card"
      role="region"
      aria-label={`${symbol} ${interval} indicator chart`}
    >
      <h4 className="shrink-0 border-b px-3 py-2 text-sm font-semibold">{title || symbol}</h4>
      <div className="shrink-0 flex items-center justify-between gap-2 border-b px-2.5 py-1 text-xs text-muted-foreground">
        <span>
          {replay
            ? `REPLAY · ${replayStamp(replay.until)}`
            : session.state === 'unavailable'
              ? 'Calendar unavailable · historical candles'
              : session.state === 'checking'
                ? 'Checking exchange calendar · historical candles'
                : session.state === 'closed'
                  ? 'Market closed · historical candles'
                  : lastTick > 0 && now - lastTick <= 10 && tickSource === 'websocket'
                    ? 'Fresh tick · forming candle'
                    : 'Historical candles · no fresh tick'}
          {following ? '' : ' · browsing'}
        </span>
        {showFvg && (
          <FairValueGapLegend gaps={gapState.scope === structureScope ? gapState.gaps : []} />
        )}
        <button
          type="button"
          onClick={resetView}
          className="shrink-0 rounded border px-2 py-1 text-foreground hover:bg-muted"
          aria-label="Reset chart to latest candles"
        >
          Latest
        </button>
      </div>
      <ChartReadouts
        rsi={visibleReadout?.rsi ?? null}
        hovered={visibleReadout?.hovered ?? false}
        barTime={visibleReadout?.barTime ?? null}
        interval={interval}
        now={now}
        replay={!!replay}
      />
      {position && !replay && (
        <div
          className="shrink-0 border-b px-2.5 py-1 text-xs"
          aria-label="Actual position and protection"
        >
          {position.status === 'unavailable' ? (
            'Position unconfirmed — no verified position data returned.'
          ) : position.status === 'flat' ? (
            'No open position for this contract/product.'
          ) : (
            <>
              <span className="font-medium">
                {position.quantity! > 0 ? 'LONG' : 'SHORT'} {Math.abs(position.quantity!)} · Entry{' '}
                {fmtPrice(position.entry!)} · P&L before fees:{' '}
                {grossLabel(position.gross, position.currency)}
              </span>
              <div className="text-muted-foreground">
                {position.protectionAvailable
                  ? `Stop loss ${position.sl == null ? 'not set' : fmtPrice(position.sl)} · Profit target ${position.target == null ? 'not set' : fmtPrice(position.target)} · ${protectionLabel}`
                  : `Stop loss unconfirmed · Profit target ${position.target == null ? 'not set' : fmtPrice(position.target)}`}
              </div>
            </>
          )}
        </div>
      )}
      <div
        ref={legendRef}
        className="pointer-events-none min-h-[64px] shrink-0 px-2.5 py-1 font-mono text-[11px] leading-tight"
      />
      {optionChart && (
        <p className="shrink-0 border-b px-2.5 py-1 text-[11px] text-muted-foreground">
          {optionSide} premium support/resistance ·{' '}
          {structureLines.length ? `confirmed ${interval} swings` : 'waiting for confirmed swings'}
        </p>
      )}
      <div className="relative min-h-0 flex-1">
        <div ref={containerRef} className="relative z-0 h-full w-full" />
        <FairValueGapOverlay
          chartRef={chartRef}
          candleRef={candleRef}
          containerRef={containerRef}
          gaps={showFvg && gapState.scope === structureScope ? gapState.gaps : []}
          isDark={isDark}
        />
        <div
          className="pointer-events-none absolute inset-0 z-10 overflow-hidden"
          aria-label="Visible chart line labels"
        >
          <svg className="absolute inset-0 h-full w-full" aria-hidden="true">
            {labelPositions.map((l) => (
              <path
                key={`${l.title}:${l.price}`}
                d={`M ${Math.max(0, (containerRef.current?.clientWidth || 0) - labelAxisWidth)} ${l.y} L ${Math.max(0, (containerRef.current?.clientWidth || 0) - labelAxisWidth - 6)} ${l.top + 11}`}
                stroke={l.color}
                strokeWidth="1"
                fill="none"
              />
            ))}
          </svg>
          {labelPositions.map((l) => (
            <span
              key={`${l.title}:${l.price}`}
              className="absolute flex h-[22px] max-w-[55%] items-center truncate rounded border px-1.5 text-[10px] font-medium"
              aria-label={`${l.title} · ${fmtPrice(l.price, priceDecimals(exchange))}`}
              style={{
                top: l.top,
                right: labelAxisWidth + 6,
                borderColor: l.color,
                backgroundColor: isDark ? '#111827' : '#ffffff',
                color: isDark ? '#f9fafb' : '#111827',
              }}
            >
              {l.title}
            </span>
          ))}
        </div>
      </div>
      {status && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
          {status}
        </div>
      )}
    </div>
  )
})
