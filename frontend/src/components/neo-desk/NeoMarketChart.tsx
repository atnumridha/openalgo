import { strategy51VisibleStudies } from '../strategy51-guide/visibility'
import { Strategy51Engine } from '../strategy51-guide/engine'
import { Strategy51Layer } from '../strategy51-guide/Strategy51Layer'
import { Strategy51Guide } from '../strategy51-guide/Strategy51Guide'
import { normalizeStrategy51Settings,readStrategy51Preferences,saveStrategy51Preferences } from '../strategy51-guide/preferences'
import { useStrategy51Data,deriveOptionEvidence } from '../strategy51-guide/useStrategy51Data'
import type { Strategy51Result } from '../strategy51-guide/types'
import { BookPatternEngine, type BookContext, type BookGuideResult } from '../book-pattern-guide/engine'
import { BookPatternLayer } from '../book-pattern-guide/BookPatternLayer'
import { BookPatternGuide } from '../book-pattern-guide/BookPatternGuide'
import { bookChartBars, bookChartContext, validatedBookInstrument } from '../book-pattern-guide/adapter'
import { bookInstrumentForScope, normalizeBookPreferences, readBookPreferences, saveBookPreferences } from '../book-pattern-guide/preferences'
import { protectChartHistoryRefresh } from './chartHistoryRefresh'
import { VideoStrategyGuide } from './VideoStrategyGuide'
import { LivePatternGuide } from './LivePatternGuide'
import { videoStrategyGuide } from '../chart-toolkit/videoStrategyGuide.js'
import { VideoStrategyLayer } from '../chart-toolkit/VideoStrategyLayer'
import type { VideoStrategyId } from '../chart-toolkit/videoStrategyTypes'
import { TradeGuide } from './TradeGuide'
import type { GuideBrokerContext, GuidePlan } from './tradeGuidance'
import { calculateEntryPlan } from './chartTradePlan'
import {
  CombinedChartPanel,
  type CombinedChartLevels,
} from '../combined-terminal/CombinedChartPanel'
import type { DeltaChartState } from '@/api/deltaChart'
import { DeltaTradePanel } from './DeltaTradePanel'
import { useDeltaScalpRisk } from './useDeltaScalpRisk'
import { DELTA_SCALP_STRATEGY } from './deltaScalpRisk'
import type { DeltaRiskContext } from './deltaRisk'
import { DeltaOrderLayer, type DeltaOrderEditProposal } from '../chart-toolkit/DeltaOrderLayer'
import { EmaLiveLayer } from '../chart-toolkit/EmaLiveLayer'
import { EmaCrossMarks } from '../chart-toolkit/EmaCrossMarks'
import { useServerEmaTrend } from '../chart-toolkit/useServerEmaTrend'
import { fibonacciPivots } from '../chart-toolkit/emaFibonacci'
import { higherTimeframeLevels } from '../chart-toolkit/higherTimeframeLevels'
import { supportResistanceLevels } from '../chart-toolkit/TrendLineLayer'
import { cryptoFormationSegments } from '../chart-toolkit/TrendLineLayer'
import { candleCloseRefreshDelay } from '../chart-toolkit/candleCloseRefresh'
import { loadResearchSessions } from './chartResearchHistory'
import type { PlanSession } from './chartTradePlan'
import {
  CHART_STUDIES,
  chartStudyLabel,
  readDeltaStudyPreferences,
  saveDeltaStudyPreferences,
  withStandardEmaDefault,
  saveStandardStudyPreferences,
} from './chartStudyChoices'
import { PremiumPriceAlerts } from './PremiumPriceAlerts'
import { type PremiumPlan } from './PremiumRiskPreview'
import { ChartEntryPlan } from './ChartEntryPlan'
import { useChartContract } from './chartContract'
import { ChartToolDock, ChartToolPanel } from './ChartToolDock'
import { PremiumQuote } from './PremiumQuote'
import { ResearchSetupPicker } from './ResearchSetupPicker'
import { ChartStrategyConfigurations } from './ChartStrategyConfigurations.tsx'
import {
  SOURCE_STRATEGIES,
  strategyStorageKey,
  type StrategyReference,
} from './chartStrategyConfigurations'
import { canAutoRetryHistory } from './chartHistoryRecovery'
import { PiyushResearchLayer } from './PiyushResearchLayer'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CandlestickSeries,
  HistogramSeries,
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
import {
  Fragment,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
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
  closeTime,
  type Result,
  type Reference,
} from '../chart-toolkit/model'
import { ToolkitLayer } from '../chart-toolkit/ToolkitLayer'
import { NineIndicatorEngine, type NineResult } from '../chart-toolkit/nineIndicators'
import { NineIndicatorLayer } from '../chart-toolkit/NineIndicatorLayer'
import { NineIndicatorPanel } from '../chart-toolkit/NineIndicatorPanel'
import { resolveIndicatorChart, type IndicatorSource } from '../chart-toolkit/indicatorChartContext'
import { BBChikouLayer } from '../chart-toolkit/BBChikouLayer'
import { calculateBBChikou } from '../chart-toolkit/bbChikou'
import {
  CANDLE_PATTERNS,
  isPatternSelection,
  type PatternSelection,
} from '../chart-toolkit/candlePatterns'
import { analyzeCandles } from '../chart-toolkit/candleProbability'
import { getCandleSeed } from '../chart-toolkit/candleProbabilitySeeds'
import { CandleProbabilityLayer } from '../chart-toolkit/CandleProbabilityLayer'
import { RelatedPatternLayer } from '../chart-toolkit/RelatedPatternLayer'
import { archivePatternEvents } from '../chart-toolkit/archivePatternEngine'
import { patternDisplayRange, patternDisplayEvents } from '../chart-toolkit/patternDisplay'
import { finalPatternEvents, finalPatternReading } from '../chart-toolkit/finalPatternEngine'
import { deduplicateArchiveMatches } from '../chart-toolkit/archivePatternLabels'
import {
  analyzeTrend,
  combineTrend,
  higherTrendInterval,
  trendSummaryLabel,
} from '../chart-toolkit/trendAnalysis'
import { selectTrendSetup } from '../chart-toolkit/trendSetup'
import { TrendSetupLayer } from '../chart-toolkit/TrendSetupLayer'
import { TrendLineLayer } from '../chart-toolkit/TrendLineLayer'
import { ArchivePatternHelp } from '../chart-toolkit/ArchivePatternHelp'
import { CandlestickProbabilityPanel } from '../chart-toolkit/CandlestickProbabilityPanel'
import { readHistorySnapshot, saveHistorySnapshot } from '../chart-toolkit/historySnapshot'
import {
  ToolkitPanel,
  type DisplaySettings,
  type OptionReference,
} from '../chart-toolkit/ToolkitPanel'

const sourceChoices = SOURCE_STRATEGIES.map((s) => [s.id, `${s.id} · ${s.name}`] as const)
const choices = CHART_STUDIES
type History = Awaited<ReturnType<typeof scalpingApi.getHistory>> & { observedAt?: number }
// Keep source observation time fixed. Quotes and the clock cannot confirm cached OHLC.
const verifiedCandleBars = (
  candles: PriceBar[],
  observedAt: number,
  seconds: number,
  indian: boolean,
  session?: PlanSession | null
) =>
  observedAt > 0
    ? candles
        .map((bar) => ({ ...bar, time: bar.time - 19800 }))
        .filter((bar) => {
          if (!session) return closeTime(bar, seconds, indian) <= observedAt
          const midnight = Math.floor((bar.time + session.offset) / 86400) * 86400 - session.offset
          return (
            (seconds >= 86400
              ? midnight + session.end * 60
              : Math.min(bar.time + seconds, midnight + session.end * 60)) <= observedAt
          )
        })
    : []
