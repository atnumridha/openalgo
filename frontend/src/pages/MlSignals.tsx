import { Activity, BrainCircuit, Database, Loader2, RefreshCw, TrendingUp } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  type MlAction,
  type MlClosedTrade,
  type MlCoverage,
  type MlJobStatus,
  type MlLiveSignal,
  type MlLiveSource,
  type MlMode,
  type MlModel,
  type MlOpenTrade,
  type MlSuggestion,
  mlSignalsApi,
} from '@/api/mlSignals'
import { MlSettingsCard } from '@/components/ml/MlSettingsCard'
import { OpenTrades } from '@/components/ml/OpenTrades'
import { ModeSelect, SuggestionCard } from '@/components/ml/TradePanel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useMlLive, useSecondClock } from '@/hooks/useMlLive'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

const INTERVALS = ['1m', '3m', '5m', '15m']
const STATUS_POLL_MS = 10_000
const STATUS_POLL_BUSY_MS = 2000
const STATIC_POLL_MS = 60_000
const TRADES_POLL_MS = 2000

const ACTION_COLOR: Record<MlAction, string> = {
  LONG: 'text-green-600',
  SHORT: 'text-red-600',
  WAIT: 'text-muted-foreground',
}

function number(value: unknown, digits = 2) {
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue.toFixed(digits) : '-'
}

function percent(value: number | undefined) {
  return value == null || !Number.isFinite(value) ? '-' : `${(value * 100).toFixed(1)}%`
}

function clockTime(seconds: number | undefined | null, withSeconds = false) {
  if (seconds == null) return '-'
  return new Date(seconds * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
  })
}

function countdown(seconds: number) {
  const whole = Math.max(0, Math.ceil(seconds))
  const minutes = Math.floor(whole / 60)
  return `${String(minutes).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`
}

