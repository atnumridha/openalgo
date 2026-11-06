import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  kotakAssistantApi,
  type Leg,
  type Quote,
  type RiskSettings,
  type DeskMode,
  type Snapshot,
  type Trade,
  type SetupStrategy,
  type SetupMode,
  type SetupResult,
  type PivotOverlay,
} from '@/api/kotakAssistant'
import { scalpingApi } from '@/api/scalping'
import { ScalpingCharts } from './ScalpingCharts'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useMarketData } from '@/hooks/useMarketData'
import { useOrderEventRefresh } from '@/hooks/useOrderEventRefresh'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { OtherPositions } from './OtherPositions'
import { BrokerPositions, unownedBrokerPositions } from './BrokerPositions'
import { feeDay, ticketCosts } from './feeEstimates'
import { DailyDiscipline } from './DailyDiscipline'
import { SetupAssistant } from './SetupAssistant'
import { EntryDecisionAssistant } from './EntryDecisionAssistant'
import { setupChartAnnotations, setupForSelectedSide } from './setupChart'
import { ManagedTrades } from './ManagedTrades'
import { TradeTracking } from './TradeTracking'
import { IndexMovement } from './IndexMovement'
import { useManualTracking, ManualTrackingTicket, ManualTrackedTrades } from './ManualTracking'
import { orderBookQuantities } from './orderBookQuantities'
import { ChartBuyControls, TradingTicketView, useTradingTicket } from './TradingTicket'
import { MarketStructure, LEVEL_COLORS } from './PriceLevels'
import { errorMessage, expiryAscending, expiryTime, money, deskPlaceholder } from './model'

const INITIAL: RiskSettings = {
  risk: null,
  daily_loss: null,
  giveback: null,
  premium: null,
  spread: 2,
  slippage: 0.1,
  brokerage: 10,
  cooldown: 300,
  cutoff: '15:15',
}
const NO_TRADES: Trade[] = []
const NO_FILLS: NonNullable<NonNullable<Snapshot['day']>['journal']>['fills'] = []