const readHistory = async (
  symbol: string,
  exchange: string,
  interval: string,
  date?: string,
  signal?: AbortSignal
) => {
  const requestObservedAt = Date.now() / 1000
  try {
    const result =
      exchange === 'DELTA'
        ? await readDeltaHistory(
            symbol,
            interval,
            date,
            signal
              ? AbortSignal.any([signal, AbortSignal.timeout(12000)])
              : AbortSignal.timeout(12000)
          )
        : await scalpingApi.getHistory(symbol, exchange, interval, date, {
            signal,
            timeoutMs: 30000,
          })
    return { ...result, observedAt: requestObservedAt }
  } catch (error) {
    if (
      (error as { code?: string }).code === 'ECONNABORTED' ||
      (error as Error).name === 'TimeoutError'
    )
      throw Error('Broker candles are delayed.')
    throw error
  }
}
const readPlanTrend = async (source: { symbol: string; exchange: string }, signal: AbortSignal) => {
  const response = await readHistory(source.symbol, source.exchange, '15m', undefined, signal)
  if (
    response.status !== 'success' ||
    response.symbol !== source.symbol ||
    response.exchange !== source.exchange ||
    response.interval !== '15m'
  )
    throw Error('Trend candle source unavailable or mismatched')
  return verifiedCandleBars(
    response.candles,
    response.observedAt ?? 0,
    900,
    ['NSE', 'BSE', 'NSE_INDEX', 'BSE_INDEX'].includes(source.exchange)
  )
}
interface Scene {
  chart: IChartApi
  price: ISeriesApi<'Candlestick'>
  upper: ISeriesApi<'Line'>
  lower: ISeriesApi<'Line'>
  ema: ISeriesApi<'Line'>
  ema9: ISeriesApi<'Line'>
  ema15: ISeriesApi<'Line'>
  ema21: ISeriesApi<'Line'>
  fibonacci: IPriceLine[]
  emaOverlay: EmaLiveLayer
  rsi: ISeriesApi<'Line'> | null
  volume: ISeriesApi<'Histogram'> | null
  zones: TradingViewZones
  structure: IPriceLine[]
  sourceLines: IPriceLine[]
  toolkit: ToolkitLayer
  bbChikou: BBChikouLayer
  nine: NineIndicatorLayer
  relatedPatterns: RelatedPatternLayer
  trendSetup: TrendSetupLayer
  trendLines: TrendLineLayer
  probability: CandleProbabilityLayer
  bookGuide: BookPatternLayer
  strategy51: Strategy51Layer
  videoGuide: VideoStrategyLayer
  piyush: PiyushResearchLayer
  legacyActive: boolean
  deltaOrders: DeltaOrderLayer
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
  fitViewport = false,
  initialCandlePattern = 'all',
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
  fitViewport?: boolean
  initialCandlePattern?: PatternSelection
}) {
  const [brokerGuideRecord, setBrokerGuideValue] = useState<{ scope: string; value: GuideBrokerContext | null } | null>(null)
  const [combinedLevels, setCombinedLevels] = useState<CombinedChartLevels | null>(null)
  const [deltaTradeState, setDeltaTradeState] = useState<DeltaChartState | null>(null)
  const [deltaEditProposal, setDeltaEditProposal] = useState<DeltaOrderEditProposal | null>(null)
  const [deltaCloseProposal, setDeltaCloseProposal] = useState<{ nonce: number } | null>(null)
  const requestDeltaClose = useCallback(() => setDeltaCloseProposal({ nonce: Date.now() }), [])
  const clearDeltaClose = useCallback(() => setDeltaCloseProposal(null), [])
  const clearDeltaProposal = useCallback(() => setDeltaEditProposal(null), [])
  const trendPanelId = useId()
  const [trendPanelOpen, setTrendPanelOpen] = useState(() => {
    try {
      return localStorage.getItem('neo.native.chart.trendPanel') !== 'collapsed'
    } catch {
      return true
    }
  })
  function toggleTrendPanel() {
    setTrendPanelOpen((open) => {
      try {
        localStorage.setItem('neo.native.chart.trendPanel', open ? 'collapsed' : 'expanded')
      } catch {}
      return !open
    })
  }
  const [showNeutralPatterns, setShowNeutralPatterns] = useState(false)
  const [showAllPatternHistory, setShowAllPatternHistory] = useState(false)
  const [showUnconfirmedPatterns, setShowUnconfirmedPatterns] = useState(false)
  const [candlePattern, setCandlePattern] = useState<PatternSelection>(() => {
    try {
      const saved = localStorage.getItem('neo.native.chart.patternGuide')
      return initialCandlePattern === 'all' && isPatternSelection(saved)
        ? saved
        : initialCandlePattern
    } catch {
      return initialCandlePattern
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem('neo.native.chart.patternGuide', candlePattern)
    } catch {
      /* Keep current selection. */
    }
  }, [candlePattern])
  const fitted = focusMode || fitViewport
  const [premiumStudyEntryState, setPremiumStudyEntry] = useState<{
    scope: string
    price: number | null
    stop: number | null
  } | null>(null)
  const [premiumPlanState, setPremiumPlan] = useState<{
    scope: string
    plan: PremiumPlan | null
    observedAt: number
  } | null>(null)
  const [piyushMode, setPiyushMode] = useState('off')
  const piyushReward = 2
  const [piyushStatus, setPiyushStatus] = useState(
    'Research reconstruction · use 1-minute index candles'
  )
  const piyushEligible = !!symbol && !!exchange
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
  const [standardStudies, setStandardStudies] = useState<string[]>(() => {
    const selected = (() => {
      try {
        const stored = JSON.parse(localStorage.getItem('neo.native.chart.indicators') || 'null')
        return Array.isArray(stored)
          ? stored.filter((id) => choices.some((c) => c[0] === id))
          : choices
              .filter(
                (c) =>
                  c[0] !== 'volume' &&
                  c[0] !== 'neo-toolkit' &&
                  c[0] !== 'bb-chikou' &&
                  c[0] !== 'candle-probability' &&
                  c[0] !== 'book-pattern-risk-guide' &&
                  !c[0].startsWith('nine-')
              )
              .map((c) => c[0])
      } catch {
        return choices
          .filter(
            (c) =>
              c[0] !== 'volume' &&
              c[0] !== 'neo-toolkit' &&
              c[0] !== 'bb-chikou' &&
              c[0] !== 'candle-probability' &&
              c[0] !== 'book-pattern-risk-guide' &&
              !c[0].startsWith('nine-')
          )
          .map((c) => c[0])
      }
    })()
    return withStandardEmaDefault(selected)
  })
  const [deltaStudies, setDeltaStudies] = useState<string[]>(() =>
    readDeltaStudyPreferences(standardStudies)
  )
  const localStudies = exchange === 'DELTA' ? deltaStudies : standardStudies
  const setLocalStudies = exchange === 'DELTA' ? setDeltaStudies : setStandardStudies
  const [strategy51Settings,setStrategy51Settings] = useState(readStrategy51Preferences)
  const enabled = useMemo(()=>strategy51VisibleStudies(studies ?? localStudies,strategy51Settings),[studies,localStudies,strategy51Settings]),
    enabledRef = useRef(enabled)
  enabledRef.current = enabled
  const mode = useThemeStore((s) => s.mode)
  const appMode = useThemeStore((s) => s.appMode)
  const username = useAuthStore((s) => s.user?.username)
  const broker = useAuthStore((s) => s.user?.broker)
  const guideScope = JSON.stringify([username, appMode, exchange, symbol])
  const brokerGuide = brokerGuideRecord?.scope === guideScope ? brokerGuideRecord.value : null
  const setBrokerGuide = useCallback((value: GuideBrokerContext | null) => {
    setBrokerGuideValue(old => old?.scope === guideScope && JSON.stringify(old.value) === JSON.stringify(value) ? old : { scope: guideScope, value })
  }, [guideScope])
  const sourceStorageKey = strategyStorageKey({
    owner: username,
    broker,
    appMode,
    symbol,
    exchange,
    interval,
  })
  const sourceScope =
    sourceStorageKey ?? JSON.stringify([username, broker, appMode, symbol, exchange, interval])
  const restoredSource = useMemo(() => {
    try {
      const id = sourceStorageKey ? localStorage.getItem(`${sourceStorageKey}:selection`) : ''
      return SOURCE_STRATEGIES.some((s) => s.id === id) ? id! : ''
    } catch {
      return ''
    }
  }, [sourceStorageKey])
  const [sourceSelection, setSourceSelection] = useState<{ scope: string; id: string } | null>(null)
  const sourceId = sourceSelection?.scope === sourceScope ? sourceSelection.id : restoredSource
  const [sourceOpenCounter, setSourceOpenCounter] = useState(0)
  const [sourceLevelState, setSourceLevelState] = useState<{
    scope: string
    id: string
    levels: StrategyReference[]
  } | null>(null)
  const onSourceReferences = useCallback(
    (levels: StrategyReference[]) => {
      setSourceLevelState((old) =>
        old?.scope === sourceScope &&
        old.id === sourceId &&
        JSON.stringify(old.levels) === JSON.stringify(levels)
          ? old
          : { scope: sourceScope, id: sourceId, levels }
      )
    },
    [sourceScope, sourceId]
  )
  const sourceReferences =
    sourceLevelState?.scope === sourceScope && sourceLevelState.id === sourceId
      ? sourceLevelState.levels
      : []
  const chooseSetup = (id: string) => {
    setSourceOpenCounter((value) => value + 1)
    const source = SOURCE_STRATEGIES.some((s) => s.id === id) ? id : ''
    setSourceSelection({ scope: sourceScope, id: source })
    setPiyushMode(source ? 'off' : id || 'off')
    try {
      if (sourceStorageKey) localStorage.setItem(`${sourceStorageKey}:selection`, source)
    } catch {
      /* This selection remains available for the current chart. */
    }
  }
  useEffect(() => {
    if (sourceId) setPiyushMode('off')
  }, [sourceId])

  const replayKey = useMemo(
    () =>
      `neo-trading:${candleKey(username, appMode, symbol, exchange, interval)}:${JSON.stringify(savedRange ?? null)}`,
    [username, appMode, symbol, exchange, interval, savedRange?.start, savedRange?.end]
  )
  const premiumStudyEntry =
    premiumStudyEntryState?.scope === replayKey ? premiumStudyEntryState.price : null
  const onPremiumPlan = useCallback(
    (plan: PremiumPlan | null) => {
      setPremiumPlan((old) => {
        if (!plan && old?.scope !== replayKey) return old
        return old?.scope === replayKey && JSON.stringify(old.plan) === JSON.stringify(plan)
          ? old
          : { scope: replayKey, plan, observedAt: Date.now() / 1000 }
      })
    },
    [replayKey]
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
  const deltaTradingEnabled =
    exchange === 'DELTA' && appMode !== 'analyzer' && !savedRange && !selectedRange && !replay
  const scalpRiskContext = useDeltaScalpRisk(symbol, deltaTradingEnabled)
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
  const [toolkitResultState, setToolkitResult] = useState<{
    scope: string
    result: Result | null
  } | null>(null)
  const toolkitResult = toolkitResultState?.scope === replayKey ? toolkitResultState.result : null
  const [referenceLevels, setReferenceLevels] = useState<Reference[]>([])
  const toolkitOn = enabled.includes('neo-toolkit')
  const videoGuideOn = enabled.includes('video-strategy-guide')
  const strategy51On = enabled.includes('strategies-51-guide')
  const strategy51Clean = strategy51On && strategy51Settings.cleanChart
  const bookGuideOn = enabled.includes('book-pattern-risk-guide')
  const [bookPreferences, setBookPreferences] = useState(readBookPreferences)
  const bookInstrumentScope = `${exchange}:${symbol}`
  const bookInstrument = bookInstrumentForScope(bookPreferences, bookInstrumentScope)
  const bookScope = JSON.stringify([username, appMode, exchange, symbol, interval, savedRange, selectedRange, replay?.until])
  const bookEngine = useMemo(() => new BookPatternEngine(), [bookScope])
  const [bookState, setBookState] = useState<{scope:string;result:BookGuideResult;context:BookContext}|null>(null)
  const [bookClock, setBookClock] = useState(0)
  useEffect(() => {
    saveBookPreferences(bookPreferences)
  }, [bookPreferences])
  useEffect(() => {
    if (!bookGuideOn && !strategy51On) return
    const timer = window.setInterval(() => setBookClock(n => n + 1), 5000)
    return () => window.clearInterval(timer)
  }, [bookGuideOn, strategy51On])

  const strategy51Scope = JSON.stringify([username,appMode,exchange,symbol,interval,savedRange,selectedRange,replay?.until])
  const strategy51Engine = useMemo(()=>new Strategy51Engine(),[strategy51Scope])
  const [strategy51State,setStrategy51State] = useState<{scope:string;result:Strategy51Result}|null>(null)
  const strategy51Data = useStrategy51Data({enabled:strategy51On,symbol,exchange,seconds:replaySeconds(interval),owner:username,mode:appMode,historical:!!(savedRange||selectedRange||replay?.until),readHistory})
  useEffect(()=>{saveStrategy51Preferences(strategy51Settings)},[strategy51Settings])

  const videoScope = JSON.stringify([username, appMode, exchange, symbol, interval, savedRange, selectedRange, replay?.until])
  const [videoChoice, setVideoChoice] = useState<{scope:string; id:VideoStrategyId|''} | null>(null)
  const videoSelected = videoChoice?.scope === videoScope ? videoChoice.id : ''
  const probabilityOn = enabled.includes('candle-probability')
  const patternsOn = enabled.includes('candle-patterns')
  useEffect(() => {
    if (patternsOn) {
      try {
        localStorage.removeItem('neo.native.chart.relatedGuide')
      } catch {}
    }
  }, [patternsOn])
  const [probabilityNow, setProbabilityNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    if (!probabilityOn) return
    setProbabilityNow(Date.now() / 1000)
    const timer = window.setInterval(() => setProbabilityNow(Date.now() / 1000), 5000)
    return () => window.clearInterval(timer)
  }, [probabilityOn])
  const nineOn = enabled.some((id) => id.startsWith('nine-'))
  const [nineSource, setNineSource] = useState<IndicatorSource>('premium')
  const nineChart = resolveIndicatorChart(symbol, exchange, optionReference)
  const useUnderlying = nineChart.kind === 'option' && nineSource === 'underlying'
  const nineScope = `${username}:${appMode}:${symbol}:${exchange}:${interval}:${nineSource}:${nineChart.underlying?.symbol}:${nineChart.underlying?.exchange}`
  const nineEngine = useMemo(() => new NineIndicatorEngine(), [nineScope])
  const [nineState, setNineResult] = useState<{ scope: string; result: NineResult | null } | null>(
    null
  )
  const nineResult = nineState?.scope === nineScope ? nineState.result : null
  const nineAsOf = useRef(0)
  const mfiProxy = useRef<{ scope: string; result: NineResult | null }>({
    scope: nineScope,
    result: null,
  })
  const onMfiProxy = useCallback(
    (next: NineResult | null) => {
      if (mfiProxy.current.scope === nineScope && mfiProxy.current.result === next) return
      mfiProxy.current = { scope: nineScope, result: next }
      if (scene.current) drawRef.current(scene.current)
    },
    [nineScope]
  )
  const referenceReplayDate = replay
    ? new Date(replay.until * 1000).toISOString().slice(0, 10)
    : undefined
  const indian = ['NSE', 'NSE_INDEX', 'NFO', 'BSE', 'BSE_INDEX', 'BFO'].includes(exchange)
  const nineRange =
    savedRange ??
    selectedRange ??
    (referenceReplayDate ? { start: referenceReplayDate, end: referenceReplayDate } : undefined)
  const nineUnderlying = useQuery({
    queryKey: [
      'nine-underlying-history',
      username,
      appMode,
      nineChart.underlying?.symbol,
      nineChart.underlying?.exchange,
      interval,
      nineRange?.start,
      nineRange?.end,
    ],
    enabled: nineOn && useUnderlying && !!nineChart.underlying,
    queryFn: async ({ signal }) => {
      const root = nineChart.underlying!
      const check = (response: History) => {
        if (
          response.status !== 'success' ||
          response.symbol !== root.symbol ||
          response.exchange !== root.exchange ||
          response.interval !== interval
        )
          throw Error('Underlying candle source unavailable or mismatched')
        return response
      }
      if (!nineRange) {
        const response = check(
          await readHistory(root.symbol, root.exchange, interval, undefined, signal)
        )
        return {
          bars: verifiedCandleBars(
            response.candles,
            response.observedAt!,
            replaySeconds(interval),
            indian
          ),
          observedAt: response.observedAt!,
        }
      }
      const warmupDays =
        interval === '1d' ? 400 : Math.ceil(((200 * replaySeconds(interval)) / 22500) * 1.6) + 7
      const start = new Date(Date.parse(nineRange.start) - warmupDays * 86400000)
        .toISOString()
        .slice(0, 10)
      let warmup: PriceBar[] = []
      try {
        const response = check(
          await neoReportsApi.chart(root.symbol, root.exchange, interval, start, nineRange.end)
        )
        warmup = verifiedCandleBars(
          response.candles,
          Date.now() / 1000,
          replaySeconds(interval),
          indian
        ).map((b) => ({ ...b, time: b.time + 19800 }))
      } catch {
        /* Requested days below must still load successfully. */
      }
      // Kotak's date-only index endpoint can be empty. Reuse verified recent
      // and saved candles for the requested day, without admitting future bars.
      const recent = queryClient.getQueryData<{ bars: PriceBar[] }>([
        'nine-underlying-history',
        username,
        appMode,
        root.symbol,
        root.exchange,
        interval,
        undefined,
        undefined,
      ])
      let recentBars = recent?.bars ?? []
      if (!recent) {
        try {
          const response = check(
            await readHistory(root.symbol, root.exchange, interval, undefined, signal)
          )
          recentBars = verifiedCandleBars(
            response.candles,
            response.observedAt!,
            replaySeconds(interval),
            indian
          )
        } catch {
          /* Saved or requested-day history may still be available. */
        }
      }
      warmup = [
        ...new Map(
          [...warmup, ...recentBars.map((b) => ({ ...b, time: b.time + 19800 }))].map((b) => [
            b.time,
            b,
          ])
        ).values(),
      ]
      const loaded = await loadChartRangeHistory(
        nineRange,
        async (date) => {
          const fallback = chartRangeBars(warmup, date, date, 19800)
          try {
            const response = check(
              await readHistory(root.symbol, root.exchange, interval, date, signal)
            )
            const candles = verifiedCandleBars(
              response.candles,
              response.observedAt!,
              replaySeconds(interval),
              indian
            ).map((b) => ({ ...b, time: b.time + 19800 }))
            return {
              status: 'success',
              candles: [...new Map([...fallback, ...candles].map((b) => [b.time, b])).values()],
            }
          } catch (error) {
            if (!fallback.length) throw error
            return { status: 'success', candles: fallback }
          }
        },
        warmup,
        signal
      )
      return { bars: chartBars(loaded.candles), observedAt: Date.now() / 1000 }
    },
    staleTime: 20000,
    refetchOnWindowFocus: false,
    refetchInterval: nineOn && useUnderlying && !nineRange ? 25000 : false,
    retry: false,
  })
  const premiumContract =
    optionReference?.optionExchange === exchange
      ? [optionReference.ce, optionReference.pe].find((leg) => leg?.symbol === symbol)?.contract
      : undefined
  const resolvedContract = useChartContract(
    symbol,
    exchange,
    premiumContract?.tick_size
      ? { symbol, exchange, tick_size: premiumContract.tick_size, lotsize: premiumContract.lotsize }
      : undefined
  )
  useEffect(() => {
    if (scene.current) drawRef.current(scene.current)
  }, [resolvedContract?.tick_size, resolvedContract?.session])
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
      JSON.stringify(resolvedContract?.session),
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
      return verifiedCandleBars(
        result.candles,
        result.observedAt ?? 0,
        3600,
        indian,
        resolvedContract?.session
      )
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
  const publishLiveRef = useRef(publishLive)
  publishLiveRef.current = publishLive
  const quoteWork = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(
    () => () => {
      if (quoteWork.current != null) clearTimeout(quoteWork.current)
      quoteWork.current = null
    },
    [replayKey, !!replay, sessionDate, sessionEndDate]
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
      return { ...result, observedAt: result.observedAt ?? Date.now() / 1000 }
    },
    initialData:
      !savedRange &&
      initialHistory?.symbol === symbol &&
      initialHistory.exchange === exchange &&
      initialHistory.interval === interval
        ? initialHistory
        : undefined,
    initialDataUpdatedAt: initialHistory?.observedAt ? initialHistory.observedAt * 1000 : 0,
    placeholderData: snapshot,
    staleTime: 20000,
    refetchOnWindowFocus: (query) =>
      query.state.status === 'error' && canAutoRetryHistory(query.state.error),
    // Keep reconciling after a transient timeout; saved candles never become verified by waiting.
    refetchInterval: (query) =>
      query.state.status === 'error'
        ? canAutoRetryHistory(query.state.error)
          ? 15000
          : false
        : savedRange
          ? false
          : 25000,
    retry: false,
  })
  const usingSnapshot = history.isPlaceholderData || (!history.data && !!snapshot)
  const historyObservedAt = usingSnapshot
    ? 0
    : (history.data?.observedAt ??
      (history.data === initialHistory ? 0 : history.dataUpdatedAt / 1000))
  const higherInterval = higherTrendInterval(interval)
  const liveTrendSource = patternsOn && !savedRange && !selectedRange && !replay
  const higherTrendHistory = useQuery({
    queryKey: ['neo-trend-history', exchange, symbol, higherInterval],
    enabled: Boolean(liveTrendSource && higherInterval && symbol && exchange),
    queryFn: async ({ signal }) => {
      const response = await readHistory(symbol, exchange, higherInterval!, undefined, signal)
      if (
        response.status !== 'success' ||
        response.symbol !== symbol ||
        response.exchange !== exchange ||
        response.interval !== higherInterval
      )
        throw Error('Higher timeframe candles are unavailable.')
      return response
    },
    staleTime: 20000,
    refetchInterval: liveTrendSource ? 25000 : false,
    retry: false,
  })
  const dailyPivotHistory = useQuery({
    queryKey: ['neo-fibonacci-daily', exchange, symbol],
    enabled: Boolean(
      symbol &&
        exchange &&
        enabled.includes('fibonacci-pivots') &&
        !savedRange &&
        !selectedRange &&
        !replay
    ),
    queryFn: async ({ signal }) => {
      const response = await readHistory(symbol, exchange, '1d', undefined, signal)
      if (
        response.status !== 'success' ||
        response.symbol !== symbol ||
        response.exchange !== exchange ||
        response.interval !== '1d'
      )
        throw Error('Daily Fibonacci pivot candles are unavailable.')
      return response
    },
    staleTime: 60000,
    refetchInterval:
      enabled.includes('fibonacci-pivots') && !savedRange && !selectedRange && !replay
        ? 60000
        : false,
    retry: false,
  })
  const hourlyLevelHistory = useQuery({
    queryKey: ['neo-hourly-levels', exchange, symbol],
    enabled: Boolean(liveTrendSource && exchange === 'DELTA' && symbol),
    queryFn: async ({ signal }) => {
      const response = await readHistory(symbol, exchange, '1h', undefined, signal)
      if (
        response.status !== 'success' ||
        response.symbol !== symbol ||
        response.exchange !== exchange ||
        response.interval !== '1h'
      )
        throw Error('Hourly price levels are unavailable.')
      return response
    },
    staleTime: 30000,
    refetchInterval: () =>
      liveTrendSource ? (candleCloseRefreshDelay(Date.now(), 3600) ?? false) : false,
    retry: false,
  })
  // Poll exactly at candle boundaries as well as on exchange stream rollover.
  // A clock tick requests new authoritative OHLC; it never promotes a partial bar.
  useEffect(() => {
    if (
      !symbol ||
      !exchange ||
      savedRange ||
      selectedRange ||
      replay ||
      (!patternsOn && !probabilityOn && !videoGuideOn)
    )
      return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const schedule = () => {
      const delay = candleCloseRefreshDelay(
        Date.now(),
        replaySeconds(interval),
        resolvedContract?.session ?? (indian ? { start: 555, end: 930, offset: 19800 } : null)
      )
      if (delay == null) return
      timer = setTimeout(() => {
        if (stopped) return
        void queryClient.invalidateQueries(
          {
            queryKey: ['neo-tv-history', exchange, symbol, interval, undefined, undefined],
            exact: true,
          },
          { cancelRefetch: false }
        )
        if (higherInterval)
          void queryClient.invalidateQueries(
            {
              queryKey: ['neo-trend-history', exchange, symbol, higherInterval],
              exact: true,
            },
            { cancelRefetch: false }
          )
        schedule()
      }, delay)
    }
    schedule()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
  }, [
    symbol,
    exchange,
    interval,
    savedRange,
    selectedRange,
    replay,
    patternsOn,
    probabilityOn,
    videoGuideOn,
    resolvedContract?.session,
    indian,
    higherInterval,
    queryClient,
  ])
  const deltaStudyBoundary = useRef<{ scope: string; time: number } | null>(null)
  useEffect(() => {
    if (
      exchange !== 'DELTA' ||
      savedRange ||
      selectedRange ||
      replay ||
      usingSnapshot ||
      !history.isSuccess ||
      (!patternsOn && !probabilityOn && !videoGuideOn) ||
      !delta.connected ||
      !delta.bar
    ) {
      deltaStudyBoundary.current = null
      return
    }
    const time = delta.bar.time,
      scope = `${symbol}:${interval}`
    if (
      !Number.isFinite(time) ||
      !Number.isFinite(delta.published) ||
      time > (delta.published ?? 0)
    )
      return
    const previous = deltaStudyBoundary.current
    if (previous?.scope === scope && time <= previous.time) return
    deltaStudyBoundary.current = { scope, time }
    if (previous?.scope !== scope) return
    // The next exchange candle proves a boundary passed. Fetch authoritative
    // final OHLC immediately; never promote a cached partial bar by wall clock.
    void queryClient.invalidateQueries(
      {
        queryKey: ['neo-tv-history', exchange, symbol, interval, undefined, undefined],
        exact: true,
      },
      { cancelRefetch: false }
    )
  }, [
    exchange,
    symbol,
    interval,
    savedRange,
    selectedRange,
    replay,
    usingSnapshot,
    history.isSuccess,
    patternsOn,
    probabilityOn,
    videoGuideOn,
    delta.connected,
    delta.bar?.time,
    delta.published,
    queryClient,
  ])
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
      JSON.stringify(resolvedContract?.session),
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
      let verifiedWarmup = verifiedCandleBars(
        warmup,
        historyObservedAt,
        replaySeconds(interval),
        indian,
        resolvedContract?.session
      )
      const verifiedDays: PriceBar[] = []
      try {
        const archivedObservedAt = Date.now() / 1000
        const archived = await neoReportsApi.chart(
          symbol,
          exchange,
          interval,
          warmupStart,
          range.start
        )
        warmup = [...(archived?.candles ?? []), ...warmup]
        const existingTimes = new Set(verifiedWarmup.map((bar) => bar.time))
        verifiedWarmup = [
          ...verifiedCandleBars(
            archived?.candles ?? [],
            archivedObservedAt,
            replaySeconds(interval),
            indian,
            resolvedContract?.session
          ).filter((bar) => !existingTimes.has(bar.time)),
          ...verifiedWarmup,
        ]
      } catch {
        // Broker day history below remains authoritative for the requested dates.
      }
      const loadedRange = await loadChartRangeHistory(
        range,
        async (date) => {
          const loaded = chartRangeBars(history.data?.candles ?? [], date, date, 19800)
          if (loaded.length) {
            verifiedDays.push(
              ...verifiedCandleBars(
                loaded,
                historyObservedAt,
                replaySeconds(interval),
                indian,
                resolvedContract?.session
              )
            )
            return { status: 'success', candles: loaded }
          }
          const dayKey = ['neo-tv-day', username, appMode, exchange, symbol, interval, date]
          const day = await queryClient.fetchQuery({
            queryKey: dayKey,
            queryFn: () => readHistory(symbol, exchange, interval, date),
            staleTime: date === today ? 20000 : 60000,
            retry: false,
          })
          verifiedDays.push(
            ...chartRangeBars(
              verifiedCandleBars(
                day.candles,
                day.observedAt ?? 0,
                replaySeconds(interval),
                indian,
                resolvedContract?.session
              ),
              date,
              date
            )
          )
          return day
        },
        warmup,
        signal,
        exchange === 'DELTA'
      )
      const start = chartRangeBounds(sessionDate, sessionEndDate)!.start
      return {
        ...loadedRange,
        probabilityBars: [...verifiedWarmup.filter((bar) => bar.time < start), ...verifiedDays],
        observedAt: Date.now() / 1000,
      }
    },
    staleTime: 60000,
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      query.state.status === 'error' && canAutoRetryHistory(query.state.error) ? 15000 : false,
    retry: false,
  })
  const rangeLoading = !!selectedRange && !savedRange && rangeHistory.isPending
  const rangeError = !!selectedRange && !savedRange && rangeHistory.isError
  const resolvedSessionKey = JSON.stringify(resolvedContract?.session ?? null)
  const researchHistory = useQuery({
    queryKey: [
      'chart-research-history',
      username,
      appMode,
      symbol,
      exchange,
      '1m',
      piyushMode === 'previous_day_break_5m',
      resolvedSessionKey,
    ],
    enabled:
      piyushMode !== 'off' &&
      !savedRange &&
      !selectedRange &&
      !replay &&
      !history.isError &&
      !usingSnapshot &&
      !!history.data?.candles.length,
    queryFn: async ({ signal }) => {
      const check = (result: History) => {
        if (
          result.status !== 'success' ||
          result.symbol !== symbol ||
          result.exchange !== exchange ||
          result.interval !== '1m'
        )
          throw Error('Research candle source unavailable or mismatched')
        return chartBars(result.candles).filter((b) => b.time <= (result.observedAt ?? 0))
      }
      const latest =
        interval === '1m' && history.data
          ? check({ ...history.data, observedAt: historyObservedAt })
          : check(await readHistory(symbol, exchange, '1m', undefined, signal))
      return loadResearchSessions(
        latest,
        piyushMode === 'previous_day_break_5m',
        exchange === 'DELTA',
        resolvedContract?.session ?? undefined,
        async (date) => {
          const response = await queryClient.fetchQuery({
            queryKey: ['chart-research-day', username, appMode, symbol, exchange, date],
            staleTime: date === today ? 20000 : Infinity,
            retry: false,
            queryFn: ({ signal: inner }) =>
              readHistory(symbol, exchange, '1m', date, AbortSignal.any([signal, inner])),
          })
          return check(response)
        }
      )
    },
    staleTime: 20000,
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval:
      piyushMode !== 'off' && !savedRange && !selectedRange && !replay ? 30000 : false,
  })
  const researchBars = useMemo(() => researchHistory.data ?? [], [researchHistory.data])
  useEffect(() => {
    if (scene.current) drawRef.current(scene.current)
  }, [researchBars, piyushMode])
  const ninePremiumBars = useMemo(() => {
    if (
      nineChart.kind !== 'option' ||
      nineSource !== 'premium' ||
      usingSnapshot ||
      rangeLoading ||
      rangeError ||
      history.isError
    )
      return []
    if (selectedRange && !savedRange) return rangeHistory.data?.probabilityBars ?? []
    return history.data?.symbol === symbol &&
      history.data.exchange === exchange &&
      history.data.interval === interval
      ? verifiedCandleBars(
          history.data.candles,
          historyObservedAt,
          replaySeconds(interval),
          indian,
          resolvedContract?.session
        )
      : []
  }, [
    nineChart.kind,
    resolvedContract?.session,
    nineSource,
    usingSnapshot,
    rangeLoading,
    rangeError,
    history.isError,
    selectedRange,
    savedRange,
    rangeHistory.data,
    history.data,
    historyObservedAt,
    symbol,
    exchange,
    interval,
    indian,
  ])
  const probabilityStudy = useMemo(() => {
    if (
      (!probabilityOn && !patternsOn) ||
      !resolvedContract?.tick_size ||
      rangeLoading ||
      rangeError ||
      (!(selectedRange && !savedRange) && (usingSnapshot || history.isError))
    )
      return null
    const source =
      selectedRange && !savedRange
        ? (rangeHistory.data?.probabilityBars ?? [])
        : history.data?.symbol === symbol &&
            history.data.exchange === exchange &&
            history.data.interval === interval
          ? verifiedCandleBars(
              history.data.candles,
              historyObservedAt,
              replaySeconds(interval),
              indian,
              resolvedContract?.session
            )
          : []
    if (!source.length) return null
    const observedAt =
      selectedRange && !savedRange ? (rangeHistory.data?.observedAt ?? 0) : historyObservedAt
    const asOf = replay
      ? Math.min(replay.until - 19800, observedAt)
      : savedRange
        ? Math.min(chartRangeBounds(savedRange.start, savedRange.end)!.end, observedAt)
        : selectedRange
          ? Math.min(chartRangeBounds(sessionDate, sessionEndDate)!.end, observedAt)
          : observedAt
    const scope = {
      symbol,
      exchange,
      seconds: replaySeconds(interval),
      indian,
      session: resolvedContract?.session,
      tickSize: resolvedContract?.tick_size,
      pattern: candlePattern,
    }
    return analyzeCandles(source, { ...scope, asOf }, getCandleSeed(scope))
  }, [
    probabilityOn,
    patternsOn,
    candlePattern,
    history.isError,
    resolvedContract?.session,
    resolvedContract?.tick_size,
    usingSnapshot,
    rangeLoading,
    rangeError,
    selectedRange,
    savedRange,
    rangeHistory.data,
    history.data,
    historyObservedAt,
    symbol,
    exchange,
    interval,
    indian,
    replay,
    sessionDate,
    sessionEndDate,
  ])
  const videoResult = useMemo(() => {
    const ranged = Boolean(selectedRange && !savedRange)
    const observed = ranged ? (rangeHistory.data?.observedAt ?? 0) : historyObservedAt
    const cutoff = replay ? Math.min(replay.until - 19800, observed)
      : savedRange ? Math.min(chartRangeBounds(savedRange.start, savedRange.end)!.end, observed)
      : selectedRange ? Math.min(chartRangeBounds(sessionDate, sessionEndDate)!.end, observed) : observed
    const matched = history.data?.symbol === symbol && history.data.exchange === exchange && history.data.interval === interval
    const usable = videoGuideOn && !rangeLoading && !rangeError &&
      (ranged || (!usingSnapshot && !history.isError && matched))
    const source = !usable ? [] : ranged ? (rangeHistory.data?.probabilityBars ?? [])
      : verifiedCandleBars(history.data?.candles ?? [], cutoff, replaySeconds(interval), indian, resolvedContract?.session)
    return videoStrategyGuide(source, { seconds: replaySeconds(interval), asOf: cutoff,
      tickSize: resolvedContract?.tick_size ?? 0, indian, session: resolvedContract?.session })
  }, [videoGuideOn, usingSnapshot, rangeLoading, rangeError, history.isError, history.data, rangeHistory.data,
    historyObservedAt, replay, selectedRange, savedRange, sessionDate, sessionEndDate, symbol, exchange, interval, indian, resolvedContract?.tick_size, resolvedContract?.session])

  const timeframePriceLevels = useMemo(() => {
    const response = hourlyLevelHistory.data
    if (
      !liveTrendSource ||
      exchange !== 'DELTA' ||
      usingSnapshot ||
      history.isError ||
      hourlyLevelHistory.isError ||
      !response ||
      response.symbol !== symbol ||
      response.exchange !== exchange ||
      response.interval !== '1h'
    )
      return []
    const cutoff = Math.min(response.observedAt ?? 0, historyObservedAt)
    return higherTimeframeLevels(verifiedCandleBars(response.candles, cutoff, 3600, false), cutoff)
  }, [
    hourlyLevelHistory.data,
    hourlyLevelHistory.isError,
    liveTrendSource,
    exchange,
    symbol,
    usingSnapshot,
    history.isError,
    historyObservedAt,
  ])
  const swingPriceLevels = useMemo(
    () =>
      supportResistanceLevels(
        probabilityStudy?.bars ?? [],
        replaySeconds(interval),
        resolvedContract?.session,
        indian
      ),
    [probabilityStudy, interval, resolvedContract?.session, indian]
  )
  const relatedEvents = useMemo(
    () =>
      patternsOn
        ? finalPatternEvents(
            probabilityStudy?.bars ?? [],
            replaySeconds(interval),
            resolvedContract?.session,
            indian
          )
        : [],
    [patternsOn, probabilityStudy, interval, resolvedContract?.session, indian]
  )
  const displayedPatternEvents = useMemo(
    () => patternDisplayEvents(
      patternsOn && showUnconfirmedPatterns
        ? archivePatternEvents(
            probabilityStudy?.bars ?? [], 'all', replaySeconds(interval),
            -Infinity, Infinity, resolvedContract?.session, indian, true
          )
        : relatedEvents,
      showUnconfirmedPatterns
    ),
    [patternsOn, showUnconfirmedPatterns, probabilityStudy, interval, resolvedContract?.session, indian, relatedEvents]
  )
  const latestPatternMatches = useMemo(
    () =>
      deduplicateArchiveMatches(
        relatedEvents.filter(
          (match) =>
            match.time === probabilityStudy?.bars.at(-1)?.time &&
            (showNeutralPatterns || match.side !== 'NEUTRAL')
        )
      ),
    [relatedEvents, probabilityStudy, showNeutralPatterns]
  )
  const archiveReading = useMemo(
    () => finalPatternReading(relatedEvents, probabilityStudy?.bars ?? []),
    [relatedEvents, probabilityStudy]
  )
  const deltaCurrentEmaTrend = useServerEmaTrend(probabilityStudy?.bars ?? [], exchange === 'DELTA', replaySeconds(interval))
  const currentTrend = useMemo(
    () =>
      exchange === 'DELTA' ? deltaCurrentEmaTrend : analyzeTrend(probabilityStudy?.bars ?? [], {
        seconds: replaySeconds(interval),
        session: resolvedContract?.session,
        indian,
      }),
    [probabilityStudy, interval, resolvedContract?.session, indian, exchange, deltaCurrentEmaTrend]
  )
  const higherTrendSource = useMemo(() => {
    const response = higherTrendHistory.data
    if (
      !liveTrendSource ||
      !higherInterval ||
      higherTrendHistory.isError ||
      !response ||
      response.symbol !== symbol ||
      response.exchange !== exchange ||
      response.interval !== higherInterval ||
      usingSnapshot ||
      history.isError
    )
      return null
    const cutoff = Math.min(response.observedAt ?? 0, historyObservedAt)
    const source = verifiedCandleBars(
      response.candles,
      cutoff,
      replaySeconds(higherInterval),
      indian,
      resolvedContract?.session
    )
    const latest = source.at(-1)
    if (
      !latest ||
      cutoff - closeTime(latest, replaySeconds(higherInterval), indian) >
        2 * replaySeconds(higherInterval)
    )
      return null
    return source
  }, [
    higherTrendHistory.data,
    higherTrendHistory.isError,
    liveTrendSource,
    higherInterval,
    symbol,
    exchange,
    usingSnapshot,
    history.isError,
    historyObservedAt,
    indian,
    resolvedContract?.session,
  ])
  const deltaHigherEmaTrend = useServerEmaTrend(higherTrendSource ?? [], exchange === 'DELTA', replaySeconds(higherInterval ?? interval))
  const higherTrend = useMemo(() => higherTrendSource ? exchange === 'DELTA' ? deltaHigherEmaTrend : analyzeTrend(higherTrendSource, {
    seconds: replaySeconds(higherInterval!), session: resolvedContract?.session, indian,
  }) : null, [higherTrendSource, exchange, deltaHigherEmaTrend, higherInterval, resolvedContract?.session, indian])
  const combinedTrend = useMemo(
    () => combineTrend(currentTrend, higherTrend),
    [currentTrend, higherTrend]
  )
  const deltaRiskContext = useMemo<DeltaRiskContext | null>(() => {
    const response = history.data
    if (
      !deltaTradingEnabled ||
      usingSnapshot ||
      history.isError ||
      !response ||
      response.symbol !== symbol ||
      response.exchange !== 'DELTA' ||
      response.interval !== interval
    )
      return null
    const seconds = replaySeconds(interval)
    const bars = verifiedCandleBars(response.candles, historyObservedAt, seconds, false)
    const reading = deltaCurrentEmaTrend.time === bars.at(-1)?.time ? deltaCurrentEmaTrend : { ...deltaCurrentEmaTrend, direction: 'unavailable' as const }
    const levels = supportResistanceLevels(bars, seconds, undefined, false)
    // A contrary higher timeframe blocks a new managed entry; no open candle is evidence.
    const entryAligned =
      !higherTrend ||
      higherTrend.direction === 'unavailable' ||
      higherTrend.direction === reading.direction
    return {
      symbol,
      intervalSeconds: seconds,
      sourceTime: bars.at(-1)?.time ?? 0,
      observedAt: historyObservedAt,
      direction: reading.direction,
      trendReason:
        !entryAligned && higherTrend
          ? `${interval}: ${reading.label}. ${higherInterval}: ${higherTrend.label}. ${higherTrend.reason}`
          : reading.reason,
      entryAligned,
      bars,
      ...levels,
    }
  }, [
    deltaTradingEnabled,
    history.data,
    history.isError,
    usingSnapshot,
    symbol,
    interval,
    historyObservedAt,
    higherTrend,
    deltaCurrentEmaTrend,
    higherInterval,
  ])
  const trendShapeEvents = useMemo(
    () => relatedEvents.filter((event) => event.entry !== undefined && event.target !== undefined),
    [relatedEvents]
  )
  const trendSetup = useMemo(
    () =>
      selectTrendSetup(
        trendShapeEvents,
        probabilityStudy?.bars ?? [],
        resolvedContract?.tick_size ?? 0,
        { seconds: replaySeconds(interval), session: resolvedContract?.session, indian }
      ),
    [
      trendShapeEvents,
      probabilityStudy,
      resolvedContract?.tick_size,
      interval,
      resolvedContract?.session,
      indian,
    ]
  )
  const trendSetupAligned = Boolean(
    trendSetup?.status === 'active' &&
      combinedTrend.aligned &&
      (trendSetup.side === 'CALL'
        ? combinedTrend.direction === 'up'
        : combinedTrend.direction === 'down')
  )
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
        if (exchange === 'DELTA') saveDeltaStudyPreferences(localStudies)
        else saveStandardStudyPreferences(localStudies)
      } catch {
        /* Keep this view's choice. */
      }
    }
  }, [localStudies, studies, exchange])

  function drawStudies(s: Scene) {
    const requestedAsOf = replayRef.current
      ? replayRef.current.until - 19800
      : savedRange
        ? chartRangeBounds(savedRange.start, savedRange.end)!.end
        : selectedRange
          ? Math.min(Date.now() / 1000, chartRangeBounds(sessionDate, sessionEndDate)!.end)
          : Date.now() / 1000
    // A cached forming premium candle cannot become confirmed just by waiting.
    // Quotes still update the plotted price; studies wait for broker reconciliation.
    const premiumObservedAt =
      usingSnapshot || history.isError || rangeLoading || rangeError
        ? 0
        : selectedRange && !savedRange
          ? (rangeHistory.data?.observedAt ?? 0)
          : history.data?.symbol === symbol &&
              history.data.exchange === exchange &&
              history.data.interval === interval
            ? historyObservedAt
            : 0
    if (enabledRef.current.includes('book-pattern-risk-guide')) {
      const seconds = replaySeconds(interval)
      const session = resolvedContract?.session ?? (indian ? {start:555,end:930,offset:19800} : undefined)
      const context = bookChartContext({
        symbol, exchange, intervalSeconds: seconds, now: requestedAsOf,
        observedAt: premiumObservedAt, quoteObservedAt: (feedTimeMs(tick?.timestamp) ?? 0) / 1000,
        sourceReady: premiumObservedAt > 0,
        connected: exchange === 'DELTA' ? delta.connected : market.isConnected,
        tickSize: resolvedContract?.tick_size ?? 0,
        session, historical: !!(savedRange || selectedRange || replayRef.current),
        instrument: validatedBookInstrument(bookInstrument, {symbol,exchange}),
      })
      const result = bookEngine.reconcile(bookChartBars(calculationBars.current, seconds, session), context, bookPreferences.settings)
      s.bookGuide.update(result, bookChartBars(shownBars.current, seconds, session), bookPreferences.settings)
      setBookState({scope:bookScope,result,context})
    } else {
      s.bookGuide.update(null, [], bookPreferences.settings)
    }
    if (enabledRef.current.includes('strategies-51-guide')) {
      const seconds = replaySeconds(interval)
      const session = resolvedContract?.session ?? (indian ? {start:555,end:930,offset:19800} : undefined)
      const context = bookChartContext({symbol,exchange,intervalSeconds:seconds,now:requestedAsOf,observedAt:premiumObservedAt,quoteObservedAt:(feedTimeMs(tick?.timestamp)??0)/1000,sourceReady:premiumObservedAt>0,connected:exchange==='DELTA'?delta.connected:market.isConnected,tickSize:resolvedContract?.tick_size??0,session,historical:!!(savedRange||selectedRange||replayRef.current)})
      const bars = bookChartBars(calculationBars.current,seconds,session)
      const option = deriveOptionEvidence(symbol,exchange,bars,strategy51Data.extras.underlying?.bars??[],strategy51Data.chain,strategy51Settings.supplied,seconds)
      const result = strategy51Engine.reconcile(bars,context,strategy51Settings,{...strategy51Data.extras,option,historical:!!(savedRange||selectedRange||replayRef.current),session:session??(exchange==='DELTA'||exchange==='CRYPTO'?{start:0,end:1440,offset:0}:null)})
      s.strategy51.update(result,bookChartBars(shownBars.current,seconds,session),strategy51Settings)
      setStrategy51State({scope:strategy51Scope,result})
    } else {
      s.strategy51.update(null,[],strategy51Settings)
    }
    const asOf =
      nineChart.kind === 'option' || exchange === 'DELTA'
        ? Math.min(requestedAsOf, premiumObservedAt)
        : requestedAsOf
    const first = shownBars.current[0]?.time ?? 0,
      last = shownBars.current.at(-1)?.time ?? 0
    const patternRange = patternDisplayRange(shownBars.current, showAllPatternHistory)
    const researchAvailable =
      !history.isError &&
      !usingSnapshot &&
      !rangeLoading &&
      !rangeError &&
      !savedRange &&
      !selectedRange &&
      !replayRef.current &&
      !researchHistory.isError
    const researchStatus = s.piyush.update(
      researchAvailable ? researchBars : [],
      piyushMode,
      2,
      symbol,
      '1m',
      first,
      last,
      {
        universal: true,
        continuous: exchange === 'DELTA',
        tickSize: resolvedContract?.tick_size,
        session: resolvedContract?.session,
        optionSide: /^(?:NFO|BFO|MCX|CDS|BCD|NCO)$/.test(exchange)
          ? (/(CE|PE)$/.exec(symbol)?.[0] as 'CE' | 'PE' | undefined)
          : undefined,
        hostTimes: shownBars.current.map((b) => b.time),
        hostSeconds: replaySeconds(interval),
      }
    )
    setPiyushStatus(
      piyushMode !== 'off' && !researchAvailable
        ? 'Research paused: verified current source candles are unavailable, or history/replay is selected.'
        : piyushMode !== 'off' && researchHistory.isPending
          ? 'Loading confirmed 1-minute research candles…'
          : researchStatus
    )
    s.probability.update(
      probabilityStudy,
      patternRange.first,
      patternRange.last,
      ['NSE_INDEX', 'BSE_INDEX'].includes(exchange),
      exchange === 'DELTA',
      nineChart.optionSide,
      false,
      enabledRef.current.includes('candle-probability'),
      showUnconfirmedPatterns
    )
    s.relatedPatterns.updateEvents(
      displayedPatternEvents,
      probabilityStudy?.bars ?? [],
      patternRange.first,
      patternRange.last,
      showNeutralPatterns
    )
    s.videoGuide.update(videoResult, videoSelected, probabilityStudy?.bars ?? calculationBars.current, {
      first: patternRange.first, last: patternRange.last,
      showPending: showUnconfirmedPatterns, showAll: showAllPatternHistory,
    })
    s.trendSetup.update(trendSetup)
    s.trendLines.update(
      patternsOn ? (probabilityStudy?.bars ?? []) : [],
      replaySeconds(interval),
      trendSetup?.status === 'active' ? trendSetup.boundary : undefined,
      resolvedContract?.session,
      indian,
      patternsOn
        ? cryptoFormationSegments(displayedPatternEvents, probabilityStudy?.bars ?? [], patternRange.first, patternRange.last, showUnconfirmedPatterns)
        : [],
      timeframePriceLevels
    )
    nineAsOf.current = asOf
    const independent =
      enabledRef.current.some((id) => id.startsWith('nine-')) &&
      first &&
      (!useUnderlying || (nineChart.underlying && nineUnderlying.data && !nineUnderlying.isError))
        ? nineEngine.update(
            useUnderlying
              ? nineUnderlying.data!.bars
              : nineChart.kind === 'option'
                ? ninePremiumBars
                : calculationBars.current,
            {
              seconds: replaySeconds(interval),
              asOf: useUnderlying ? Math.min(requestedAsOf, nineUnderlying.data!.observedAt) : asOf,
              indian,
              continuous: exchange === 'DELTA',
              session: useUnderlying ? undefined : resolvedContract?.session,
            }
          )
        : null
    s.nine.update(
      independent,
      enabledRef.current,
      first,
      last,
      mfiProxy.current.scope === nineScope ? mfiProxy.current.result : null,
      shownBars.current,
      { chart: nineChart, source: nineSource }
    )
    setNineResult({ scope: nineScope, result: independent })
    const bbStudy =
      enabledRef.current.includes('bb-chikou') && first
        ? calculateBBChikou(calculationBars.current, {
            seconds: replaySeconds(interval),
            asOf,
            continuous: exchange === 'DELTA',
            reward: 2,
            longOnly: nineChart.kind === 'option',
            tickSize: resolvedContract?.tick_size,
            session: resolvedContract?.session,
          })
        : null
    s.bbChikou.update(bbStudy, first, last, exchange === 'DELTA', 2, nineChart.optionSide)
    const bbEntry = bbStudy?.latest?.entry ?? null,
      bbStop = bbStudy?.latest?.side === 'BULL' ? bbStudy.latest.stop : null
    setPremiumStudyEntry((old) =>
      old?.scope === replayKey && old.price === bbEntry && old.stop === bbStop
        ? old
        : { scope: replayKey, price: bbEntry, stop: bbStop }
    )
    const result =
      enabledRef.current.includes('neo-toolkit') && first && asOf > 0
        ? engine.update(calculationBars.current, {
            seconds: replaySeconds(interval),
            asOf,
            indian,
            continuous: exchange === 'DELTA',
            session: resolvedContract?.session,
          })
        : null
    const references =
      result && toolkitSettings.references
        ? completedReferences(referenceHistory.data ?? [], 3600, asOf, indian)
        : []
    s.toolkit.update(result, references, first, last, {
      ...toolkitSettings,
      labelTop: focusMode ? 104 : 0,
      directional: exchange === 'DELTA',
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
    setToolkitResult((old) =>
      old?.scope === replayKey && old.result === result ? old : { scope: replayKey, result }
    )
    setReferenceLevels((old) =>
      JSON.stringify(old) === JSON.stringify(references) ? old : references
    )
    s.emaOverlay.update(
      calculationBars.current,
      enabledRef.current.includes('ema-9-15'),
      shownBars.current.at(0)?.time ?? 0,
      shownBars.current.at(-1)?.time ?? 0,
      asOf - replaySeconds(interval),
      exchange === 'DELTA' ? replaySeconds(interval) : 0,
      historyObservedAt,
      replaySeconds(interval)
    )
    for (const level of s.fibonacci) s.price.removePriceLine(level)
    const pivotResponse = dailyPivotHistory.data
    const pivotDays =
      pivotResponse &&
      !dailyPivotHistory.isError &&
      !savedRange &&
      !selectedRange &&
      !replayRef.current &&
      !usingSnapshot &&
      !history.isError
        ? chartBars(pivotResponse.candles)
        : []
    const pivots = enabledRef.current.includes('fibonacci-pivots')
      ? fibonacciPivots(
          pivotDays,
          Math.min(requestedAsOf, pivotResponse?.observedAt ?? 0),
          indian ? 19800 : 0
        )
      : []
    s.fibonacci = pivots.map((level) =>
      s.price.createPriceLine({
        ...level,
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
      })
    )
    const volumeOn = enabledRef.current.includes('volume')
    const paneChanged = volumeOn !== !!s.volume || enabledRef.current.includes('rsi') !== !!s.rsi
    if (volumeOn !== !!s.volume) {
      // Remove RSI first: deleting an empty pane shifts every following pane index.
      if (s.rsi) {
        s.chart.removeSeries(s.rsi)
        s.rsi = null
      }
      if (s.volume) {
        s.chart.removeSeries(s.volume)
        s.volume = null
      }
      if (volumeOn)
        s.volume = s.chart.addSeries(
          HistogramSeries,
          { priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: true },
          1
        )
    }
    s.volume?.setData(
      shownBars.current
        .filter((bar) => Number.isFinite(bar.volume) && bar.volume >= 0)
        .map((bar) => ({
          time: bar.time as UTCTimestamp,
          value: bar.volume,
          color: bar.close >= bar.open ? '#26a69a' : '#ef5350',
        }))
    )
    if (paneChanged)
      s.chart.panes().forEach((pane, index) => pane.setStretchFactor(index === 0 ? 6 : 1))
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
    const computed = computeStudies(calculationBars.current, interval, asOf, {
        continuous: exchange === 'DELTA',
      }),
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
            autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
          },
          s.volume ? 2 : 1
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
        s.chart.panes().forEach((pane, index) => pane.setStretchFactor(index === 0 ? 6 : 1))
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
    if (quoteWork.current != null) {
      clearTimeout(quoteWork.current)
      quoteWork.current = null
    }
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
      protectChartHistoryRefresh(chart)
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
      let emaOverlay: EmaLiveLayer
      const zones = new TradingViewZones(dark)
      price.attachPrimitive(zones)
      s = {
        chart,
        price,
        upper: line('#5b8def'),
        lower: line('#5b8def'),
        ema: line('#dca94c', 2),
        fibonacci: [],

        rsi: null,
        volume: null,
        zones,
        structure: [],
        sourceLines: [],
        toolkit: new ToolkitLayer(chart, price, dark),
        bbChikou: new BBChikouLayer(chart, price),
        nine: new NineIndicatorLayer(price),
        probability: new CandleProbabilityLayer(price),
        bookGuide: new BookPatternLayer(price),
        strategy51: new Strategy51Layer(price),
        videoGuide: new VideoStrategyLayer(price),
        relatedPatterns: new RelatedPatternLayer(price),
        trendSetup: new TrendSetupLayer(price),
        trendLines: new TrendLineLayer(price),
        piyush: new PiyushResearchLayer(chart, price),
        legacyActive: false,
        deltaOrders: new DeltaOrderLayer(
          chart,
          price,
          host.current,
          setDeltaEditProposal,
          requestDeltaClose
        ),
        ema9: line('#3b82f6', 1),
        ema15: line('#ef5350', 1),
        ema21: line('#a855f7', 1),
        get emaOverlay() {
          return emaOverlay
        },
      }
      const emaMarkers = new EmaCrossMarks(s.ema9, dark)
      emaOverlay = new EmaLiveLayer(s.ema9, s.ema15, markers => emaMarkers.setMarkers(markers), s.ema21)
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
      if (s) {
        for (const line of s.sourceLines) s.price.removePriceLine(line)
        s.sourceLines = []
        s.emaOverlay.destroy()
        s.deltaOrders.destroy()
        s.bookGuide.destroy()
        s.strategy51.destroy()
        s.videoGuide.destroy()
        s.chart.remove()
      }
      if (scene.current === s) scene.current = null
    }
  }, [mode, appMode, symbol, exchange, interval, username, darkOverride])

  useEffect(() => {
    const state = deltaTradingEnabled && deltaTradeState?.symbol === symbol ? deltaTradeState : null
    scene.current?.deltaOrders.update(state, deltaTradingEnabled)
  }, [deltaTradeState, deltaTradingEnabled, symbol, ready])

  useEffect(() => {
    setDeltaEditProposal(null)
    setDeltaCloseProposal(null)
    setDeltaTradeState(null)
  }, [symbol, exchange, deltaTradingEnabled])

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
  }, [
    ready,
    enabled,
    profile,
    referenceHistory.data,
    dailyPivotHistory.data,
    dailyPivotHistory.isError,
    probabilityStudy,
    videoResult,
    videoSelected,
    bookPreferences,
    bookScope,
    bookClock,
    strategy51Settings,
    strategy51Scope,
    strategy51Data.extras,
    strategy51Data.chain,
    history.isError,
    usingSnapshot,
    rangeLoading,
    rangeError,
    historyObservedAt,
    delta.connected,
    market.isConnected,
    displayedPatternEvents,
    showAllPatternHistory,
    showUnconfirmedPatterns,
    timeframePriceLevels,
    trendSetup,
    showNeutralPatterns,
    candlePattern,
    piyushMode,
    piyushReward,
    nineScope,
    nineUnderlying.data,
    nineUnderlying.isError,
    ninePremiumBars,
  ])
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
  const chartPlanReady =
    !usingSnapshot &&
    !history.isError &&
    !rangeLoading &&
    !rangeError &&
    !savedRange &&
    !replay &&
    !selectedRange &&
    history.data?.symbol === symbol &&
    history.data.exchange === exchange &&
    history.data.interval === interval &&
    !!history.data.candles.length
  const planningBars = useMemo(
    () =>
      history.data?.symbol === symbol &&
      history.data.exchange === exchange &&
      history.data.interval === interval &&
      !usingSnapshot
        ? verifiedCandleBars(
            history.data.candles,
            Math.min(historyObservedAt, Date.now() / 1000),
            replaySeconds(interval),
            ['NSE', 'BSE', 'NSE_INDEX', 'BSE_INDEX'].includes(exchange),
            resolvedContract?.session
          )
        : [],
    [
      history.data,
      historyObservedAt,
      symbol,
      exchange,
      interval,
      indian,
      usingSnapshot,
      resolvedContract?.session,
    ]
  )
  const frozenPreviewPlan = chartPlanReady && premiumPlanState?.scope === replayKey ? premiumPlanState.plan : null
  const guidePlan = useMemo<GuidePlan | null>(() => {
    if (!chartPlanReady) return null
    const direction = exchange === 'DELTA' && currentTrend.direction === 'down' ? 'short' : 'long'
    const fallback = calculateEntryPlan(planningBars, planningBars.at(-1)?.close ?? 0,
      resolvedContract?.tick_size ?? 0, direction, replaySeconds(interval), resolvedContract?.session ?? exchange !== 'DELTA').plan
    const p = frozenPreviewPlan ?? fallback
    return p ? { entry: p.entry, stop: p.stop, target: p.target, side: p.stop > p.entry ? 'sell' : 'buy',
      asOf: frozenPreviewPlan ? premiumPlanState?.observedAt ?? 0 : fallback?.asOf ?? 0,
      label: frozenPreviewPlan ? 'Your frozen chart plan' : `Chart planning levels · ${interval}`, protection: 'planned' } : null
  }, [chartPlanReady, frozenPreviewPlan, planningBars, resolvedContract?.tick_size, resolvedContract?.session, interval, exchange, currentTrend.direction, premiumPlanState?.observedAt])
  const scopedGuide = brokerGuide?.symbol === symbol && brokerGuide.exchange === exchange && chartPlanReady && Date.now() / 1000 - brokerGuide.asOf <= 10 ? brokerGuide : null
  const advisoryLevels = scopedGuide?.plan ? scopedGuide.plan.protection === 'planned' ? scopedGuide.plan : null : guidePlan
  const previewPlan = strategy51Clean ? null : frozenPreviewPlan ?? (fitted && advisoryLevels?.stop && advisoryLevels.target ? { entry: advisoryLevels.entry, stop: advisoryLevels.stop, target: advisoryLevels.target } : null)
  useEffect(() => {
    const s = scene.current
    if (
      !s ||
      combinedLevels?.symbol !== symbol ||
      combinedLevels.exchange !== exchange ||
      savedRange ||
      replay ||
      selectedRange ||
      usingSnapshot
    )
      return
    const lines = combinedLevels.levels.map((level) =>
      s.price.createPriceLine({
        ...level,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
      })
    )
    return () => {
      for (const line of lines) s.price.removePriceLine(line)
    }
  }, [ready, combinedLevels, symbol, exchange, savedRange, replay, selectedRange, usingSnapshot])
  useEffect(() => {
    const s = scene.current
    if (!s || !previewPlan) return
    const lines = [
      { price: previewPlan.entry, title: 'Entry (preview)', color: '#2962ff' },
      { price: previewPlan.stop, title: 'SL (preview)', color: '#ef5350' },
      { price: previewPlan.target, title: 'Target 1:2', color: '#26a69a' },
    ].map((level) =>
      s.price.createPriceLine({
        ...level,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
      })
    )
    return () => {
      for (const line of lines) s.price.removePriceLine(line)
    }
  }, [ready, previewPlan])
  useEffect(() => {
    const s = scene.current
    if (!s || !sourceId) return
    const lines = sourceReferences.map((level) =>
      s.price.createPriceLine({
        ...level,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
      })
    )
    s.sourceLines = lines
    return () => {
      for (const line of lines) if (s.sourceLines.includes(line)) s.price.removePriceLine(line)
      if (s.sourceLines === lines) s.sourceLines = []
    }
  }, [ready, sourceId, sourceReferences])
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
              market.data.get(`${exchange}:${symbol}`)?.data,
              resolvedContract?.session ?? undefined
            )
    const next = raw ? { ...raw, volume: raw.volume ?? 0 } : null
    if (!next || (previous && next.time < previous.time)) return
    if (previous?.time === next.time) bars.current[bars.current.length - 1] = next
    else bars.current.push(next)
    liveBar.current = next
    // Preserve every raw price in the candle, but coalesce history copies and
    // full study redraws. A burst must not rerun all studies for every packet.
    if (quoteWork.current == null)
      quoteWork.current = setTimeout(() => {
        quoteWork.current = null
        if (scene.current !== s) return
        publishLiveRef.current()
        if (!replayRef.current) drawRef.current(s)
      }, 150)
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
    s.emaOverlay.update(
      calculationBars.current,
      enabledRef.current.includes('ema-9-15'),
      shownBars.current.at(0)?.time ?? 0,
      shownBars.current.at(-1)?.time ?? 0,
      historyObservedAt - replaySeconds(interval),
      exchange === 'DELTA' ? replaySeconds(interval) : 0,
      historyObservedAt,
      replaySeconds(interval)
    )
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
    historyObservedAt,
  ])
  const candle = hover ?? last,
    timestamp = feedTimeMs(tick?.timestamp),
    age = timestamp ? Math.max(0, (Date.now() - timestamp) / 1000) : null
  const premiumChart = ['NFO', 'BFO'].includes(exchange) && /(?:CE|PE)$/.test(symbol)
  const premiumPreviousClose =
    premiumContract?.prev_close && premiumContract.prev_close > 0
      ? premiumContract.prev_close
      : tick && 'close' in tick
        ? tick.close
        : undefined
  const problems = [
    renderError,
    (history.error as Error)?.message,
    selectedRange ? (rangeHistory.error as Error)?.message : undefined,
    savedRange ? undefined : (info.error as Error)?.message,
  ].filter(Boolean)
  return (
    <section
      aria-label={`${title || symbol} TradingView chart`}
      className={`relative flex h-full ${fitted ? 'min-h-0' : 'min-h-[420px]'} overflow-hidden flex-col bg-background ${focusMode ? '' : 'rounded-md border'}`}
    >
      {piyushEligible && (focusMode || !compact) ? (
        <section
          aria-label="Research setups"
          className="relative z-20 flex shrink-0 flex-wrap items-center gap-2 border-b bg-background px-3 py-2 text-xs"
        >
          <strong>Research setups</strong>
          <span>Setup</span>
          <ResearchSetupPicker
            value={sourceId || piyushMode}
            onChange={chooseSetup}
            extraChoices={sourceChoices}
          />
          {!sourceId && <output aria-label="Target">Target 1:2</output>}
          <output aria-label="Study status" className="text-muted-foreground">
            {sourceId ? 'Strategy preview · no automatic trades' : piyushStatus}
          </output>
          {!sourceId && (
            <span className="text-muted-foreground">
              White entry · red SL · green target. Own chart prices · research signals.
            </span>
          )}
        </section>
      ) : null}
      {nineOn && nineChart.kind === 'option' ? (
        <div
          className="flex shrink-0 flex-wrap items-center gap-2 border-b px-3 py-1.5 text-xs"
          role="group"
          aria-label="Signal source controls"
        >
          <label>
            Signals{' '}
            <select
              aria-label="Signal price source"
              value={nineSource}
              onChange={(e) => setNineSource(e.target.value as IndicatorSource)}
              className="ml-1 rounded border bg-background px-2 py-1"
            >
              <option value="premium">Option premium · {nineChart.optionSide}</option>
              <option value="underlying">
                Underlying · {nineChart.underlying?.symbol ?? 'unavailable'}
              </option>
            </select>
          </label>
          <span className="text-muted-foreground">Closed candles · markers on {symbol}</span>
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
        <div
          role="region"
          aria-label="Chart plot area"
          className="relative flex min-h-0 min-w-0 flex-1 flex-col"
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
              {premiumChart && !replay && !savedRange && !selectedRange ? (
                <PremiumQuote
                  price={tick?.ltp ? Number(tick.ltp) : premiumContract?.ltp}
                  previousClose={premiumPreviousClose}
                  dark={darkOverride ?? (mode === 'dark' || appMode === 'analyzer')}
                  source={age != null && age <= 15 && market.isConnected ? 'Stream' : 'Last quote'}
                />
              ) : null}
              <section
                aria-label="Candle prices"
                className="flex flex-wrap gap-x-2 text-[11px] tabular-nums text-muted-foreground"
              >
                {candle ? (
                  <>
                    <span>O {candle.open.toFixed(2)}</span>
                    <span>H {candle.high.toFixed(2)}</span>
                    <span>L {candle.low.toFixed(2)}</span>
                    <span
                      className={candle.close >= candle.open ? 'text-emerald-500' : 'text-red-400'}
                    >
                      C {candle.close.toFixed(2)}
                    </span>
                  </>
                ) : (
                  <span>
                    {history.isPending || rangeLoading
                      ? 'Loading candles…'
                      : 'No candles available'}
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
                    <b className="font-medium">
                      {toolkitResult?.current.emaSlow?.toFixed(2) ?? '—'}
                    </b>
                  </span>
                </section>
              ) : null}
              {enabled.includes('bb-chikou') ? (
                <section aria-label="BB + Chikou study" className="text-[11px] text-violet-400">
                  BB + Chikou · 20 / 2 / 26 · closed candles · Target 1:2
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
                  {premiumChart && !replay && !savedRange && !selectedRange ? (
                    <PremiumQuote
                      price={tick?.ltp ? Number(tick.ltp) : premiumContract?.ltp}
                      previousClose={premiumPreviousClose}
                      dark={darkOverride ?? (mode === 'dark' || appMode === 'analyzer')}
                    />
                  ) : (
                    <strong className="tabular-nums">
                      {savedRange
                        ? last
                          ? `${exchange === 'DELTA' ? '$' : '₹'}${last.close.toFixed(2)}`
                          : 'No saved candles'
                        : tick?.ltp
                          ? `${exchange === 'DELTA' ? '$' : '₹'}${Number(tick.ltp).toFixed(2)}`
                          : 'Waiting for quote'}
                    </strong>
                  )}
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
                    <span
                      className={candle.close >= candle.open ? 'text-emerald-500' : 'text-red-400'}
                    >
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
                      {chartStudyLabel(id, label, exchange === 'DELTA')}
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
                    BB + Chikou · 20 / 2 / 26 · closed candles · Target 1:2
                  </span>
                ) : null}
                {enabled.includes('neo-toolkit') ? (
                  <>
                    <span className="text-blue-500">
                      EMA 9 · {toolkitResult?.current.ema9?.toFixed(2) ?? '—'}
                    </span>
                    <span className="text-amber-500">
                      EMA {toolkitSettings.slow} ·{' '}
                      {toolkitResult?.current.emaSlow?.toFixed(2) ?? '—'}
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
                {enabled.includes('volume') ? (
                  <span className="text-emerald-400">Volume</span>
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
          {patternsOn && (
            <output
              aria-label="Unified pattern indicator"
              className="absolute left-3 top-16 z-20 rounded bg-background/90 px-2 py-1 text-xs"
            >
              Pattern analysis · {showAllPatternHistory ? 'All history' : 'Last 10 candles'}
              {showUnconfirmedPatterns ? ' · Unconfirmed previews on' : ' · Confirmed only'}
            </output>
          )}
          {patternsOn && (
            <details className="absolute bottom-3 left-3 z-20 max-h-[45%] w-80 max-w-[90%] overflow-auto rounded border bg-background/95 px-3 py-2 text-xs shadow">
              <summary className="cursor-pointer font-medium">Pattern help</summary>
              <div className="space-y-2 pt-2 text-muted-foreground">
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={showAllPatternHistory}
                    onChange={(event) => setShowAllPatternHistory(event.target.checked)} />
                  Show all historical patterns
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={showUnconfirmedPatterns}
                    onChange={(event) => setShowUnconfirmedPatterns(event.target.checked)} />
                  Show unconfirmed patterns
                </label>
                <p>By default, confirmed labels appear only on the last 10 chart candles.
                  Older labels disappear as new candles arrive. Previews use completed candles
                  awaiting confirmation and do not change order eligibility.</p>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={showNeutralPatterns}
                    onChange={(event) => setShowNeutralPatterns(event.target.checked)}
                  />
                  Show neutral patterns
                </label>
                <p>
                  {exchange === 'DELTA'
                    ? 'EMA9/EMA15 sets Auto direction. Candlestick labels are optional chart information. A label on an older candle is history.'
                    : 'Read the latest closed-candle box first. WAIT means no fresh confirmed direction or conflicting patterns. A label on an older candle is history.'}
                </p>
                <ArchivePatternHelp crypto={exchange === 'DELTA'} />
                <p>
                  Green BULL means price may rise. Red BEAR means price may fall. Grey Doji or
                  Spinning Top means the direction is unclear.
                </p>
                <p>
                  Names appear on completed candles. A chart shape appears on the candle that closes
                  beyond its boundary.
                </p>
                <p>
                  These labels describe the price on this chart. On an option chart, they describe
                  the option premium.
                </p>
                <p>
                  The related images repeat many patterns. Their candle patterns and chart shapes
                  are combined here. Stars in an image are ratings, so they are not shown as
                  percentages.
                </p>
                <p>
                  SL = loss limit. TP = profit target. Support = an area where price has bounced up.
                  Resistance = an area where price has turned down. A higher timeframe shows the
                  bigger trend.
                </p>
                <p>
                  Time-of-day tips, glossaries and names with unclear rules stay as learning
                  references.
                </p>
                <div className="flex flex-wrap gap-3">
                  <a
                    className="underline"
                    href="https://in.pinterest.com/pin/980658887633372067/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Original image
                  </a>
                  <a
                    className="underline"
                    href="https://in.pinterest.com/pin/808677676886530128/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Candle guide
                  </a>
                  <a
                    className="underline"
                    href="https://in.pinterest.com/pin/1096837684277419345/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Trading terms
                  </a>
                </div>
              </div>
            </details>
          )}
          {probabilityOn ? (
            <details
              open={!compact || (!nineOn && !toolkitOn)}
              className="absolute bottom-16 left-3 z-20 max-h-[70%] w-[310px] max-w-[calc(100%_-_2rem)] overflow-auto rounded-md border bg-background/95 p-3 shadow-md sm:bottom-auto sm:top-16"
            >
              <summary className="cursor-pointer text-xs font-semibold focus-visible:outline focus-visible:outline-ring">
                Candlestick evidence
              </summary>
              <div className="pt-3">
                <label className="mb-3 flex items-center justify-between gap-2 text-xs">
                  Pattern setup
                  <select
                    aria-label="Pattern setup"
                    value={candlePattern}
                    onChange={(e) => setCandlePattern(e.target.value as PatternSelection)}
                    className="h-8 min-w-0 max-w-[190px] rounded-md border bg-background px-2 text-foreground"
                  >
                    {CANDLE_PATTERNS.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <CandlestickProbabilityPanel
                  study={probabilityStudy}
                  symbol={symbol}
                  exchange={exchange}
                  seconds={replaySeconds(interval)}
                  now={replay ? replay.until - 19800 : Math.max(probabilityNow, Date.now() / 1000)}
                  ready={
                    ((!!selectedRange && !savedRange) || (!usingSnapshot && !history.isError)) &&
                    !rangeError &&
                    !rangeLoading &&
                    !!probabilityStudy &&
                    (!!replay ||
                      !!savedRange ||
                      !!selectedRange ||
                      (exchange === 'DELTA' ? delta.connected : market.isConnected))
                  }
                  replay={!!replay || !!savedRange || !!selectedRange}
                  compact
                />
              </div>
            </details>
          ) : null}
          <div
            ref={host}
            className="relative min-h-0 flex-1"
            role="region"
            aria-label="TradingView candlesticks"
          />
          <ChartToolDock floating={fitted}>
            {sourceId && (
              <ChartToolPanel
                floating
                label="Strategy"
                title="Strategy settings"
                openToken={`${sourceScope}:${sourceId}:${sourceOpenCounter}`}
              >
                <ChartStrategyConfigurations
                  symbol={symbol}
                  exchange={exchange}
                  interval={interval}
                  tickSize={resolvedContract?.tick_size}
                  lotSize={premiumContract?.lotsize}
                  selectedId={sourceId}
                  onSelectedIdChange={chooseSetup}
                  onReferences={onSourceReferences}
                />
              </ChartToolPanel>
            )}

            <ChartEntryPlan
              key={`risk:${replayScope}`}
              symbol={symbol}
              exchange={exchange}
              interval={interval}
              scope={replayScope}
              bars={planningBars}
              ready={chartPlanReady}
              docked={fitted}
              contract={premiumContract}
              tickSize={resolvedContract?.tick_size}
              session={resolvedContract?.session ?? undefined}
              price={tick?.ltp ? Number(tick.ltp) : planningBars.at(-1)?.close}
              trendSource={
                nineChart.kind === 'option'
                  ? (nineChart.underlying ?? { symbol, exchange })
                  : { symbol, exchange }
              }
              loadTrend={readPlanTrend}
              onLevels={onPremiumPlan}
            />
            {['NFO', 'BFO'].includes(exchange) && /(?:CE|PE)$/.test(symbol) ? (
              <PremiumPriceAlerts
                docked={fitted}
                key={`${username}:${appMode}:${exchange}:${symbol}`}
                scope={`${username}:${appMode}:${exchange}:${symbol}`}
                symbol={symbol}
                quote={
                  tick ? { price: Number(tick.ltp), time: feedTimeMs(tick.timestamp) ?? NaN } : null
                }
                live={
                  !savedRange &&
                  !replay &&
                  !selectedRange &&
                  sessionEndDate === today &&
                  market.isConnected
                }
                levels={{
                  support:
                    !usingSnapshot &&
                    !history.isError &&
                    history.data?.symbol === symbol &&
                    history.data.exchange === exchange &&
                    history.data.interval === interval &&
                    toolkitOn
                      ? (toolkitResult?.zones.find((z) => !z.above)?.low ?? null)
                      : null,
                  resistance:
                    !usingSnapshot &&
                    !history.isError &&
                    history.data?.symbol === symbol &&
                    history.data.exchange === exchange &&
                    history.data.interval === interval &&
                    toolkitOn
                      ? (toolkitResult?.zones.find((z) => z.above)?.high ?? null)
                      : null,
                  entry: (() => {
                    const value = Number(
                      info.data?.overlays.find((line) => /entry|^buy\b/i.test(line.label))?.price
                    )
                    return Number.isFinite(value) && value > 0 ? value : premiumStudyEntry
                  })(),
                }}
              />
            ) : null}
            {nineOn || toolkitOn ? (
              <ChartToolPanel
                floating={fitted}
                defaultOpen={!focusMode}
                label="Chart signal details"
                title="Signals & details"
              >
                <div className="grid max-h-[30vh] min-w-0 gap-2 overflow-y-auto p-2 md:grid-cols-2">
                  {nineOn ? (
                    <NineIndicatorPanel
                      docked
                      result={nineResult}
                      enabled={enabled}
                      symbol={symbol}
                      exchange={exchange}
                      interval={interval}
                      seconds={replaySeconds(interval)}
                      asOf={nineAsOf.current}
                      priceBars={planningBars}
                      replay={!!replay || !!savedRange || !!selectedRange}
                      ready={
                        !usingSnapshot &&
                        !!history.data &&
                        !history.isError &&
                        (!useUnderlying || (!!nineUnderlying.data && !nineUnderlying.isError))
                      }
                      reference={optionReference}
                      source={nineSource}
                      onSourceChange={setNineSource}
                      onMfiProxy={onMfiProxy}
                    />
                  ) : null}
                  {toolkitOn ? (
                    <div className="min-w-0">
                      <ToolkitPanel
                        compact={focusMode}
                        historyReady={!usingSnapshot && !!history.data && !history.isError}
                        signalMarket={
                          exchange === 'DELTA'
                            ? 'perpetual'
                            : ['NSE_INDEX', 'BSE_INDEX'].includes(exchange)
                              ? 'index'
                              : nineChart.kind === 'option'
                                ? 'option'
                                : 'price'
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
                </div>
              </ChartToolPanel>
            ) : null}
            {problems.length ? (
              <div
                role="alert"
                className="flex shrink-0 items-center justify-between gap-2 border-t px-3 py-2 text-xs text-destructive"
              >
                <span>
                  {problems.join('; ')}
                  {(history.isError && canAutoRetryHistory(history.error)) ||
                  (selectedRange &&
                    rangeHistory.isError &&
                    canAutoRetryHistory(rangeHistory.error)) ? (
                    <span className="ml-1">Retrying automatically every 15 seconds.</span>
                  ) : null}
                </span>
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
              <ChartToolPanel
                floating={fitted}
                defaultOpen={!focusMode}
                label="History & replay"
                title="History & replay"
              >
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
                      !recentContext &&
                        range.start === istSessionDate() &&
                        range.end === range.start
                        ? null
                        : range
                    )
                  }
                  loading={rangeLoading}
                  unavailable={rangeError}
                />
              </ChartToolPanel>
            )}
          </ChartToolDock>
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t px-3 py-1 text-[11px] text-muted-foreground">
            <span>
              {savedRange
                ? `SQL saved history · ${savedRange.start} → ${savedRange.end}`
                : (exchange === 'DELTA' ? delta.connected : market.isConnected)
                  ? 'Feed connected'
                  : 'Feed disconnected'}
              {age != null ? ` · last quote ${age.toFixed(0)}s ago` : ''} ·{' '}
              {shownBars.current.length} candles · IST
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
        </div>
        {(patternsOn || fitted || videoGuideOn || bookGuideOn || strategy51On) && (
          <aside
            aria-label="Latest pattern reading"
            className={`max-h-40 w-full shrink-0 overflow-y-auto border-t bg-background text-xs lg:max-h-none lg:border-l lg:border-t-0 ${trendPanelOpen ? 'px-2 py-2 lg:w-56' : 'p-1 lg:w-9'}`}
          >
            <div className="mb-1 flex items-center justify-between gap-1">
              {trendPanelOpen && <strong className="text-[11px]">Trend &amp; setup</strong>}
              <button
                type="button"
                onClick={toggleTrendPanel}
                aria-expanded={trendPanelOpen}
                aria-controls={trendPanelId}
                aria-label={trendPanelOpen ? 'Collapse trend panel' : 'Expand trend panel'}
                title={trendPanelOpen ? 'Collapse trend panel' : 'Expand trend panel'}
                className="flex h-7 min-w-7 items-center justify-center rounded border text-base hover:bg-muted focus-visible:outline focus-visible:outline-2"
              >
                {trendPanelOpen ? '›' : '‹'}
              </button>
              {!trendPanelOpen && <span className="text-[11px] lg:hidden">Trend &amp; setup</span>}
            </div>
            <div id={trendPanelId} hidden={!trendPanelOpen}>
              {strategy51On && <Strategy51Guide key={`strategy51:${strategy51Scope}`} result={strategy51State?.scope===strategy51Scope?strategy51State.result:null} settings={strategy51Settings} onChange={change=>setStrategy51Settings(old=>normalizeStrategy51Settings({...old,...change}))} symbol={symbol} exchange={exchange} seconds={replaySeconds(interval)} />}
              {!strategy51Clean && <>
              {bookGuideOn && <BookPatternGuide key={bookScope}
                result={bookState?.scope === bookScope ? bookState.result : null}
                context={bookState?.scope === bookScope ? bookState.context : null}
                settings={bookPreferences.settings} instrument={bookInstrument}
                onSettingsChange={change => setBookPreferences(old => normalizeBookPreferences({...old,settings:{...old.settings,...change}}))}
                onInstrumentChange={change => setBookPreferences(old => normalizeBookPreferences({...old,instrumentScope:bookInstrumentScope,instrument:{...bookInstrumentForScope(old,bookInstrumentScope),...change}}))}
              />}
              {patternsOn && <LivePatternGuide key={`patterns:${videoScope}`} events={relatedEvents}
                bars={probabilityStudy?.bars ?? []} seconds={replaySeconds(interval)}
                asOf={selectedRange && !savedRange ? (rangeHistory.data?.observedAt ?? 0) : historyObservedAt}
                live={chartPlanReady && !savedRange && !selectedRange && !replay}
                candle={last} observedAt={timestamp ? timestamp / 1000 : null} symbol={symbol} exchange={exchange} session={resolvedContract?.session} />}
              {videoGuideOn && <VideoStrategyGuide key={videoScope} result={videoResult} selectedId={videoSelected}
                onSelect={id => setVideoChoice({scope:videoScope,id})} symbol={symbol} exchange={exchange} interval={interval}
                live={chartPlanReady && !savedRange && !selectedRange && !replay} />}
              <TradeGuide key={`${username}:${appMode}:${exchange}:${symbol}`} symbol={symbol} exchange={exchange}
                interval={interval} seconds={replaySeconds(interval)} live={chartPlanReady}
                current={currentTrend} higher={higherTrend} higherInterval={higherInterval}
                plan={guidePlan} tick={resolvedContract?.tick_size ?? 0} lotSize={premiumContract?.lotsize ?? resolvedContract?.lotsize}
                quote={tick && feedTimeMs(tick.timestamp) ? { price: Number(tick.ltp), time: feedTimeMs(tick.timestamp)! / 1000 } : null}
                context={brokerGuide} />
              <section aria-label="Trend analysis" className="mb-2 border-b pb-2">
                <strong
                  className={
                    combinedTrend.direction === 'up'
                      ? 'text-emerald-400'
                      : combinedTrend.direction === 'down'
                        ? 'text-red-400'
                        : 'text-muted-foreground'
                  }
                >
                  Trend: {trendSummaryLabel(currentTrend, higherTrend, liveTrendSource)}{exchange === 'DELTA' ? ' · EMA 9/15' : ''}
                </strong>
                <div className="mt-1">
                  {interval}: {currentTrend.label} ·{' '}
                  {higherInterval
                    ? `${higherInterval}: ${!liveTrendSource ? 'Off in history' : (higherTrend?.label ?? 'Checking candles')}`
                    : 'No higher timeframe'}
                </div>
                {!combinedTrend.aligned && liveTrendSource && (
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    {currentTrend.direction === 'up' || currentTrend.direction === 'down'
                      ? `${higherInterval}: ${higherTrend?.reason ?? 'Checking the higher timeframe.'}`
                      : currentTrend.reason}
                  </p>
                )}
                <details className="mt-1 text-[10px] text-muted-foreground">
                  <summary className="cursor-pointer">Why this trend?</summary>
                  <div className="mt-1 text-[10px] text-muted-foreground">
                    {replay
                      ? 'Higher timeframe is off in replay'
                      : selectedRange || savedRange
                        ? 'Higher timeframe is off for saved dates'
                        : combinedTrend.aligned
                          ? 'Trend agrees'
                          : combinedTrend.reason}
                  </div>

                  <p>{currentTrend.reason}</p>
                  {higherTrend && (
                    <p>
                      {higherInterval}: {higherTrend.reason}
                    </p>
                  )}
                  <p>
                    {exchange === 'DELTA' ? 'Uses completed candles and our backend EMA9/EMA15 direction. Candlestick patterns are optional.' : 'Uses closed candles, 20 / 50 moving averages and confirmed price swings.'} Green
                    line: support. Red line: resistance. Blue dashed line: breakout boundary.
                  </p>
                </details>
              </section>
              <details
                open
                className="mb-2 border-b pb-2"
                aria-label="Support and timeframe levels"
              >
                <summary className="cursor-pointer font-semibold text-[11px]">Levels</summary>
                <dl className="mt-1 grid grid-cols-2 gap-x-2 gap-y-1 text-[10px] tabular-nums">
                  <dt className="text-emerald-400">SUPPORT</dt>
                  <dd className="text-right">
                    {swingPriceLevels.support?.toLocaleString('en-IN', {
                      maximumFractionDigits: 2,
                    }) ?? '—'}
                  </dd>
                  <dt className="text-red-400">RESISTANCE</dt>
                  <dd className="text-right">
                    {swingPriceLevels.resistance?.toLocaleString('en-IN', {
                      maximumFractionDigits: 2,
                    }) ?? '—'}
                  </dd>
                  {timeframePriceLevels.map((level) => (
                    <Fragment key={level.title}>
                      <dt style={{ color: level.color }}>{level.title}</dt>
                      <dd className="text-right">
                        {level.price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                      </dd>
                    </Fragment>
                  ))}
                </dl>
                {timeframePriceLevels.length > 0 && (
                  <p className="mt-1 text-[9px] text-muted-foreground">
                    Previous completed 1H / 4H candles · UTC boundaries
                  </p>
                )}
              </details>
              <section aria-label="Trend breakout setup" className="mb-2 border-b pb-2">
                <strong
                  className={
                    trendSetupAligned
                      ? trendSetup?.side === 'CALL'
                        ? 'text-emerald-400'
                        : 'text-red-400'
                      : 'text-muted-foreground'
                  }
                >
                  {trendSetupAligned
                    ? trendSetup?.side === 'CALL'
                      ? 'BULL · Upward setup'
                      : 'BEAR · Downward setup'
                    : exchange === 'DELTA' ? 'Chart shape · optional' : 'WAIT'}
                </strong>
                {trendSetup ? (
                  <details
                    key={`${trendSetup.time}:${trendSetup.status}`}
                    open={trendSetup.status === 'active'}
                    className="mt-1"
                  >
                    <summary className="cursor-pointer">
                      {trendSetup.name} · {trendSetup.status.replaceAll('-', ' ')}
                    </summary>
                    <div className="mt-1 text-[10px] text-muted-foreground">
                      Confirmed{' '}
                      {new Date(trendSetup.time * 1000).toLocaleString('en-IN', {
                        timeZone: 'Asia/Kolkata',
                        day: '2-digit',
                        month: 'short',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}{' '}
                      IST · Reward / risk {trendSetup.rewardRisk.toFixed(2)}
                    </div>
                    <div className="mt-1">
                      Entry {trendSetup.entry.toLocaleString('en-IN', { maximumFractionDigits: 4 })}{' '}
                      · Stop {trendSetup.stop.toLocaleString('en-IN', { maximumFractionDigits: 4 })}{' '}
                      · Target{' '}
                      {trendSetup.target.toLocaleString('en-IN', { maximumFractionDigits: 4 })}
                    </div>
                    <div className="mt-1 text-[10px] text-muted-foreground">
                      {trendSetup.status !== 'active'
                        ? trendSetup.reason
                        : trendSetupAligned
                          ? 'Breakout confirmed. Trend agrees.'
                          : 'Pattern confirmed; wait for both trends to agree.'}{' '}
                      Levels mark the confirmed breakout, not a new entry at any price. Target is an
                      estimate.
                    </div>
                  </details>
                ) : (
                  <div className="mt-1 text-[10px] text-muted-foreground">
                    Waiting for a chart pattern to close beyond its boundary.
                  </div>
                )}
              </section>
              {patternsOn && (
                <>
                  {latestPatternMatches.length > 1 && (
                    <details aria-label="Distinct candle patterns" className="mb-2 border-b pb-2">
                      <summary className="cursor-pointer">
                        All patterns on this candle ({latestPatternMatches.length})
                      </summary>
                      <ul className="mt-1 space-y-1">
                        {latestPatternMatches.map((match) => (
                          <li
                            key={`${match.side}:${match.name}`}
                            className={
                              match.side === 'CALL'
                                ? 'text-emerald-400'
                                : match.side === 'PUT'
                                  ? 'text-red-400'
                                  : 'text-muted-foreground'
                            }
                          >
                            {match.name.replace(/^(Bullish|Bearish|Bull|Bear)\s+/i, '')}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  <strong
                    className={
                      archiveReading.side === 'BULL'
                        ? 'text-emerald-400'
                        : archiveReading.side === 'BEAR'
                          ? 'text-red-400'
                          : 'text-muted-foreground'
                    }
                  >
                    {exchange === 'DELTA' ? (archiveReading.side === 'WAIT' ? 'Candle pattern' : `Candle pattern · ${archiveReading.side}`) : archiveReading.side} ·{' '}
                    {archiveReading.name
                      .replace(/^No fresh confirmed pattern$/, exchange === 'DELTA' ? 'None on this candle' : 'No fresh confirmed pattern')
                      .replace(/^(Bullish|Bearish)\s+/i, '')
                      .replace(/\s+\(operational(?: re-entry)?\)/g, '')}
                  </strong>
                  {exchange === 'DELTA' && <p className="mt-1 text-[10px] text-muted-foreground">Candlestick patterns are optional; EMA confirmation sets Auto direction.</p>}
                  <div className="mt-1 text-[10px] text-muted-foreground">
                    Latest closed candle
                    {archiveReading.time
                      ? ` · ${new Date(archiveReading.time * 1000).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })} IST`
                      : ''}
                  </div>
                  {archiveReading.invalid !== null && (
                    <div className="mt-1">
                      Invalid {archiveReading.side === 'BULL' ? 'below' : 'above'}{' '}
                      {archiveReading.invalid.toLocaleString('en-IN', { maximumFractionDigits: 4 })}
                    </div>
                  )}
                </>
              )}
              </>}
            </div>
          </aside>
        )}
        <CombinedChartPanel symbol={symbol} exchange={exchange} onLevels={setCombinedLevels} onGuidance={setBrokerGuide} />
        {exchange === 'DELTA' && (
          <DeltaTradePanel
            key={`${username}:${symbol}`}
            symbol={symbol}
            enabled={deltaTradingEnabled}
            riskContext={scalpRiskContext}
            chartRiskContext={deltaRiskContext}
            executionMode={DELTA_SCALP_STRATEGY}
            onState={setDeltaTradeState}
            onGuidance={setBrokerGuide}
            closeProposal={deltaCloseProposal}
            onCloseProposalHandled={clearDeltaClose}
            editProposal={deltaEditProposal}
            onProposalHandled={clearDeltaProposal}
          />
        )}
      </div>
    </section>
  )
}