function ago(seconds: number | null | undefined) {
  if (seconds == null || !Number.isFinite(seconds)) return '-'
  if (seconds < 1) return 'just now'
  if (seconds < 90) return `${Math.round(seconds)}s ago`
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`
  return `${Math.round(seconds / 3600)}h ago`
}

function ProbabilityRow({
  label,
  value,
  threshold,
  barClass,
}: {
  label: string
  value: number | undefined
  threshold?: number
  barClass: string
}) {
  const width = value == null || !Number.isFinite(value) ? 0 : Math.min(100, value * 100)
  return (
    <div className="grid grid-cols-[3.5rem_1fr_3.5rem] items-center gap-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <div className="relative h-2 rounded bg-muted">
        <div
          className={cn('h-2 rounded transition-all', barClass)}
          style={{ width: `${width}%` }}
        />
        {threshold != null && (
          <div
            className="absolute top-[-3px] h-[14px] w-px bg-foreground/50"
            style={{ left: `${threshold * 100}%` }}
          />
        )}
      </div>
      <span className="text-right font-mono">{percent(value)}</span>
    </div>
  )
}

function liveSourceText(source: MlLiveSource | undefined) {
  if (!source) return { text: '-', className: 'text-muted-foreground' }
  switch (source.status) {
    case 'ok':
      return { text: `Live · ${ago(source.age_seconds)}`, className: 'text-green-600' }
    case 'catching_up':
      return { text: 'Catching up', className: 'text-amber-600' }
    case 'error':
      return { text: source.message || 'Retrying', className: 'text-red-600' }
    default:
      return {
        text: source.age_seconds == null ? 'Waiting' : `No update for ${ago(source.age_seconds)}`,
        className: 'text-amber-600',
      }
  }
}

export default function MlSignals() {
  const [symbol, setSymbol] = useState('BTCUSD')
  const [symbols, setSymbols] = useState<string[]>(['BTCUSD', 'ETHUSD', 'SOLUSD'])
  const [interval, setInterval] = useState('5m')
  const [mode, setMode] = useState<MlMode>('sandbox')
  const [suggestions, setSuggestions] = useState<MlSuggestion[]>([])
  const [openTrades, setOpenTrades] = useState<MlOpenTrade[]>([])
  const [closedTrades, setClosedTrades] = useState<MlClosedTrade[]>([])
  const [coverage, setCoverage] = useState<MlCoverage | null>(null)
  const [models, setModels] = useState<MlModel[]>([])
  const [status, setStatus] = useState<MlJobStatus>({
    busy: false,
    job: null,
    progress: 0,
    message: 'idle',
  })
  const [labels, setLabels] = useState<Record<string, unknown> | null>(null)
  const [searchResult, setSearchResult] = useState<Record<string, unknown> | null>(null)
  const [stopPct, setStopPct] = useState('0.2')
  const [targetPct, setTargetPct] = useState('0.6')
  const [holdMinutes, setHoldMinutes] = useState('28')

  const { snapshot, clockOffset, unreachable } = useMlLive(interval, symbol)
  const nowMs = useSecondClock()
  const serverNow = nowMs / 1000 - clockOffset

  const loadStatic = useCallback(async () => {
    const [coverageData, modelData] = await Promise.all([
      mlSignalsApi.coverage().catch(() => null),
      mlSignalsApi.models(symbol).catch(() => ({ models: [] })),
    ])
    setCoverage(coverageData)
    setModels(modelData.models || [])
  }, [symbol])

  const loadStatus = useCallback(async () => {
    const statusData = await mlSignalsApi
      .status()
      .catch((): MlJobStatus => ({ busy: false, job: null, progress: 0, message: 'unavailable' }))
    setStatus(statusData)
    if (statusData.result && statusData.job === 'rule_search') setSearchResult(statusData.result)
  }, [])

  useEffect(() => {
    void loadStatic()
    void loadStatus()
    const timer = window.setInterval(() => void loadStatic(), STATIC_POLL_MS)
    return () => window.clearInterval(timer)
  }, [loadStatic, loadStatus])

  const loadTrading = useCallback(async () => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    const [suggestionData, tradeData] = await Promise.all([
      mlSignalsApi.suggestions(interval, mode).catch(() => null),
      mlSignalsApi.trades().catch(() => null),
    ])
    if (suggestionData) {
      setSuggestions(suggestionData)
      const listed = suggestionData.map((item) => item.symbol)
      if (listed.length) setSymbols(listed)
    }
    if (tradeData) {
      setOpenTrades(tradeData.open)
      setClosedTrades(tradeData.closed)
    }
  }, [interval, mode])

  useEffect(() => {
    void loadTrading()
    const timer = window.setInterval(() => void loadTrading(), TRADES_POLL_MS)
    return () => window.clearInterval(timer)
  }, [loadTrading])

  useEffect(() => {
    const timer = window.setInterval(
      () => void loadStatus(),
      status.busy ? STATUS_POLL_BUSY_MS : STATUS_POLL_MS
    )
    return () => window.clearInterval(timer)
  }, [status.busy, loadStatus])

  const wasBusy = useRef(false)
  useEffect(() => {
    if (wasBusy.current && !status.busy) void loadStatic()
    wasBusy.current = status.busy
  }, [status.busy, loadStatic])

  const afterStart = () => {
    void loadStatus()
    void loadStatic()
  }

  const refreshData = async () => {
    try {
      await mlSignalsApi.refresh(symbol)
      showToast.success('Saving the latest history for training has started')
      afterStart()
    } catch {
      showToast.error('Could not start saving history. Another job may be running.')
    }
  }
  const previewLabels = async () => {
    try {
      setLabels(
        await mlSignalsApi.labels({
          symbol,
          stop_pct: stopPct,
          target_pct: targetPct,
          hold_minutes: holdMinutes,
        })
      )
    } catch {
      showToast.error('Could not preview labels')
    }
  }
  const search = async () => {
    try {
      const response = await mlSignalsApi.search(symbol)
      setSearchResult(response.data?.data ?? null)
      showToast.success('Rule search started')
      afterStart()
    } catch {
      showToast.error('Could not start rule search')
    }
  }
  const train = async () => {
    try {
      await mlSignalsApi.retrain(symbol)
      showToast.success(`Saving history and retraining ${symbol} in the background`)
      afterStart()
    } catch {
      showToast.error('Could not start retraining')
    }
  }
  const activate = async (version: string) => {
    try {
      await mlSignalsApi.activate(version, symbol)
      showToast.success(`Activated ${version}`)
      void loadStatic()
    } catch {
      showToast.error('Could not activate model')
    }
  }

  const live = snapshot?.state === 'live' ? snapshot : null
  const liveSources = snapshot?.sources ?? {}
  const sourceNames = useMemo(() => {
    const names = Object.keys(snapshot?.sources ?? {})
    for (const name of Object.keys(coverage?.sources ?? {})) {
      if (!names.includes(name)) names.push(name)
    }
    return names
  }, [snapshot?.sources, coverage])
  const historyRefreshed = Object.values(coverage?.sources ?? {})[0]?.last_refresh
  const activeModel = models.find((model) => model.active)
  const drivers = Object.entries(live?.sentiment?.drivers ?? {}).sort(([a], [b]) =>
    a.localeCompare(b)
  )
  const sourcesTotal = Object.keys(liveSources).length
  const signalAge = live?.computed_at != null ? serverNow - live.computed_at : null

  const forming: MlLiveSignal | null | undefined = live?.forming
  const closed: MlLiveSignal | null | undefined = live?.closed

  let feedBadge: { text: string; className: string }
  if (unreachable) {
    feedBadge = { text: 'Server not answering, retrying', className: 'bg-red-500/10 text-red-600' }
  } else if (!live) {
    feedBadge = { text: 'Connecting', className: 'bg-amber-500/10 text-amber-600' }
  } else if (signalAge != null && signalAge > 10) {
    feedBadge = {
      text: `Delayed · ${ago(signalAge)}`,
      className: 'bg-amber-500/10 text-amber-600',
    }
  } else {
    feedBadge = { text: 'Live', className: 'bg-green-500/10 text-green-600' }
  }

  return (
    <div className="container mx-auto max-w-7xl space-y-6 py-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <BrainCircuit className="h-7 w-7 text-primary" />
            <h1 className="text-3xl font-bold">ML Signals</h1>
          </div>
          <p className="text-muted-foreground">
            LONG, SHORT or WAIT for each symbol, chosen by expected profit after Delta's fees. One
            click opens a trade that is then managed for you.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              'inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-medium',
              feedBadge.className
            )}
          >
            <span className="relative flex h-2 w-2">
              {feedBadge.text === 'Live' && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-500 opacity-60" />
              )}
              <span className="relative inline-flex h-2 w-2 rounded-full bg-current" />
            </span>
            {feedBadge.text}
          </span>
          <ModeSelect mode={mode} onChange={setMode} />
          <Select value={symbol} onValueChange={setSymbol}>
            <SelectTrigger className="w-28" aria-label="Symbol">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {symbols.map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={interval} onValueChange={setInterval}>
            <SelectTrigger className="w-24" aria-label="Signal interval">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {INTERVALS.map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-xl font-semibold">
            Suggestions · {interval} · {mode === 'live' ? 'Live' : 'Sandbox'}
          </h2>
          <span className="text-xs text-muted-foreground">
            From the last closed candle. Sized so the stop loses your risk %, fees included.
          </span>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {suggestions.length ? (
            suggestions.map((item) => (
              <SuggestionCard
                key={item.symbol}
                suggestion={item}
                mode={mode}
                nowSeconds={serverNow}
                onTraded={() => void loadTrading()}
              />
            ))
          ) : (
            <p className="text-muted-foreground">Waiting for the ML worker.</p>
          )}
        </div>
      </div>

      <OpenTrades open={openTrades} closed={closedTrades} onChanged={() => void loadTrading()} />

      <div className="grid gap-4 md:grid-cols-4">
        <Card className="md:col-span-2">
          <CardHeader className="pb-2">
            <CardDescription>
              Live signal · {symbol} {interval}
              {live?.price != null && (
                <span className="ml-2 font-mono text-foreground">{number(live.price, 1)}</span>
              )}
            </CardDescription>
            {!live ? (
              <div className="flex items-center gap-2 py-4 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                {snapshot?.feed || 'Starting the live feed.'}
              </div>
            ) : (
              <>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <CardTitle
                    className={cn('text-3xl', forming?.action && ACTION_COLOR[forming.action])}
                    data-testid="live-action"
                  >
                    {forming?.action ?? '-'}
                  </CardTitle>
                  {forming?.closes_at != null && (
                    <span className="text-sm text-muted-foreground">
                      Current {interval} candle closes in{' '}
                      <span className="font-mono text-foreground">
                        {countdown(forming.closes_at - serverNow)}
                      </span>
                    </span>
                  )}
                </div>
                {live.message && <p className="text-sm text-amber-600">{live.message}</p>}
              </>
            )}
          </CardHeader>
          {live && (
            <CardContent className="space-y-2">
              <ProbabilityRow label="LONG" value={forming?.p_long} barClass="bg-green-600" />
              <ProbabilityRow label="SHORT" value={forming?.p_short} barClass="bg-red-600" />
              <ProbabilityRow label="WAIT" value={forming?.p_wait} barClass="bg-muted-foreground" />
              <p className="pt-1 text-xs text-muted-foreground">
                Changes every second until the candle closes. A side is taken only when its expected
                profit after fees beats {number(forming?.min_edge_pct, 3)}%: LONG{' '}
                {number(forming?.ev_long_pct, 3)}%, SHORT {number(forming?.ev_short_pct, 3)}% now.
                Last closed candle ({clockTime(closed?.time)}):{' '}
                <span className={cn('font-medium', closed?.action && ACTION_COLOR[closed.action])}>
                  {closed?.action ?? '-'}
                </span>
                . Updated {ago(signalAge)}.
              </p>
            </CardContent>
          )}
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Sentiment ({interval})</CardDescription>
            <CardTitle
              className={cn(
                'text-2xl',
                live?.sentiment?.score == null
                  ? ''
                  : Number(live.sentiment.score) >= 0
                    ? 'text-green-600'
                    : 'text-red-600'
              )}
            >
              {live?.sentiment?.score == null ? '-' : Number(live.sentiment.score).toFixed(2)}
            </CardTitle>
            <CardDescription>
              {live
                ? `From ${live.sentiment?.sources_used ?? 0} signals across ${sourcesTotal} live feeds`
                : 'Waiting for live feeds'}
            </CardDescription>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Model</CardDescription>
            <CardTitle className="text-lg">{activeModel?.version || 'Not trained'}</CardTitle>
            <Badge variant={live?.model_promoted ? 'default' : 'secondary'}>
              {live?.model_promoted ? `Live allowed on ${interval}` : 'Sandbox only'}
            </Badge>
            {live?.promotion_reason && (
              <CardDescription className="pt-1 text-xs">{live.promotion_reason}</CardDescription>
            )}
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            Market sentiment drivers
          </CardTitle>
          <CardDescription>
            Live readings for the current {interval} candle, updated every second. A feed that has
            not reported stays out rather than being filled in.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {drivers.length ? (
              drivers.map(([key, value]) => (
                <div key={key} className="rounded border p-3">
                  <div className="text-xs text-muted-foreground">{key}</div>
                  <div
                    className={cn(
                      'font-mono font-semibold',
                      Number(value) >= 0 ? 'text-green-600' : 'text-red-600'
                    )}
                  >
                    {number(value, 3)}
                  </div>
                </div>
              ))
            ) : (
              <p className="text-muted-foreground">Waiting for live feeds.</p>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>
              <Database className="mr-2 inline h-5 w-5" />
              Data feeds
            </CardTitle>
            <CardDescription>
              Live status of each feed, and the history saved for training.
              {historyRefreshed
                ? ` History last saved ${new Date(String(historyRefreshed)).toLocaleTimeString()}.`
                : ' No history saved yet.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="max-h-96 space-y-1 overflow-auto">
              {sourceNames.length ? (
                sourceNames.map((key) => {
                  const liveSource = liveSources[key]
                  const saved = coverage?.sources?.[key]
                  const liveText = liveSourceText(liveSource)
                  return (
                    <div
                      key={key}
                      className="grid grid-cols-[1fr_auto] items-center gap-x-3 border-b py-2 text-sm"
                    >
                      <span>{liveSource?.label ?? key}</span>
                      <span className={cn('text-right text-xs', liveText.className)}>
                        {liveText.text}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {saved
                          ? `${number(saved.rows, 0)} rows · ${number(saved.span_days, 1)}d saved`
                          : 'No saved history'}
                      </span>
                      <span className="text-right">
                        {saved?.error ? (
                          <Badge variant="destructive">History incomplete</Badge>
                        ) : saved ? (
                          <Badge variant="secondary">History ready</Badge>
                        ) : null}
                      </span>
                    </div>
                  )
                })
              ) : (
                <p className="text-muted-foreground">No feeds yet.</p>
              )}
            </div>
            <Button className="mt-4" onClick={() => void refreshData()} disabled={status.busy}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Save latest history
            </Button>
            <p className="mt-2 text-xs text-muted-foreground">
              The live signal does not need this. It updates the saved year that training and rule
              search use.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>30-minute rule search</CardTitle>
            <CardDescription>
              Stop up to 0.2%, target up to 2%, 28-minute cap, sentiment filters, walk-forward and
              $100 account simulation.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <Label>Stop %</Label>
                <Input value={stopPct} onChange={(e) => setStopPct(e.target.value)} />
              </div>
              <div>
                <Label>Target %</Label>
                <Input value={targetPct} onChange={(e) => setTargetPct(e.target.value)} />
              </div>
              <div>
                <Label>Hold minutes</Label>
                <Input value={holdMinutes} onChange={(e) => setHoldMinutes(e.target.value)} />
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => void previewLabels()} disabled={status.busy}>
                Preview labels
              </Button>
              <Button onClick={() => void search()} disabled={status.busy}>
                <TrendingUp className="mr-2 h-4 w-4" />
                Run search
              </Button>
              <Button onClick={() => void train()}>
                <BrainCircuit className="mr-2 h-4 w-4" />
                Retrain {symbol} now
              </Button>
            </div>
            <div className="space-y-1">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Job</span>
                <span>
                  {status.busy
                    ? `${status.job} ${Math.round(status.progress * 100)}%`
                    : status.message}
                </span>
              </div>
              <Progress value={status.progress * 100} />
            </div>
            {labels && (
              <div className="grid grid-cols-3 gap-2 text-center text-sm">
                <div className="rounded bg-green-500/10 p-2">
                  LONG
                  <br />
                  <b>{String((labels.counts as Record<string, unknown>)?.LONG ?? '-')}</b>
                </div>
                <div className="rounded bg-red-500/10 p-2">
                  SHORT
                  <br />
                  <b>{String((labels.counts as Record<string, unknown>)?.SHORT ?? '-')}</b>
                </div>
                <div className="rounded bg-muted p-2">
                  WAIT
                  <br />
                  <b>{String((labels.counts as Record<string, unknown>)?.WAIT ?? '-')}</b>
                </div>
              </div>
            )}
            {status.error && <p className="text-sm text-red-600">{status.error}</p>}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <MlSettingsCard onSaved={() => void loadTrading()} />
        <Card>
          <CardHeader>
            <CardTitle>Model versions · {symbol}</CardTitle>
            <CardDescription>
              The newest model drives signals as soon as it is trained. Live trading on an interval
              unlocks only when that interval made money after fees on a period it never saw, more
              than random entries would one time in twenty.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {models.length ? (
                models.map((model) => (
                  <div
                    key={model.version}
                    className="flex flex-wrap items-center justify-between gap-3 rounded border p-3"
                  >
                    <div>
                      <b>{model.version}</b>
                      <div className="text-sm text-muted-foreground">
                        {model.promoted ? 'Live allowed' : 'Sandbox only'} ·{' '}
                        {String(model.promotion_reason || '')}
                      </div>
                    </div>
                    {model.active ? (
                      <Badge>Active</Badge>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void activate(model.version)}
                      >
                        Activate
                      </Button>
                    )}
                  </div>
                ))
              ) : (
                <p className="text-muted-foreground">No models trained.</p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {searchResult && (
        <Card>
          <CardHeader>
            <CardTitle>Search results</CardTitle>
            <CardDescription>
              {symbol}: {String(searchResult.settings ?? 0)} settings evaluated;{' '}
              {String(searchResult.candidate_count ?? 0)} passed both walk-forward windows.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="p-2">Timeframe</th>
                    <th className="p-2">Family</th>
                    <th className="p-2">Filter</th>
                    <th className="p-2">Test net %</th>
                    <th className="p-2">Win %</th>
                    <th className="p-2">Account end</th>
                    <th className="p-2">Promotable</th>
                  </tr>
                </thead>
                <tbody>
                  {(Array.isArray(searchResult.ranked) ? searchResult.ranked.slice(0, 20) : []).map(
                    (row, index) => {
                      const item = row as Record<string, unknown>
                      const test = (item.test || {}) as Record<string, unknown>
                      const account = (item.account || {}) as Record<string, unknown>
                      return (
                        <tr key={`${String(item.timeframe)}-${index}`} className="border-b">
                          <td className="p-2">{String(item.timeframe ?? '-')}</td>
                          <td className="p-2">{String(item.family ?? '-')}</td>
                          <td className="p-2">{String(item.filter ?? 'none')}</td>
                          <td
                            className={cn(
                              'p-2 font-mono',
                              Number(test.net_pct) >= 0 ? 'text-green-600' : 'text-red-600'
                            )}
                          >
                            {number(test.net_pct, 3)}%
                          </td>
                          <td className="p-2 font-mono">{number(test.win_pct, 1)}%</td>
                          <td className="p-2 font-mono">${number(account.end_usd, 2)}</td>
                          <td className="p-2">
                            {item.test_beats_random && item.train_beats_random ? (
                              <Badge>Candidate</Badge>
                            ) : (
                              <span className="text-muted-foreground">No</span>
                            )}
                          </td>
                        </tr>
                      )
                    }
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
      {status.busy && (
        <div className="flex items-center justify-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {status.message}
        </div>
      )}
      <div className="text-xs text-muted-foreground">
        Sandbox trades are sized from the Sandbox balance in settings; Live trades from your Delta
        USD balance. Every trade has a stop, a target and a break-even trail; Live trades also hold
        a stop on Delta in case OpenAlgo stops.
      </div>
    </div>
  )
}