function useTicketLevels(entry?: number, sl?: number, target?: number) {
  return useMemo(
    () =>
      [
        { price: entry ?? 0, title: 'Entry', color: LEVEL_COLORS.entry },
        { price: sl ?? 0, title: 'Stop loss', color: LEVEL_COLORS.stop },
        { price: target ?? 0, title: 'Target', color: LEVEL_COLORS.target },
      ].filter((l) => Number.isFinite(l.price) && l.price > 0),
    [entry, sl, target]
  )
}
export function KotakAssistant() {
  const broker = useAuthStore((s) => s.user?.broker)
  return broker === 'kotak' ? <Desk /> : null
}
function Desk() {
  const username = useAuthStore((s) => s.user?.username),
    appMode = useThemeStore((s) => s.appMode)
  const mode: DeskMode = appMode === 'live' ? 'live' : 'analyze'
  const [pivotOverlay, setPivotOverlay] = useState<PivotOverlay | null>(null)
  const manualTracking = useManualTracking(`${username}:kotak`)
  const [underlying, setUnderlying] = useState('NIFTY'),
    [expiry, setExpiry] = useState(''),
    [strategy, setStrategy] = useState<SetupStrategy>('trend'),
    [signalMode, setSignalMode] = useState<SetupMode>('confirmed'),
    [replayUntil, setReplayUntil] = useState<number | null>(null),
    [selected, setSelected] = useState(''),
    [strikeChoice, setStrikeChoice] = useState(''),
    [sideChoice, setSideChoice] = useState<'ce' | 'pe'>('ce'),
    [preferredRatio, setPreferredRatio] = useState('2'),
    [count, setCount] = useState(8),
    [interval, setIntervalView] = useState('5m'),
    [now, setNow] = useState(Date.now() / 1000),
    [risk, setRisk] = useState<RiskSettings>(INITIAL),
    [notice, setNotice] = useState(''),
    [saving, setSaving] = useState(false)
  const selectContract = useCallback((symbol: string) => {
    setSelected(symbol)
    setSideChoice(/PE$/.test(symbol) ? 'pe' : 'ce')
  }, [])
  const [journalDate, setJournalDate] = useState(() =>
    new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Kolkata',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(new Date())
  )
  const qc = useQueryClient()
  const exchange = underlying === 'SENSEX' ? 'BFO' : 'NFO',
    indexExchange = underlying === 'SENSEX' ? 'BSE_INDEX' : 'NSE_INDEX'
  const key = [
    'kotak-desk',
    username,
    mode,
    underlying,
    expiry,
    count,
    selected,
    strategy,
    signalMode,
    preferredRatio,
  ]
  const snapshot = useQuery({
    queryKey: key,
    queryFn: () =>
      kotakAssistantApi.snapshot({
        underlying,
        expiry,
        count,
        symbol: selected,
        strategy,
        signal_mode: signalMode,
        rr: preferredRatio,
      }),
    placeholderData: (previous, query) => deskPlaceholder(previous, query?.queryKey, key),
    refetchInterval: 1000,
    refetchIntervalInBackground: true,
    retry: false,
  })
  const brokerMonitor = useQuery({
    queryKey: ['kotak-broker-monitor', username],
    queryFn: () => kotakAssistantApi.brokerMonitor(),
    refetchInterval: 1000,
    refetchIntervalInBackground: true,
    retry: false,
  })
  const expiries = useQuery({
    queryKey: ['kotak-expiries', username, underlying, mode],
    queryFn: async () => {
      const result = await scalpingApi.getExpiry(underlying, exchange)
      if (result.status !== 'success') throw new Error(result.message || 'Expiry lookup failed')
      return result
    },
    staleTime: 60000,
    retry: false,
    refetchInterval: (query) =>
      query.state.status === 'error' || !query.state.data?.data?.length ? 5000 : 60000,
    refetchIntervalInBackground: true,
  })
  const replaySetup = useQuery({
    queryKey: ['kotak-setup-replay', username, underlying, strategy, signalMode, replayUntil],
    queryFn: () =>
      kotakAssistantApi.setupReplay({
        underlying,
        strategy,
        signal_mode: signalMode,
        until: replayUntil!,
      }),
    enabled: replayUntil != null,
    retry: false,
    staleTime: 60000,
  })
  const d = snapshot.data
  const displayedSetup: SetupResult | null | undefined = setupForSelectedSide(
    replayUntil == null ? d?.setup : replaySetup.data,
    selected ? (selected.endsWith('PE') ? 'PE' : 'CE') : undefined
  )
  const setupAnnotations = useMemo(
    () => setupChartAnnotations(displayedSetup, replayUntil ?? now),
    [displayedSetup, replayUntil, now]
  )
  const settingsKey = JSON.stringify(d?.settings)
  useEffect(() => {
    if (d?.settings) setRisk(d.settings)
  }, [settingsKey])
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => {
    setExpiry('')
    setSelected('')
    setStrikeChoice('')
  }, [underlying, mode, username])
  const refresh = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['kotak-desk', username] })
    void qc.invalidateQueries({ queryKey: ['kotak-broker-monitor', username] })
    void qc.invalidateQueries({ queryKey: ['kotak-expiries', username] })
  }, [qc, username])
  useOrderEventRefresh(refresh, {
    events: ['order_event', 'analyzer_update', 'close_position_event'],
    delay: 0,
  })
  const trades = useMemo(
    () =>
      [...(d?.trades || []), ...(d?.live_trades || [])].filter(
        (t) => !['closed', 'rejected'].includes(t.status)
      ),
    [d?.trades, d?.live_trades]
  )
  const brokerPositions = useMemo(
    () => unownedBrokerPositions(brokerMonitor.data, trades),
    [brokerMonitor.data, trades]
  )
  const legs = useMemo(
    () => (d?.chain?.chain || []).flatMap((r) => [r.ce, r.pe].filter((l): l is Leg => !!l)),
    [d?.chain]
  )
  const strikeRows = expiry ? d?.chain?.chain || [] : []
  const focusedRow =
    strikeRows.find((r) => r.ce?.symbol === selected || r.pe?.symbol === selected) ||
    strikeRows.find((r) => String(r.strike) === strikeChoice) ||
    strikeRows.find((r) => r.strike === d?.chain?.atm_strike) ||
    strikeRows[Math.floor(strikeRows.length / 2)]
  useEffect(() => {
    const contract = focusedRow?.[sideChoice]
    if (expiry && !selected && contract) selectContract(contract.symbol)
  }, [expiry, selected, focusedRow, sideChoice, selectContract])
  const strikeListRef = useRef<HTMLDivElement | null>(null)
  const scrolledStrike = useRef('')
  useEffect(() => {
    const key = `${username}:${mode}:${underlying}:${expiry}:${selected}:${focusedRow?.strike}`
    if (scrolledStrike.current === key || !focusedRow || !strikeListRef.current) return
    const row = strikeListRef.current.querySelector(`[data-strike="${focusedRow.strike}"]`)
    if (!row) return
    const container = strikeListRef.current
    container.scrollTop +=
      row.getBoundingClientRect().top -
      container.getBoundingClientRect().top -
      container.clientHeight / 2 +
      row.getBoundingClientRect().height / 2
    scrolledStrike.current = key
  }, [username, mode, underlying, expiry, selected, focusedRow, d?.chain])
  const symbols = useMemo(
    () => [
      { symbol: underlying, exchange: indexExchange },
      ...legs.map((l) => ({ symbol: l.symbol, exchange })),
      ...trades.map((t) => ({ symbol: t.symbol, exchange: t.exchange })),
      ...brokerPositions.map((p) => ({ symbol: p.symbol, exchange: p.exchange })),
    ],
    [underlying, indexExchange, legs, exchange, trades, brokerPositions]
  )
  const feed = useMarketData({ symbols, mode: 'Depth' })
  // Quote mode carries the index reference and option day-volume counters.
  // These subscriptions share the existing connection with Depth.
  const indexStream = useMarketData({
    symbols: [
      ...new Map(
        [
          { symbol: underlying, exchange: indexExchange },
          ...(selected ? [{ symbol: selected, exchange }] : []),
          ...trades.map((t) => ({ symbol: t.symbol, exchange: t.exchange })),
          ...brokerPositions.map((p) => ({ symbol: p.symbol, exchange: p.exchange })),
          ...manualTracking.rows
            .filter((r) => !r.closed)
            .map((r) => ({ symbol: r.symbol, exchange: r.exchange })),
        ].map((item) => [`${item.exchange}:${item.symbol}`, item])
      ).values(),
    ],
    mode: 'Quote',
  })
  const quote = useCallback(
    (symbol: string, ex: string, fallback?: Quote): Quote | undefined => {
      const tick = (ex.endsWith('_INDEX') ? indexStream.data : feed.data).get(`${ex}:${symbol}`)
      if (tick?.lastUpdate && now - tick.lastUpdate / 1000 <= 5) {
        const bid = tick.data.bid_price ?? tick.data.depth?.buy[0]?.price,
          ask = tick.data.ask_price ?? tick.data.depth?.sell[0]?.price
        if (ex.endsWith('_INDEX') && tick.data.ltp)
          return {
            ltp: tick.data.ltp,
            prev_close: [tick.data.close, fallback?.prev_close, fallback?.close].find(
              (value) => typeof value === 'number' && Number.isFinite(value) && value > 0
            ),
            time: tick.lastUpdate / 1000,
            timestamp: tick.data.timestamp,
            source: tick.updateSource === 'websocket' ? 'Live feed' : 'Broker snapshot',
          }
        if (
          (bid != null && ask != null && bid > 0 && ask >= bid) ||
          (tick.data.ltp != null && tick.data.ltp > 0)
        )
          return {
            ltp: tick.data.ltp,
            volume: tick.data.volume,
            ...orderBookQuantities(tick.data),
            bid,
            ask,
            time: tick.lastUpdate / 1000,
            timestamp: tick.data.timestamp,
            source: tick.updateSource === 'websocket' ? 'Live feed' : 'Broker snapshot',
          }
      }
      return fallback
    },
    [feed.data, indexStream.data, now]
  )
  const ix = quote(underlying, indexExchange, d?.index_quote || undefined)
  const ceTicket = useTradingTicket({
    leg: focusedRow?.ce || null,
    desk: d,
    mode,
    refresh,
    selectedPlan: selected === focusedRow?.ce?.symbol ? d?.selected_plan || null : null,
    defaultRatio: preferredRatio,
    onRatioChange: setPreferredRatio,
  })
  const peTicket = useTradingTicket({
    previewDelay: 1800,
    leg: focusedRow?.pe || null,
    desk: d,
    mode,
    refresh,
    selectedPlan: selected === focusedRow?.pe?.symbol ? d?.selected_plan || null : null,
    defaultRatio: preferredRatio,
    onRatioChange: setPreferredRatio,
  })
  const useSetup = (setup: SetupResult) => {
    if (replayUntil != null || setup.read_only) return
    const recommended = d?.recommendation
    const leg = legs.find((item) => item.symbol === selected)
    if (leg && !leg.symbol.endsWith(setup.direction || '?')) {
      setNotice(
        'The index setup does not match your selected CE/PE. Your strike selection is unchanged.'
      )
      return
    }
    if (!leg) {
      setNotice('Choose an expiry and a matching option contract first.')
      return
    }
    const q = quote(leg.symbol, exchange, {
      ltp: leg.ltp,
      bid: leg.bid,
      ask: leg.ask,
      time: d?.chain_time || 0,
    })
    if (!q?.ask || now - q.time > 5) {
      setNotice('A fresh option ask is needed to load this setup.')
      return
    }
    if (
      setup.strategy === 'trend' &&
      !(d?.selected_plan || (recommended?.symbol === leg.symbol ? recommended.plan : null))?.fits
    ) {
      setNotice(
        'Loading the selected option’s completed candles for its premium stop. Use setup again when the plan is ready.'
      )
      return
    }
    const option = { ...leg, ask: q.ask, bid: q.bid, ltp: q.ltp }
    ;(setup.direction === 'PE' ? peTicket : ceTicket).adoptSetup(setup, option)
    setNotice('Setup loaded. Review the option premium, lots, SL and target in the ticket.')
  }
  const activeTicket = selected.endsWith('PE') ? peTicket : ceTicket
  const selectedLeg = legs.find((leg) => leg.symbol === selected)
  const contractPlan =
    d?.selected_contract?.symbol === selected && d.selected_contract.strategy === strategy
      ? d.selected_contract
      : undefined
  const indicativePlan = contractPlan?.plan?.fits ? contractPlan.plan : undefined
  const ticketIsPlan =
    activeTicket.leg?.symbol === selected &&
    (strategy === 'trend' ? !activeTicket.cashRisk : activeTicket.cashRisk)
  const selectedPremium = ticketIsPlan ? activeTicket.order : indicativePlan
  const selectedCosts = ticketIsPlan
    ? activeTicket.costEstimate
    : indicativePlan
      ? ticketCosts(
          { ...activeTicket.order!, ...indicativePlan },
          exchange,
          d?.settings.brokerage ?? 10,
          d?.settings.slippage ?? 0,
          feeDay(now * 1000)
        )
      : null
  const selectedContract =
    selectedLeg && focusedRow
      ? {
          symbol: selected,
          side: selected.endsWith('PE') ? ('PE' as const) : ('CE' as const),
          strike: focusedRow.strike,
          expiry,
          quantity: selectedPremium?.quantity,
          entry: selectedPremium?.entry,
          sl: selectedPremium?.sl,
          target: selectedPremium?.target,
          costs: selectedCosts,
          source: ticketIsPlan ? 'Ticket values' : 'Indicative · 1 lot',
          reason: ticketIsPlan
            ? activeTicket.cashRisk
              ? activeTicket.cashStatus
              : contractPlan?.reason
            : indicativePlan
              ? 'Use setup to load this selected contract’s plan.'
              : contractPlan?.reason || 'Loading the selected strike’s premium plan…',
        }
      : null
  const ceLevels = useTicketLevels(
    ceTicket.order?.entry,
    ceTicket.order?.sl,
    ceTicket.order?.target
  )
  const peLevels = useTicketLevels(
    peTicket.order?.entry,
    peTicket.order?.sl,
    peTicket.order?.target
  )

  const levels = useMemo(() => {
    const zones = (d?.analysis.zones || []).filter((z) => Number.isFinite(z.price) && z.price > 0)
    const price = ix?.ltp
    if (!price) return []
    const support = zones
      .filter((z) => z.kind === 'low' && z.price <= price)
      .sort((a, b) => b.price - a.price)[0]
    const resistance = zones
      .filter((z) => z.kind === 'high' && z.price >= price)
      .sort((a, b) => a.price - b.price)[0]
    return [
      ...(support ? [{ price: support.price, title: 'Support', color: LEVEL_COLORS.support }] : []),
      ...(resistance
        ? [{ price: resistance.price, title: 'Resistance', color: LEVEL_COLORS.resistance }]
        : []),
    ]
  }, [d?.analysis.zones, ix?.ltp])
  const save = async () => {
    setSaving(true)
    try {
      await kotakAssistantApi.configure(mode, risk)
      setNotice('Risk settings saved')
      refresh()
    } catch (e) {
      setNotice(errorMessage(e))
    } finally {
      setSaving(false)
    }
  }
  const today = new Date(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Kolkata',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(new Date())
  ).getTime()
  const options = expiryAscending(expiries.data?.data || []).filter((e) => expiryTime(e) >= today)
  const firstExpiry = options[0] || ''
  const expiryPlaceholder =
    expiries.isPending || (!options.length && expiries.isFetching)
      ? 'Loading expiries…'
      : expiries.isError
        ? 'Expiry unavailable'
        : 'No active expiries'
  useEffect(() => {
    if (!expiry && firstExpiry) setExpiry(firstExpiry)
  }, [expiry, firstExpiry])
  const indexFresh = !!ix && now - ix.time <= 5
  const booksFresh = !!d?.book_time && now - d.book_time <= 15
  const action = indexFresh && booksFresh ? d?.analysis.action || 'WAIT' : 'WAIT'
  const signalReason =
    indexFresh && booksFresh ? d?.analysis.reason : 'Waiting for fresh market and account data'
  return (
    <section aria-label="Kotak trading assistant" className="space-y-3">
      <DailyDiscipline
        key={brokerMonitor.data?.scope || d?.scope || username}
        scope={brokerMonitor.data?.scope || d?.scope || `${username}:kotak`}
        discipline={
          brokerMonitor.data?.discipline || (mode === 'live' ? d?.day?.discipline : undefined)
        }
        bookTime={brokerMonitor.data?.discipline ? brokerMonitor.data.book_time : d?.book_time}
        now={now}
        error={
          brokerMonitor.data?.discipline
            ? brokerMonitor.data.error ||
              (brokerMonitor.error ? errorMessage(brokerMonitor.error) : null)
            : d?.error ||
              (d?.day?.risk_available === false
                ? d.day.risk_error || 'Account risk data unavailable'
                : null)
        }
      />
      <Card className="gap-0 py-0 overflow-hidden">
        <CardContent className="p-3 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">Kotak Trading Assistant</h2>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant={mode === 'live' ? 'destructive' : 'secondary'}>
                {mode === 'live' ? 'LIVE' : 'PAPER'}
              </Badge>
              <Button variant="ghost" size="sm" onClick={refresh}>
                Refresh
              </Button>
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-sm">
              Index
              <select
                aria-label="Index"
                className="block h-9 rounded-md border bg-background px-2 text-sm"
                value={underlying}
                onChange={(e) => setUnderlying(e.target.value)}
              >
                <option>NIFTY</option>
                <option>BANKNIFTY</option>
                <option>SENSEX</option>
              </select>
            </label>
            <label className="text-sm">
              Expiry · nearest first
              <select
                aria-label="Expiry"
                aria-busy={expiries.isFetching}
                aria-describedby={
                  !options.length && !expiries.isPending ? 'kotak-expiry-status' : undefined
                }
                disabled={!options.length}
                className="block h-9 rounded-md border bg-background px-2 text-sm"
                value={expiry}
                onChange={(e) => {
                  setExpiry(e.target.value)
                  setSelected('')
                  setStrikeChoice('')
                }}
              >
                <option value="">{options.length ? 'Select expiry' : expiryPlaceholder}</option>
                {options.map((e) => (
                  <option key={e}>{e}</option>
                ))}
              </select>
            </label>
            {!options.length && !expiries.isPending && (
              <div id="kotak-expiry-status" role="status" className="text-sm text-muted-foreground">
                <span>
                  {expiries.isError
                    ? `${underlying} expiries unavailable · retrying automatically.`
                    : `No active ${underlying} expiries found · checking again.`}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={expiries.isFetching}
                  onClick={() => void expiries.refetch()}
                >
                  Retry expiries
                </Button>
              </div>
            )}
            <label className="text-sm">
              Strike
              <select
                aria-label="Strike"
                disabled={!strikeRows.length}
                className="block h-9 min-w-28 rounded-md border bg-background px-2 text-sm"
                value={focusedRow?.strike || ''}
                onChange={(e) => {
                  setStrikeChoice(e.target.value)
                  const row = strikeRows.find((r) => String(r.strike) === e.target.value)
                  const contract = row?.[sideChoice]
                  if (contract) selectContract(contract.symbol)
                  else setSelected('')
                }}
              >
                {!strikeRows.length && (
                  <option value="">{expiry ? 'Loading strikes…' : 'Choose expiry'}</option>
                )}
                {strikeRows.map((r) => (
                  <option key={r.strike} value={r.strike}>
                    {r.strike}
                    {r.strike === d?.chain?.atm_strike ? ' · ATM' : ''}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex items-center gap-2" aria-label="Quick option selection">
              {(['ce', 'pe'] as const).map((side) => {
                const option = focusedRow?.[side]
                return (
                  <Button
                    key={side}
                    variant={option && selected === option.symbol ? 'secondary' : 'outline'}
                    className="h-9"
                    disabled={!option}
                    aria-label={`Select ${focusedRow?.strike || ''} ${side.toUpperCase()}`}
                    onClick={() => option && selectContract(option.symbol)}
                    onMouseEnter={() =>
                      option && selected !== option.symbol && selectContract(option.symbol)
                    }
                  >
                    {side.toUpperCase()} {option ? money(option.ltp ?? option.ask) : '—'}
                  </Button>
                )
              })}
            </div>
            <strong className="tabular-nums">
              {underlying} {money(ix?.ltp)}
            </strong>
            <span className="text-xs text-muted-foreground">
              {ix?.time && now - ix.time <= 5
                ? ix.source === 'Live feed'
                  ? 'Live feed · panels refresh 1s'
                  : 'Broker snapshots · panels refresh 1s'
                : 'Waiting for fresh prices · panels refresh 1s'}
            </span>
          </div>
          <IndexMovement index={underlying} quote={ix} now={Date.now() / 1000} />
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-2">
            <Badge variant="outline">{action}</Badge>
            <span className="text-sm">{signalReason}</span>
            <span className="text-xs text-muted-foreground ml-auto">
              Account{' '}
              {d?.book_time ? `${Math.max(0, Math.floor(now - d.book_time))}s ago` : 'unavailable'}
            </span>
          </div>
          {(snapshot.error || d?.error) && (
            <p role="alert" className="text-sm text-destructive">
              {snapshot.error ? errorMessage(snapshot.error) : d?.error}
            </p>
          )}
          {d?.day?.halt && (
            <p role="alert" className="font-medium text-destructive">
              New entries paused: {d.day.halt}. Exit controls remain available.
            </p>
          )}
          {d?.day?.cooldown_until != null && d.day.cooldown_until > now && (
            <p role="alert">
              Loss cooldown: {Math.ceil(d.day.cooldown_until - now)} seconds remaining.
            </p>
          )}
          <div className="grid grid-cols-2 gap-2 border-t pt-2 text-xs sm:grid-cols-5">
            {[
              ['Gross realised', d?.day?.journal?.gross_realised],
              ['Estimated charges', d?.day?.journal?.charges],
              ['Estimated net realised', d?.day?.journal?.net_realised],
              ['Estimated account net', d?.day?.net],
              ['Observed net peak', d?.day?.peak],
            ].map(([label, value]) => (
              <div key={String(label)}>
                <span className="text-muted-foreground">{String(label)}</span>
                <strong className="mt-1 block text-sm tabular-nums">
                  {money(value as number | null | undefined)}
                </strong>
              </div>
            ))}
          </div>
          {d?.day?.risk_available === false && (
            <p className="text-xs text-destructive">
              Risk valuation unavailable: {d.day.risk_error || d.day.journal?.reason}. Previous
              estimates are for context.
            </p>
          )}
          {d?.day?.journal && !d.day.journal.complete && (
            <p className="text-xs text-destructive">Journal incomplete: {d.day.journal.reason}</p>
          )}
        </CardContent>
      </Card>
      <div className="grid gap-3 min-[900px]:grid-cols-2">
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3"
          aria-label="Recommended strike"
        >
          <div className="min-w-0">
            <h3 className="text-xs font-medium text-muted-foreground">Recommended strike</h3>
            {d?.recommendation ? (
              <>
                <p className="text-lg font-semibold">
                  {underlying} {d.recommendation.strike} {d.recommendation.side}
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    {expiry} · {action === 'WAIT' ? 'Watchlist only · WAIT' : action}
                  </span>
                </p>
                <p className="text-xs text-muted-foreground">{d.recommendation.reason}</p>
              </>
            ) : (
              <p className="mt-1 text-sm">
                {!expiry
                  ? 'Choose an expiry to find a candidate.'
                  : action === 'WAIT'
                    ? 'WAIT · no qualified strike recommendation.'
                    : 'Checking available strikes…'}
              </p>
            )}
          </div>
          {d?.recommendation && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => selectContract(d.recommendation!.symbol)}
            >
              Inspect recommended strike
            </Button>
          )}
        </div>
        <details className="rounded-lg border bg-card px-3 py-3">
          <summary className="cursor-pointer text-sm font-medium">
            {underlying} index levels
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              Support{' '}
              {levels.find((l) => l.title === 'Support')?.price.toLocaleString('en-IN') || '—'} ·
              Resistance{' '}
              {levels.find((l) => l.title === 'Resistance')?.price.toLocaleString('en-IN') || '—'}
            </span>
          </summary>
          <div className="mt-3">
            {' '}
            <MarketStructure
              index={underlying}
              price={ix?.ltp}
              fresh={indexFresh}
              zones={d?.analysis.zones || []}
            />
          </div>
        </details>
      </div>
      <ScalpingCharts
        ce={focusedRow?.ce}
        pe={focusedRow?.pe}
        underlying={underlying}
        expiry={expiry}
        strike={focusedRow?.strike}
        exchange={exchange}
        indexExchange={indexExchange}
        interval={interval}
        onIntervalChange={setIntervalView}
        selected={selected}
        select={selectContract}
        mode={mode}
        trades={trades}
        indexLevels={[...levels, ...setupAnnotations.levels]}
        pivotOverlay={pivotOverlay}
        indexMarkers={setupAnnotations.markers}
        onReplayTimeChange={setReplayUntil}
        ceLevels={ceLevels}
        peLevels={peLevels}
        ceOrderControls={
          <ChartBuyControls
            controller={ceTicket}
            side="CE"
            activate={() => focusedRow?.ce && selectContract(focusedRow.ce.symbol)}
          />
        }
        peOrderControls={
          <ChartBuyControls
            controller={peTicket}
            side="PE"
            activate={() => focusedRow?.pe && selectContract(focusedRow.pe.symbol)}
          />
        }
        fills={d?.day?.journal?.fills || NO_FILLS}
      >
        <div className="space-y-3 border-b p-3">
          <EntryDecisionAssistant
            onPivotOverlay={setPivotOverlay}
            scope={`${username}:${mode}`}
            underlying={underlying}
            symbol={selected}
            side={selectedLeg ? selected.endsWith('PE') ? 'PE' : 'CE' : undefined}
            lots={activeTicket.lots}
            onLotsChange={activeTicket.setLots}
            now={now}
            replay={replayUntil != null}
            onUse={(plan) => {
              activeTicket.useManualRisk()
              activeTicket.changeEntry(String(plan.entry))
              activeTicket.setSL(String(plan.sl))
              activeTicket.setTarget(String(plan.target))
              activeTicket.setAutoInvalidation(false)
              setNotice('Decision levels loaded into the selected ticket. Review before buying.')
            }}
          />
          <details open={replayUntil != null}>
          <summary className="min-h-11 cursor-pointer content-center text-sm font-medium">Other strategy tools and replay</summary>
          <SetupAssistant
            setup={displayedSetup}
            selectedContract={
              replayUntil == null
                ? selectedContract
                : selectedContract && {
                    symbol: selectedContract.symbol,
                    side: selectedContract.side,
                    strike: selectedContract.strike,
                    expiry: selectedContract.expiry,
                    source: 'Read-only replay',
                    reason:
                      'Index sequence for this option side. Historical option premium plans are unavailable in this replay.',
                  }
            }
            strategy={strategy}
            mode={signalMode}
            onStrategyChange={(value) => {
              setStrategy(value)
              if (value === 'opening_reversal') setIntervalView('1m')
            }}
            onModeChange={setSignalMode}
            onUseSetup={useSetup}
            now={replayUntil ?? now}
            replay={replayUntil != null}
            executionReadiness={d?.execution_readiness}
          />
          </details>
          {replayUntil != null && replaySetup.error && (
            <p role="alert" className="mt-2 text-xs text-destructive">
              {errorMessage(replaySetup.error)}
            </p>
          )}
        </div>
      </ScalpingCharts>
      <div className="grid items-start gap-3 min-[900px]:grid-cols-[minmax(0,1fr)_310px] min-[1400px]:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-3">
          <Card className="gap-0 py-0">
            <CardContent className="p-3 space-y-3">
              <div className="flex justify-between items-center">
                <h3 className="font-semibold">Strikes · CE / PE</h3>
                <Button
                  variant="outline"
                  disabled={count >= 20}
                  onClick={() => setCount(Math.min(count + 4, 20))}
                >
                  More strikes
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Choose above or scroll this list · centred on your strike.
              </p>
              <div ref={strikeListRef} className="max-h-72 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 z-10 bg-card">
                    <tr className="border-b">
                      <th className="p-2 text-left">Call · Buy CE</th>
                      <th className="p-2">Strike</th>
                      <th className="p-2 text-left">Put · Buy PE</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d?.chain?.chain.map((row) => (
                      <tr
                        key={row.strike}
                        data-strike={row.strike}
                        className={`border-b ${focusedRow?.strike === row.strike ? 'bg-primary/5' : ''}`}
                      >
                        <td className="p-1">
                          <LegButton
                            leg={row.ce}
                            selected={selected}
                            select={(symbol) => {
                              setStrikeChoice(String(row.strike))
                              selectContract(symbol)
                            }}
                            q={
                              row.ce
                                ? quote(row.ce.symbol, exchange, {
                                    ltp: row.ce.ltp,
                                    bid: row.ce.bid,
                                    ask: row.ce.ask,
                                    time: d.chain_time || 0,
                                  })
                                : undefined
                            }
                            now={now}
                          />
                        </td>
                        <td className="p-2 text-center font-medium tabular-nums">
                          {row.strike}
                          {d.chain?.atm_strike === row.strike && (
                            <span className="block text-xs text-muted-foreground">ATM</span>
                          )}
                        </td>
                        <td className="p-1">
                          <LegButton
                            leg={row.pe}
                            selected={selected}
                            select={(symbol) => {
                              setStrikeChoice(String(row.strike))
                              selectContract(symbol)
                            }}
                            q={
                              row.pe
                                ? quote(row.pe.symbol, exchange, {
                                    ltp: row.pe.ltp,
                                    bid: row.pe.bid,
                                    ask: row.pe.ask,
                                    time: d.chain_time || 0,
                                  })
                                : undefined
                            }
                            now={now}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!expiry && (
                <p className="text-sm text-muted-foreground">
                  Choose an expiry to show actual available strike prices.
                </p>
              )}
            </CardContent>
          </Card>
          <ManualTrackingTicket
            controller={manualTracking}
            leg={(selected.endsWith('PE') ? focusedRow?.pe : focusedRow?.ce) || null}
            exchange={exchange}
            interval={interval}
            quote={quote(selected, exchange)}
          />
        </div>
        <div className="min-w-0 space-y-3">
          <TradingTicketView controller={activeTicket} />
        </div>
      </div>
      <ManagedTrades
        trades={trades}
        interval={interval}
        trackingCount={manualTracking.rows.filter((r) => !r.closed).length + brokerPositions.length}
        brokerage={d?.settings.brokerage ?? 10}
        refresh={refresh}
        quote={(t) => quote(t.symbol, t.exchange, t.quote)}
      >
        <BrokerPositions
          data={brokerMonitor.data}
          error={brokerMonitor.error ? errorMessage(brokerMonitor.error) : undefined}
          trades={trades}
          interval={interval}
          now={now}
          brokerage={d?.settings.brokerage ?? 10}
          quote={(p) =>
            quote(p.symbol, p.exchange, {
              ltp: Number(p.ltp) || undefined,
              time: brokerMonitor.data?.book_time || 0,
              source: 'Broker snapshot',
            })
          }
        />
        <ManualTrackedTrades
          controller={manualTracking}
          interval={interval}
          brokerage={d?.settings.brokerage ?? 10}
        />
      </ManagedTrades>
      {d && <OtherPositions desk={d} refresh={refresh} />}
      <TradeTracking trades={d?.trades || NO_TRADES} mode={mode} />
      <details className="rounded-lg border p-4">
        <summary className="cursor-pointer font-medium">Risk settings & journal</summary>
        <p className="mt-3 text-xs text-muted-foreground">
          Rupee limits are optional. Leave a limit blank to use your selected lots and trade levels.
          Any limits you set still apply. Trade-count and loss-streak guidance does not block manual
          Buy.
        </p>
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          {(
            [
              'risk',
              'daily_loss',
              'giveback',
              'premium',
              'spread',
              'slippage',
              'brokerage',
              'cooldown',
            ] as const
          ).map((k) => (
            <label key={k} className="text-sm">
              {
                {
                  risk: 'Risk per trade ₹',
                  daily_loss: 'Daily loss limit ₹',
                  giveback: 'Profit giveback ₹',
                  premium: 'Premium allocation ₹',
                  spread: 'Maximum spread %',
                  slippage: 'Exit slippage ₹/unit',
                  brokerage: 'Brokerage ₹/order',
                  cooldown: 'Loss cooldown seconds',
                }[k]
              }
              <Input
                type="number"
                min="0"
                step="any"
                value={risk[k] ?? ''}
                onChange={(e) =>
                  setRisk({ ...risk, [k]: e.target.value === '' ? null : Number(e.target.value) })
                }
              />
            </label>
          ))}
          <label className="text-sm">
            Intraday square-off IST
            <Input
              type="time"
              value={risk.cutoff}
              max="15:15"
              onChange={(e) => setRisk({ ...risk, cutoff: e.target.value })}
            />
          </label>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button disabled={saving} onClick={save}>
            {saving ? 'Saving…' : 'Save risk settings'}
          </Button>
          <label className="text-sm">
            Journal date
            <Input
              type="date"
              value={journalDate}
              onChange={(e) => setJournalDate(e.target.value)}
            />
          </label>
          <a
            className="text-sm underline"
            href={`/kotak-assistant/api/journal?date=${encodeURIComponent(journalDate)}`}
          >
            Download trading journal CSV
          </a>
          <span role="status" className="text-sm">
            {notice}
          </span>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Stops can slip or remain unfilled through gaps. The server must remain connected for
          targets and trailing management. A broker stop is separate from the entry and has DAY
          validity.
        </p>
      </details>
    </section>
  )
}
function LegButton({
  leg,
  selected,
  select,
  q,
  now,
}: {
  leg: Leg | null
  selected: string
  select: (s: string) => void
  q?: Quote
  now: number
}) {
  if (!leg) return <span className="text-xs">Unavailable</span>
  return (
    <button
      type="button"
      aria-pressed={selected === leg.symbol}
      title={`${leg.symbol} · ${leg.lotsize}/lot · Volume ${leg.volume || 'unavailable'} · OI ${leg.oi || 'unavailable'}`}
      className={`w-full rounded p-2 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary ${selected === leg.symbol ? 'bg-primary/15 ring-1 ring-primary' : 'hover:bg-muted'}`}
      onClick={() => select(leg.symbol)}
    >
      <strong>{money(q?.ltp)}</strong>
      <span className="block text-[11px] text-muted-foreground">
        Bid {money(q?.bid)} / Ask {money(q?.ask)}
      </span>
      <span className="block text-[11px] text-muted-foreground">
        {q?.time ? `${Math.max(0, Math.floor(now - q.time))}s ago` : 'No quote'}
      </span>
    </button>
  )
}
