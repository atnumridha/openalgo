import type { PlanBar } from '../neo-desk/chartTradePlan'
import { deltaOiSignal, readDeltaOpenInterest } from '../neo-desk/deltaOpenInterest'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { apiClient, webClient } from '@/api/client'
import { scalpingApi } from '@/api/scalping'
import { activeExpiries, expiryDate, nearestExpiry } from '@/lib/neoOptionSelection'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import type { OptionChainResponse } from '@/types/option-chain'
import { chartBars } from '../neo-desk/tradingViewStudies'
import { closeTime } from './model'
import { indicatorVote } from './indicatorVote'
import {
  INDICATORS,
  NineIndicatorEngine,
  type IndicatorKey,
  type IndicatorState,
  type NineResult,
} from './nineIndicators'
import {
  ivComparison,
  normalizeFeedExpiry,
  optionContextStates,
  volumePCR,
  type OptionSignalSnapshot,
} from './optionSignalContext'
import type { OptionReference } from './ToolkitPanel'
import {
  indicatorAction,
  resolveIndicatorChart,
  type IndicatorSource,
} from './indicatorChartContext'

const label = (state: Pick<IndicatorState, 'side'>) =>
  state.side === 'CALL' ? 'BUY CALL' : state.side === 'PUT' ? 'BUY PUT' : 'WAIT'
const stamp = (time: number | null, withSeconds = false) =>
  time == null
    ? ''
    : new Date(time * 1000).toLocaleString('en-IN', {
        timeZone: 'Asia/Kolkata',
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
        ...(withSeconds ? { second: '2-digit' as const } : {}),
        hour12: false,
      })
const stateTone = (state: Pick<IndicatorState, 'side'>) =>
  state.side === 'CALL'
    ? 'text-emerald-400'
    : state.side === 'PUT'
      ? 'text-red-400'
      : 'text-yellow-300'
const dashboardTone = (state: Pick<IndicatorState, 'side'>) =>
  state.side === 'CALL'
    ? 'text-emerald-700 dark:text-emerald-400'
    : state.side === 'PUT'
      ? 'text-red-700 dark:text-red-400'
      : 'text-yellow-700 dark:text-yellow-300'
const dashboardBadge = (state: Pick<IndicatorState, 'side'>) =>
  `${dashboardTone(state)} ${state.side === 'CALL' ? 'bg-emerald-50 dark:bg-emerald-950/40' : state.side === 'PUT' ? 'bg-red-50 dark:bg-red-950/40' : 'bg-yellow-50 dark:bg-yellow-950/40'}`
const expiryInstant = (expiry: string) => {
  const date = expiryDate(expiry)
  return date ? Date.parse(`${date}T15:30:00+05:30`) / 1000 : NaN
}

