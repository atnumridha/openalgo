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

const label = (state: Pick<IndicatorState, 'side'>) =>
  state.side === 'CALL' ? 'BUY CALL' : state.side === 'PUT' ? 'BUY PUT' : 'WAIT'
const stamp = (time: number | null) =>
  time == null
    ? ''
    : new Date(time * 1000).toLocaleString('en-IN', {
        timeZone: 'Asia/Kolkata',
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
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
  replay,
  ready,
  embedded = false,
  reference,
  onMfiProxy,
}: {
  result: NineResult | null
  enabled: string[]
  symbol: string
  exchange: string
  interval: string
  seconds: number
  asOf: number
  replay: boolean
  ready: boolean
  embedded?: boolean
  reference?: OptionReference
  onMfiProxy: (result: NineResult | null) => void
}) {
  const username = useAuthStore((s) => s.user?.username)
  const apiKey = useAuthStore((s) => s.apiKey)
  const mode = useThemeStore((s) => s.appMode)
  const [now, setNow] = useState(() => Date.now() / 1000)
  const [observations, setObservations] = useState<OptionSignalSnapshot[]>([])
  const eligible = ['NSE_INDEX', 'BSE_INDEX'].includes(exchange)
  const live = eligible && !replay
  const derivativesExchange = exchange === 'BSE_INDEX' ? 'BFO' : 'NFO'
  const selected = INDICATORS.filter((item) => enabled.includes(item.id))
  const nativeMfi = result?.states.find((s) => s.key === 'mfi')
  const needProxy = enabled.includes('nine-mfi') && nativeMfi?.value == null
  const needIV = enabled.includes('nine-iv'),
    needPCR = enabled.includes('nine-pcr'),
    needOI = enabled.includes('nine-oi')
  const needsData = live && (needIV || needPCR || needOI || needProxy)
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 5000)
    return () => window.clearInterval(timer)
  }, [])
  const metadata = useQuery({
    queryKey: ['nine-indicator-metadata', username, mode, symbol, derivativesExchange],
    enabled: needsData,
    queryFn: async () => {
      const [expiries, futures] = await Promise.allSettled([
        scalpingApi.getExpiry(symbol, derivativesExchange, 'options'),
        scalpingApi.futures(symbol, derivativesExchange),
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
  const scopedReference =
    reference?.underlying === symbol && reference.exchange === exchange ? reference : undefined
  const expiry = scopedReference?.expiry || metadata.data?.expiry || ''
  const future = metadata.data?.future
  const identity = [
    username,
    mode,
    symbol,
    exchange,
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
    staleTime: 20000,
    refetchInterval: live && needOI ? 30000 : false,
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
          underlying: symbol,
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
    staleTime: 20000,
    refetchInterval: live && (needIV || needPCR) ? 30000 : false,
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
        needIV ? readIVHistory(symbol, exchange) : Promise.resolve(null),
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
    setObservations((old) =>
      [
        ...old.filter((s) => s.identity === identity && s.observedAt !== snapshot.observedAt),
        snapshot,
      ].slice(-2)
    )
  }, [oiData.data, identity, live])
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
          true
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
  const current = useMemo(() => {
    const options = data.data?.snapshot.identity === identity ? data.data.snapshot : undefined
    const oi = oiData.data?.snapshot.identity === identity ? oiData.data.snapshot : undefined
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
  }, [data.data, oiData.data, chainData.data, identity, expiry])
  const previous = observations
    .filter((s) => s.identity === identity && s.observedAt < (current?.futureObservedAt ?? 0))
    .at(-1)
  const contextStates = live ? optionContextStates(current, previous, identity, wallTime) : []
  const proxyMfi = proxyResult?.states.find((s) => s.key === 'mfi')
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
    if (!eligible || (context && replay))
      state = {
        ...state,
        side: 'WAIT',
        reason: !eligible
          ? 'CALL/PUT signals require an underlying index chart'
          : 'Live options context is unavailable in replay',
        time: null,
        value: null,
      }
    return { item, state, context }
  })
  const vote = indicatorVote(
    states.map(({ item, state, context }) =>
      context || (ready && freshIndex) || (item.key === 'mfi' && proxyResult) ? state.side : 'WAIT'
    )
  )
  return (
    <section
      aria-label="Independent option signals"
      className={
        embedded
          ? 'text-sm text-foreground'
          : 'absolute right-[82px] top-[170px] z-20 max-h-[65%] w-[305px] max-w-[calc(100%_-_2rem)] overflow-auto rounded-md border border-slate-600/50 bg-[#131722]/95 p-2 text-[11px] text-slate-200 shadow-md'
      }
    >
      {!embedded ? (
        <div className="mb-1 flex items-center justify-between">
          <strong>Independent CALL / PUT signals</strong>
          <span className="text-slate-400">Closed price bars</span>
        </div>
      ) : null}
      {!eligible ? <p>Choose the Nifty or Sensex index chart for option direction.</p> : null}
      {!ready && !embedded ? (
        <p className="mb-2 text-amber-300">
          {result
            ? 'Broker history delayed · historical events only.'
            : 'Waiting for verified index history.'}{' '}
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
                {label(vote)}
              </strong>
              {vote.tied ? <span className="text-sm text-muted-foreground">Tie</span> : null}
            </div>
            <div className="flex flex-wrap items-center gap-4 text-sm font-semibold tabular-nums">
              <span className="text-emerald-700 dark:text-emerald-400">BUY CALL {vote.call}</span>
              <span className="text-red-700 dark:text-red-400">BUY PUT {vote.put}</span>
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
                          Time (IST)
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map(({ item, state, context }) => (
                        <tr
                          key={item.key}
                          aria-label={`${item.label} signal`}
                          data-side={state.side}
                          className="border-t border-border/60"
                        >
                          <th scope="row" className="px-2 py-3 font-semibold">
                            <span title={item.label}>{item.short}</span>
                          </th>
                          <td
                            className={`whitespace-nowrap px-2 py-3 text-right text-base font-semibold tabular-nums ${dashboardTone(state)}`}
                          >
                            {state.value == null
                              ? '—'
                              : state.value.toLocaleString('en-IN', {
                                  minimumFractionDigits: item.key === 'oi' ? 0 : 2,
                                  maximumFractionDigits: item.key === 'oi' ? 0 : 2,
                                })}
                            <span className="ml-1 text-xs font-normal">
                              {state.value == null
                                ? ''
                                : item.key === 'bb' || item.key === 'ma'
                                  ? '%'
                                  : item.key === 'iv'
                                    ? state.side === 'PUT'
                                      ? '% PE'
                                      : '% CE'
                                    : ''}
                            </span>
                          </td>
                          <td className="whitespace-nowrap px-2 py-3">
                            <b
                              className={`inline-flex rounded-md px-2 py-1 text-xs font-semibold ${dashboardBadge(state)}`}
                            >
                              {label(state)}
                            </b>
                          </td>
                          <td
                            className="px-2 py-3 text-xs text-muted-foreground"
                            title={state.reason}
                          >
                            {state.time ? (
                              <>
                                <span className="block whitespace-nowrap">
                                  {stamp(state.time).replace(',', '')}
                                </span>
                                <span className="text-[11px]">
                                  {context ? 'Observed' : 'Last event'}
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
              data-side={state.side}
              className="border-t border-slate-700/50 py-1"
            >
              <div className="flex items-center justify-between gap-2">
                <span>
                  {item.label}{' '}
                  <span className={`tabular-nums ${stateTone(state)}`}>
                    {state.value == null ? '—' : state.value.toFixed(2)}
                  </span>
                </span>
                <b className={stateTone(state)}>{label(state)}</b>
              </div>
              <p className="text-[10px] text-slate-400" title={state.reason}>
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
          <p>
            Each indicator is independent. Green BUY CALL / red BUY PUT labels indicate rule events,
            not placed orders. Price rows show their last event and timestamp; WAIT means no
            qualifying data or event.
          </p>
          <p>
            RSI14 and IMI14 exit 30/70; MFI14 exits20/80; MACD12/26/9 crosses; BB20/2 close breaks
            an outer band; MA crosses into agreement above/below EMA20 and SMA50.
          </p>
          <p>
            Each row uses its own conditions. IV: only CE IV falling gives CALL; only PE IV falling
            gives PUT; both or neither falling gives WAIT. This is an app-defined pricing
            comparison; IV alone does not establish price direction. PCR: quoted-window volume ratio
            below1 gives CALL, above1 gives PUT, equal1 gives WAIT. OI: rising futures OI plus
            rising/falling futures price over two observed polls. No row requires another
            indicator's confirmation.
          </p>
          <p>
            IV uses matched closed 1m candles, European BSM and 0% rate/yield assumptions. No IV
            Rank is inferred. PCR is the quoted {chain?.chain.length ?? 0}-strike window, not the
            full market. Current option snapshots are not backfilled onto past candles.
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