export function NineIndicatorPanel({
  result,
  enabled,
  symbol,
  exchange,
  interval,
  seconds,
  asOf,
  priceBars,
  replay,
  ready,
  embedded = false,
  docked = false,
  reference,
  onMfiProxy,
  liveValues,
  liveValueTime,
  source = 'underlying',
  onSourceChange,
}: {
  result: NineResult | null
  enabled: string[]
  symbol: string
  exchange: string
  interval: string
  seconds: number
  asOf: number
  priceBars?: readonly PlanBar[]
  replay: boolean
  ready: boolean
  embedded?: boolean
  docked?: boolean
  reference?: OptionReference
  onMfiProxy: (result: NineResult | null) => void
  liveValues?: Partial<Record<IndicatorKey, number | null>>
  liveValueTime?: number
  source?: IndicatorSource
  onSourceChange?: (source: IndicatorSource) => void
}) {
  const username = useAuthStore((s) => s.user?.username)
  const apiKey = useAuthStore((s) => s.apiKey)
  const mode = useThemeStore((s) => s.appMode)
  const [now, setNow] = useState(() => Date.now() / 1000)
  const [observations, setObservations] = useState<OptionSignalSnapshot[]>([])
  const chart = resolveIndicatorChart(symbol, exchange, reference)
  const crypto = exchange === 'DELTA'
  const eligible = !!chart.underlying
  const contextSymbol = chart.underlying?.symbol ?? symbol
  const contextExchange = chart.underlying?.exchange ?? exchange
  const premiumMode = chart.kind === 'option' && source === 'premium'
  const action = (state: Pick<IndicatorState, 'side'> & { key?: IndicatorKey }) =>
    indicatorAction(state.side, chart, source, state.key)
  const rowLabel = (state: IndicatorState) => action(state).label
  const rowReason = (state: IndicatorState) =>
    state.reason
      .replaceAll('BUY CALL', indicatorAction('CALL', chart, source, state.key).label)
      .replaceAll('BUY PUT', indicatorAction('PUT', chart, source, state.key).label)
  const priceEligible = chart.kind !== 'option' || premiumMode || eligible
  const live = eligible && !replay
  const derivativesExchange =
    contextExchange === 'BSE_INDEX' || contextExchange === 'BSE' ? 'BFO' : 'NFO'
  const selected = INDICATORS.filter((item) => enabled.includes(item.id))
  const nativeMfi = result?.states.find((s) => s.key === 'mfi')
  const needProxy =
    enabled.includes('nine-mfi') &&
    nativeMfi?.value == null &&
    !premiumMode &&
    ['NSE_INDEX', 'BSE_INDEX'].includes(contextExchange)
  const needIV = enabled.includes('nine-iv'),
    needPCR = enabled.includes('nine-pcr'),
    needOI = enabled.includes('nine-oi')
  const cryptoOi = useQuery({
    queryKey: ['delta-indicator-oi', username, mode, symbol, interval],
    enabled: crypto && needOI && ready && !replay,
    queryFn: ({ signal }) => readDeltaOpenInterest(symbol, interval, signal),
    staleTime: 20000,
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: crypto && needOI && ready && !replay ? 30000 : false,
  })
  const needsData = live && (needIV || needPCR || needOI || needProxy)
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 5000)
    return () => window.clearInterval(timer)
  }, [])
  const metadata = useQuery({
    queryKey: ['nine-indicator-metadata', username, mode, contextSymbol, derivativesExchange],
    enabled: needsData,
    queryFn: async () => {
      const [expiries, futures] = await Promise.allSettled([
        scalpingApi.getExpiry(contextSymbol, derivativesExchange, 'options'),
        scalpingApi.futures(contextSymbol, derivativesExchange),
      ])
      const expiry =
        expiries.status === 'fulfilled'
          ? nearestExpiry(activeExpiries(expiries.value.data ?? []))
          : ''
      const rows = futures.status === 'fulfilled' ? (futures.value.data ?? []) : []
      const futureExpiry = nearestExpiry(
        activeExpiries(rows.map((row) => normalizeFeedExpiry(row.expiry)))
      )
      return {
        expiry,
        future: rows.find((row) => normalizeFeedExpiry(row.expiry) === futureExpiry),
      }
    },
    staleTime: 60000,
    refetchInterval: needsData ? 60000 : false,
    retry: false,
  })
  const scopedReference = chart.reference
  const expiry = chart.expiry || scopedReference?.expiry || metadata.data?.expiry || ''
  const future = metadata.data?.future
  const identity = [
    username,
    mode,
    symbol,
    exchange,
    contextSymbol,
    contextExchange,
    source,
    expiry,
    scopedReference?.ce?.symbol,
    scopedReference?.pe?.symbol,
    future?.symbol,
  ].join(':')
  const oiData = useQuery({
    queryKey: ['nine-futures-oi', identity],
    enabled: live && needOI && !!future && !!apiKey,
    queryFn: async () => {
      const response = await apiClient.post<{
        status: string
        data?: { ltp?: number; oi?: number }
      }>(
        '/quotes',
        { apikey: apiKey, symbol: future!.symbol, exchange: derivativesExchange },
        { timeout: 12000 }
      )
      const observedAt = Date.now() / 1000
      const quote = response.data.status === 'success' ? response.data.data : null
      const snapshot: OptionSignalSnapshot = {
        identity,
        observedAt,
        futureObservedAt: observedAt,
        pcr: null,
        ceIV: null,
        peIV: null,
        future:
          quote && Number.isFinite(quote.ltp) && Number.isFinite(quote.oi)
            ? { symbol: future!.symbol, price: quote.ltp!, oi: quote.oi! }
            : null,
      }
      return { snapshot }
    },
    staleTime: embedded ? 4000 : 20000,
    refetchInterval: live && needOI ? (embedded ? 5000 : 30000) : false,
    retry: false,
  })
  const proxyData = useQuery({
    queryKey: ['nine-futures-mfi', identity, interval],
    enabled: live && needProxy && !!future,
    queryFn: async () => {
      const response = await scalpingApi.getHistory(
        future!.symbol,
        derivativesExchange,
        interval,
        undefined,
        { timeoutMs: 60000 }
      )
      return {
        identity,
        observedAt: Date.now() / 1000,
        bars: response.status === 'success' ? chartBars(response.candles) : [],
      }
    },
    staleTime: 20000,
    refetchInterval: live && needProxy ? 30000 : false,
    retry: false,
  })
  const chainData = useQuery({
    queryKey: ['nine-option-chain', identity],
    enabled: live && (needIV || needPCR) && !!expiry,
    queryFn: async () => {
      const response = await webClient.get<OptionChainResponse>('/scalping/api/strikes', {
        params: {
          underlying: contextSymbol,
          exchange: derivativesExchange,
          expiry,
          strike_count: 5,
          quotes: true,
        },
        timeout: 30000,
      })
      return {
        identity,
        observedAt: Date.now() / 1000,
        chain: response.data.status === 'success' ? response.data : null,
        diagnostics:
          response.data.status === 'success'
            ? []
            : [response.data.message || 'Broker chain quotes unavailable'],
      }
    },
    staleTime: embedded && needPCR ? 4000 : 20000,
    refetchInterval: live && (needIV || needPCR) ? (embedded && needPCR ? 5000 : 30000) : false,
    retry: false,
  })
  const chain = chainData.data?.identity === identity ? chainData.data.chain : null
  const atm = chain?.chain.find((row) => row.strike === chain.atm_strike)
  const ce =
    scopedReference?.ce ?? (atm?.ce ? { symbol: atm.ce.symbol, strike: atm.strike } : undefined)
  const pe =
    scopedReference?.pe ?? (atm?.pe ? { symbol: atm.pe.symbol, strike: atm.strike } : undefined)
  const historyDay = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(Date.now()))
  const data = useQuery({
    queryKey: ['nine-option-signals', identity, ce?.symbol, pe?.symbol, historyDay],
    enabled: live && needIV && !!expiry && !!ce && !!pe,
    queryFn: async () => {
      const responseTimes: number[] = []
      const readIVHistory = async (contract: string, venue: string, date?: string) => {
        const response = await scalpingApi.getHistory(contract, venue, '1m', date, {
          timeoutMs: 30000,
        })
        responseTimes.push(Date.now() / 1000)
        return response
      }
      // Kotak's date-only index history can return no candles. Its recent-history
      // route includes today's index candles; option legs can stay date-limited.
      const [spotHistory, ceHistory, peHistory] = await Promise.allSettled([
        needIV ? readIVHistory(contextSymbol, contextExchange) : Promise.resolve(null),
        needIV && ce
          ? readIVHistory(ce.symbol, derivativesExchange, historyDay)
          : Promise.resolve(null),
        needIV && pe
          ? readIVHistory(pe.symbol, derivativesExchange, historyDay)
          : Promise.resolve(null),
      ])
      const diagnostics: string[] = []
      for (const response of [spotHistory, ceHistory, peHistory]) {
        if (response.status === 'rejected')
          diagnostics.push('A matched 1m history request failed or timed out')
      }
      const observedAt = Date.now() / 1000
      const verifiedAt = Math.min(...responseTimes)
      const bars = (response: typeof spotHistory) =>
        response.status === 'fulfilled' && response.value?.status === 'success'
          ? chartBars(response.value.candles)
          : []
      const spotBars = bars(spotHistory),
        ceBars = bars(ceHistory),
        peBars = bars(peHistory),
        ceTimes = new Set(ceBars.map((bar) => bar.time)),
        peTimes = new Set(peBars.map((bar) => bar.time)),
        commonTimes = new Set(
          spotBars
            .filter((bar) => ceTimes.has(bar.time) && peTimes.has(bar.time))
            .map((bar) => bar.time)
        ),
        spot = spotBars.filter((bar) => commonTimes.has(bar.time)),
        expires = expiryInstant(expiry)
      const snapshot: OptionSignalSnapshot = {
        identity,
        observedAt,
        expiry: expires,
        pcr: null,
        ceIV: ce
          ? ivComparison(
              ceBars.filter((bar) => commonTimes.has(bar.time)),
              spot,
              expires,
              ce.strike,
              true,
              verifiedAt
            )
          : null,
        peIV: pe
          ? ivComparison(
              peBars.filter((bar) => commonTimes.has(bar.time)),
              spot,
              expires,
              pe.strike,
              false,
              verifiedAt
            )
          : null,
        future: null,
      }
      // A failed poll must not overwrite a still-fresh verified comparison.
      // The pure evaluator continues to enforce the original source timestamps.
      if (!snapshot.ceIV || !snapshot.peIV || snapshot.ceIV.time !== snapshot.peIV.time)
        throw Error('Kotak IV history is delayed or incomplete; awaiting matched closed minutes')
      return {
        snapshot,
        diagnostics: [...new Set(diagnostics)],
      }
    },
    staleTime: 20000,
    refetchInterval: live && needIV ? 30000 : false,
    retry: false,
  })
  useEffect(() => {
    const snapshot = oiData.data?.snapshot
    if (!snapshot || snapshot.identity !== identity || !live) return
    setObservations((old) => {
      const scoped = old.filter((s) => s.identity === identity)
      const latest = scoped.at(-1)
      if (latest && snapshot.observedAt <= latest.observedAt) return old
      // Faster dashboard quotes are numeric previews. The OI direction still
      // compares observations at least 30 seconds apart.
      if (embedded && latest && snapshot.observedAt - latest.observedAt < 30) return old
      return [...scoped, snapshot].slice(-2)
    })
  }, [oiData.data, identity, live, embedded])
  const proxyEngine = useMemo(() => new NineIndicatorEngine(), [identity, interval])
  // Minute cadence stabilizes memoization without moving 09:15-anchored closes
  // to UTC hourly buckets. The engine owns Indian session-close semantics.
  const proxyAsOf = Math.floor((proxyData.data?.observedAt ?? 0) / 60) * 60
  const proxyCandidate = useMemo(
    () =>
      live && needProxy && proxyData.data?.identity === identity && proxyData.data.bars.length
        ? proxyEngine.update(proxyData.data.bars, { seconds, asOf: proxyAsOf, indian: true })
        : null,
    [proxyData.data, identity, live, needProxy, proxyEngine, seconds, proxyAsOf]
  )
  const wallTime = Math.max(now, Date.now() / 1000)
  const lastIndexClose =
    result?.lastTime == null
      ? NaN
      : closeTime(
          { time: result.lastTime, open: 0, high: 0, low: 0, close: 0, volume: 0 },
          seconds,
          ['NSE', 'NSE_INDEX', 'NFO', 'BSE', 'BSE_INDEX', 'BFO'].includes(exchange)
        )
  const freshIndex =
    Number.isFinite(lastIndexClose) &&
    lastIndexClose <= wallTime &&
    wallTime - lastIndexClose <= seconds + 180
  const snapshotAge = wallTime - (proxyData.data?.observedAt ?? -Infinity)
  const proxyClose =
    proxyCandidate?.lastTime == null
      ? NaN
      : closeTime(
          { time: proxyCandidate.lastTime, open: 0, high: 0, low: 0, close: 0, volume: 0 },
          seconds,
          true
        )
  const proxyResult =
    proxyClose <= wallTime &&
    wallTime - proxyClose <= seconds + 180 &&
    snapshotAge >= 0 &&
    snapshotAge <= 90 &&
    proxyCandidate
      ? proxyCandidate
      : null
  useEffect(() => {
    onMfiProxy(proxyResult)
  }, [proxyResult, onMfiProxy])
  const latestOi = oiData.data?.snapshot.identity === identity ? oiData.data.snapshot : undefined
  const confirmedOi = embedded
    ? observations.filter((snapshot) => snapshot.identity === identity).at(-1)
    : latestOi
  const current = useMemo(() => {
    const options = data.data?.snapshot.identity === identity ? data.data.snapshot : undefined
    const oi = confirmedOi
    const pcr = chainData.data?.identity === identity ? chainData.data : undefined
    if (!options && !oi && !pcr) return undefined
    return {
      identity,
      observedAt: Math.max(options?.observedAt ?? 0, oi?.observedAt ?? 0, pcr?.observedAt ?? 0),
      expiry: expiryInstant(expiry),
      pcr: pcr?.chain ? volumePCR(pcr.chain.chain) : null,
      pcrObservedAt: pcr?.observedAt,
      ceIV: options?.ceIV ?? null,
      peIV: options?.peIV ?? null,
      future: oi?.future ?? null,
      futureObservedAt: oi?.futureObservedAt,
    }
  }, [data.data, confirmedOi, chainData.data, identity, expiry])
  const previous = observations
    .filter((s) => s.identity === identity && s.observedAt < (current?.futureObservedAt ?? 0))
    .at(-1)
  const contextStates = live ? optionContextStates(current, previous, identity, wallTime) : []
  const proxyMfi = proxyResult?.states.find((s) => s.key === 'mfi')
  const freshLiveValues =
    embedded &&
    live &&
    liveValueTime != null &&
    Number.isFinite(liveValueTime) &&
    liveValueTime <= wallTime &&
    wallTime - liveValueTime <= 15
  const freshOiValue =
    live &&
    latestOi != null &&
    latestOi.observedAt <= wallTime &&
    wallTime - latestOi.observedAt <= 90 &&
    latestOi.future != null &&
    Number.isFinite(latestOi.future.oi) &&
    latestOi.future.oi > 0
  const states = selected.map((item) => {
    const context = ['iv', 'pcr', 'oi'].includes(item.key)
    let state = context
      ? contextStates.find((s) => s.key === item.key)
      : result?.states.find((s) => s.key === item.key)
    if (item.key === 'mfi' && nativeMfi?.value == null && proxyMfi)
      state = {
        ...proxyMfi,
        reason: `${future?.symbol} futures-volume proxy · ${proxyMfi.reason}`,
      }
    if (!state)
      state = {
        key: item.key,
        value: null,
        side: 'WAIT',
        time: null,
        reason: context ? 'Waiting for fresh option data' : 'Waiting for completed candles',
      }
    if ((context && (!eligible || replay)) || (!context && !priceEligible))
      state = {
        ...state,
        side: 'WAIT',
        reason: !eligible
          ? 'Underlying not identified; select Option premium for price indicators'
          : 'Live options context is unavailable in replay',
        time: null,
        value: null,
      }
    if (crypto && context) {
      state =
        item.key === 'oi' && ready && !replay
          ? deltaOiSignal(
              cryptoOi.isError ? undefined : cryptoOi.data,
              priceBars ?? [],
              seconds,
              asOf,
              wallTime
            )
          : {
              key: item.key,
              side: 'WAIT',
              value: null,
              time: null,
              reason: replay
                ? 'Live crypto context is unavailable in replay'
                : item.key === 'oi'
                  ? 'Waiting for verified crypto candles'
                  : `${item.short} is not applicable to this perpetual; it requires an options contract / chain`,
            }
    }
    const usesProxy = item.key === 'mfi' && nativeMfi?.value == null && proxyMfi != null
    const preview = liveValues?.[item.key]
    const hasPreview =
      freshLiveValues && !context && preview !== undefined && !(usesProxy && preview == null)
    const value = hasPreview
      ? preview != null && Number.isFinite(preview)
        ? preview
        : null
      : embedded && item.key === 'oi' && live
        ? freshOiValue
          ? latestOi!.future!.oi
          : null
        : state.value
    const valueSource = hasPreview
      ? value == null
        ? 'Live unavailable'
        : 'Live'
      : crypto && item.key === 'oi'
        ? 'Closed Delta candle'
        : item.key === 'iv'
          ? 'Closed 1m candles'
          : item.key === 'oi' || item.key === 'pcr'
            ? value == null
              ? 'Awaiting quotes'
              : `Observed · ${embedded ? 5 : 30}s`
            : usesProxy
              ? 'Futures candle'
              : 'Closed candle'
    const valueTime = hasPreview
      ? liveValueTime!
      : item.key === 'oi' && freshOiValue
        ? latestOi!.observedAt
        : context
          ? state.time
          : usesProxy
            ? proxyClose
            : lastIndexClose
    return { item, state, context, value, valueSource, valueTime }
  })
  const vote = indicatorVote(
    states.map(({ item, state, context }) =>
      context || (ready && freshIndex) || (item.key === 'mfi' && proxyResult)
        ? action(state).side
        : 'WAIT'
    )
  )
  const overallLabel =
    chart.kind === 'option'
      ? vote.side === 'WAIT'
        ? 'WAIT'
        : `${vote.side === 'CALL' ? 'BUY' : 'AVOID'} ${chart.optionSide}`
      : chart.kind === 'index'
        ? label(vote)
        : vote.side === 'WAIT'
          ? 'WAIT'
          : vote.side === 'CALL'
            ? crypto
              ? 'LONG'
              : 'BULL'
            : crypto
              ? 'SHORT'
              : 'BEAR'
  return (
    <section
      aria-label="Independent option signals"
      className={
        embedded
          ? 'text-sm text-foreground'
          : docked
            ? 'min-w-0 rounded-md border border-slate-600/50 bg-background p-2 text-xs text-foreground'
            : 'absolute right-[82px] top-[170px] z-20 max-h-[65%] w-[305px] max-w-[calc(100%_-_2rem)] overflow-auto rounded-md border border-slate-600/50 bg-[#131722]/95 p-2 text-[11px] text-slate-200 shadow-md'
      }
    >
      {!embedded ? (
        <div className="mb-1 flex items-center justify-between">
          <strong>Independent {crypto ? 'LONG / SHORT' : 'CALL / PUT'} signals</strong>
          <span className="text-slate-400">Closed price bars</span>
        </div>
      ) : null}
      {chart.kind === 'option' ? (
        <div className="mb-2 space-y-1 border-b border-slate-600 pb-2">
          <label className="block text-xs">
            Independent indicators source
            <select
              aria-label="Independent indicators source"
              value={source}
              onChange={(e) => onSourceChange?.(e.target.value as IndicatorSource)}
              disabled={!onSourceChange}
              className="mt-1 w-full rounded border border-slate-500 bg-[#131722] p-1 text-slate-100"
            >
              <option value="underlying">
                Underlying · {chart.underlying?.symbol ?? 'unavailable'}
              </option>
              <option value="premium">Option premium · {chart.optionSide}</option>
            </select>
          </label>
          <p>
            Price signals:{' '}
            {premiumMode ? symbol : (chart.underlying?.symbol ?? 'underlying unavailable')}.
          </p>
          <p>
            IV / PCR: {chart.underlying?.symbol ?? 'unavailable'} · {expiry || 'expiry unavailable'}
            .
          </p>
          <p>OI / futures MFI: {future?.symbol ?? 'nearest active futures when available'}.</p>
          <p>
            Green = BUY {chart.optionSide}; red = AVOID {chart.optionSide}. Signals do not close
            broker positions.
          </p>
        </div>
      ) : null}
      {!eligible && chart.kind === 'option' ? (
        <p>Underlying not identified; premium price indicators remain available.</p>
      ) : null}
      {!ready && !embedded ? (
        <p className="mb-2 text-amber-300">
          {result
            ? 'Broker history delayed · historical events only.'
            : 'Waiting for verified source candles.'}{' '}
          Other indicators continue from their own data.
        </p>
      ) : null}
      {embedded ? (
        <>
          <div
            aria-label="Overall indicator vote"
            className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted/50 px-3 py-3"
          >
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium text-muted-foreground">Overall</span>
              <strong
                aria-label="Overall indicator signal"
                className={`rounded-md px-3 py-1 text-lg font-bold ${dashboardBadge(vote)}`}
              >
                {overallLabel}
              </strong>
              {vote.tied ? <span className="text-sm text-muted-foreground">Tie</span> : null}
            </div>
            <div className="flex flex-wrap items-center gap-4 text-sm font-semibold tabular-nums">
              <span className="text-emerald-700 dark:text-emerald-400">
                {chart.kind === 'option' ? `BUY ${chart.optionSide}` : crypto ? 'LONG' : 'BUY CALL'}{' '}
                {vote.call}
              </span>
              <span className="text-red-700 dark:text-red-400">
                {chart.kind === 'option'
                  ? `AVOID ${chart.optionSide}`
                  : crypto
                    ? 'SHORT'
                    : 'BUY PUT'}{' '}
                {vote.put}
              </span>
              <span className="text-yellow-700 dark:text-yellow-300">WAIT {vote.wait}</span>
            </div>
          </div>
          <div
            aria-label="Dashboard indicator columns"
            className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
          >
            {[
              { title: 'Momentum', keys: ['rsi', 'imi', 'mfi'] },
              { title: 'Trend', keys: ['bb', 'macd', 'ma'] },
              { title: 'Options data', keys: ['iv', 'pcr', 'oi'] },
            ].map((group) => {
              const rows = states.filter(({ item }) => group.keys.includes(item.key))
              return rows.length ? (
                <div
                  key={group.title}
                  className="min-w-0 overflow-x-auto rounded-lg border border-border/70"
                >
                  <table
                    aria-label={`Indicator values and CALL / PUT signals · ${group.title}`}
                    className="w-full text-left text-sm"
                  >
                    <caption className="border-b bg-muted/30 px-3 py-2 text-left text-sm font-semibold text-foreground">
                      {group.title}
                    </caption>
                    <thead className="text-xs font-medium text-muted-foreground">
                      <tr>
                        <th scope="col" className="px-2 py-2">
                          Indicator
                        </th>
                        <th scope="col" className="px-2 py-2 text-right">
                          Value
                        </th>
                        <th scope="col" className="px-2 py-2">
                          Signal
                        </th>
                        <th scope="col" className="px-2 py-2">
                          Signal time (IST)
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map(({ item, state, context, value, valueSource, valueTime }) => (
                        <tr
                          key={item.key}
                          aria-label={`${item.label} signal`}
                          data-side={action(state).side}
                          className="border-t border-border/60"
                        >
                          <th scope="row" className="px-2 py-3 font-semibold">
                            <span title={item.label}>{item.short}</span>
                          </th>
                          <td
                            className={`whitespace-nowrap px-2 py-3 text-right text-base font-semibold tabular-nums ${dashboardTone(action(state))}`}
                          >
                            {value == null
                              ? '—'
                              : value.toLocaleString('en-IN', {
                                  minimumFractionDigits: item.key === 'oi' ? 0 : 2,
                                  maximumFractionDigits: item.key === 'oi' ? 0 : 2,
                                })}
                            <span className="ml-1 text-xs font-normal">
                              {value == null
                                ? ''
                                : item.key === 'bb' || item.key === 'ma'
                                  ? '%'
                                  : crypto && item.key === 'oi'
                                    ? 'Closed Delta candle'
                                    : item.key === 'iv'
                                      ? state.side === 'PUT'
                                        ? '% PE'
                                        : '% CE'
                                      : ''}
                            </span>
                            <span
                              className="block text-[10px] font-normal text-muted-foreground"
                              title={
                                Number.isFinite(valueTime) && valueTime != null
                                  ? `${valueSource} · ${stamp(valueTime, true)} IST`
                                  : valueSource
                              }
                            >
                              {valueSource}
                            </span>
                          </td>
                          <td className="whitespace-nowrap px-2 py-3">
                            <b
                              className={`inline-flex rounded-md px-2 py-1 text-xs font-semibold ${dashboardBadge(action(state))}`}
                            >
                              {rowLabel(state)}
                            </b>
                          </td>
                          <td
                            className="px-2 py-3 text-xs text-muted-foreground"
                            title={rowReason(state)}
                          >
                            {state.time ? (
                              <>
                                <time
                                  title={`${item.label} signal time`}
                                  dateTime={new Date(state.time * 1000).toISOString()}
                                  className="block whitespace-nowrap"
                                >
                                  {stamp(state.time, true).replace(',', '')}
                                </time>
                                <span className="text-[11px]">
                                  {item.key === 'oi'
                                    ? '30s comparison'
                                    : context
                                      ? 'Source observation'
                                      : 'Last confirmed change'}
                                </span>
                              </>
                            ) : state.value == null ? (
                              'Awaiting data'
                            ) : (
                              'No setup'
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null
            })}
          </div>
        </>
      ) : (
        <div>
          {states.map(({ item, state, context }) => (
            <div
              key={item.key}
              aria-label={`${item.label} signal`}
              data-side={action(state).side}
              className="border-t border-slate-700/50 py-1"
            >
              <div className="flex items-center justify-between gap-2">
                <span>
                  {item.label}{' '}
                  <span className={`tabular-nums ${stateTone(action(state))}`}>
                    {state.value == null ? '—' : state.value.toFixed(2)}
                  </span>
                </span>
                <b className={stateTone(action(state))}>{rowLabel(state)}</b>
              </div>
              <p className="text-[10px] text-slate-400" title={rowReason(state)}>
                {state.time
                  ? `${context ? 'Observed' : 'Last event'} ${stamp(state.time)} IST`
                  : state.reason}
              </p>
            </div>
          ))}
        </div>
      )}
      <details
        className={
          embedded
            ? 'mt-3 border-t pt-3 text-xs text-muted-foreground'
            : 'mt-1 border-t border-slate-700 pt-1'
        }
      >
        <summary className="cursor-pointer">Rules & data</summary>
        <div
          className={
            embedded
              ? 'max-w-5xl space-y-2 py-3 text-xs leading-relaxed text-muted-foreground'
              : 'space-y-1 py-1 text-slate-400'
          }
        >
          {embedded ? (
            <p>
              One equal vote per indicator's latest confirmed state. Highest count wins; ties are
              WAIT. Missing or stale feeds count as WAIT. Price rows need fresh verified candles to
              vote.
            </p>
          ) : null}
          {embedded && !crypto ? (
            <p>
              Live price values update with broker ticks; signals and their timestamps retain
              confirmed candle changes. OI and PCR quotes refresh every 5 seconds. OI direction
              compares observations at least 30 seconds apart. IV uses matched closed 1m candles;
              futures MFI uses closed candles, with history checked every 30 seconds.
            </p>
          ) : null}
          <p>
            Each indicator is independent. Labels describe the selected source and displayed
            contract; they are rule events, not placed orders. Price rows show their last event and
            timestamp; WAIT means no qualifying data or event.
          </p>
          <p>
            RSI14 and IMI14 exit 30/70; MFI14 exits20/80; MACD12/26/9 crosses; BB20/2 close breaks
            an outer band; MA crosses into agreement above/below EMA20 and SMA50.
          </p>
          {crypto ? (
            <>
              <p>
                Crypto uses 24/7 candles. OI compares two matched, completed price and open-interest
                candles: rising OI with rising price gives LONG; rising OI with falling price gives
                SHORT. OI contraction is WAIT. Context history refreshes every30 seconds.
              </p>
              <p>
                IV and PCR require an options contract and chain; they do not apply to this
                perpetual. Price signals use this contract's own OHLC and genuine volume.
              </p>
              {needOI ? (
                <p>
                  {cryptoOi.isFetching
                    ? 'Refreshing Delta open-interest candles…'
                    : cryptoOi.isError
                      ? 'Delta OI unavailable; retrying automatically.'
                      : cryptoOi.data
                        ? `Delta OI observed ${stamp(cryptoOi.data.observedAt)} IST.`
                        : 'Waiting for verified Delta OI history.'}
                </p>
              ) : null}
            </>
          ) : (
            <>
              <p>
                Each row uses its own conditions. IV: only CE IV falling gives CALL; only PE IV
                falling gives PUT; both or neither falling gives WAIT. This is an app-defined
                pricing comparison; IV alone does not establish price direction. PCR: quoted-window
                volume ratio below1 gives CALL, above1 gives PUT, equal1 gives WAIT. OI: rising
                futures OI plus rising/falling futures price over two observed polls. No row
                requires another indicator's confirmation.
              </p>
              <p>
                IV uses matched closed 1m candles, European BSM and 0% rate/yield assumptions. No IV
                Rank is inferred. PCR is the quoted {chain?.chain.length ?? 0}-strike window, not
                the full market. Current option snapshots are not backfilled onto past candles.
              </p>
              <p>
                IV CE: {ce?.symbol ?? 'unavailable'} · PE: {pe?.symbol ?? 'unavailable'} · expiry{' '}
                {expiry || 'unavailable'}. OI/MFI proxy: {future?.symbol ?? 'unavailable'}.
              </p>
              <p>
                {data.isFetching || chainData.isFetching
                  ? 'Refreshing broker option data…'
                  : data.isError || chainData.isError
                    ? 'Option context feed unavailable; price studies continue.'
                    : current
                      ? `Option snapshot observed ${stamp(current.observedAt)} IST.`
                      : 'Waiting for option data.'}
              </p>
              {needOI ? (
                <p>
                  {oiData.isFetching
                    ? 'Refreshing futures OI…'
                    : oiData.isError
                      ? 'Futures OI quote unavailable; other indicators continue.'
                      : !future
                        ? 'Current futures contract unavailable.'
                        : oiData.data
                          ? `Futures OI observed ${stamp(oiData.data.snapshot.observedAt)} IST.`
                          : 'Waiting for futures OI.'}
                </p>
              ) : null}
            </>
          )}
          {needProxy ? (
            <p>
              {proxyData.isFetching
                ? 'Refreshing futures MFI history…'
                : proxyData.isError
                  ? 'Futures MFI history unavailable; other indicators continue.'
                  : proxyData.data
                    ? `Futures MFI history observed ${stamp(proxyData.data.observedAt)} IST.`
                    : 'Waiting for futures MFI history.'}
            </p>
          ) : null}
          {[...(chainData.data?.diagnostics ?? []), ...(data.data?.diagnostics ?? [])].map(
            (message) => (
              <p key={message}>{message}</p>
            )
          )}
          {states.map(({ item, state }) => (
            <p key={item.key}>
              {item.short}: {state.reason}
            </p>
          ))}
          <a
            className="underline"
            href="https://algotest.in/blog/best-indicator-for-option-trading/"
            target="_blank"
            rel="noopener noreferrer"
          >
            Article reference
          </a>
        </div>
      </details>
    </section>
  )
}
