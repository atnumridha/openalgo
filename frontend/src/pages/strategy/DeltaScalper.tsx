import { useBrokerCurrencyFormatter } from '@/hooks/useBrokerCurrencyFormatter'
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { ArrowLeft, Play, Pause, Square, RotateCw } from 'lucide-react'
import { webClient } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import Chart from './delta/Chart'
import TradeDetails from './delta/TradeDetails'
import { candleAnalysisFresh, paperDayStart } from './delta/viewData'
import ResearchPanel from './delta/ResearchPanel'
import {
  num,
  when,
  type Snapshot,
  type Observation,
  type Models,
  type Research,
  type Amount,
} from './delta/types'

const errorText = (e: unknown) =>
  (e as { response?: { data?: { error?: string } } })?.response?.data?.error ||
  'View unavailable. Refresh before relying on displayed data.'
function Choice({
  label,
  value,
  onChange,
  options,
  disabled = false,
}: {
  label: string
  value: string
  onChange: (s: string) => void
  options: [string, string, boolean?][]
  disabled?: boolean
}) {
  return (
    <label className="grid gap-2 text-sm font-medium">
      {label}
      <select
        className="h-10 rounded-md border border-input bg-background px-3 text-sm disabled:opacity-50"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        {options.map(([key, title, blocked]) => (
          <option value={key} key={key} disabled={blocked}>
            {title}
          </option>
        ))}
      </select>
    </label>
  )
}
function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-lg tabular-nums">{value}</CardTitle>
      </CardHeader>
    </Card>
  )
}
function Rows({ rows, fields }: { rows: Record<string, Amount>[]; fields: [string, string][] }) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            {fields.map(([k, label]) => (
              <TableHead key={k}>{label}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {!rows.length && (
            <TableRow>
              <TableCell colSpan={fields.length} className="h-20 text-center text-muted-foreground">
                No records
              </TableCell>
            </TableRow>
          )}
          {rows.map((row, i) => (
            <TableRow key={i}>
              {fields.map(([k]) => (
                <TableCell key={k}>{row[k] == null ? '—' : String(row[k])}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
export default function DeltaScalper() {
  const display = useBrokerCurrencyFormatter('deltaexchange')
  const money = (value: Amount) => value == null ? 'Unavailable' : display(Number(value))
  const cache = useQueryClient()
  const [profile, setProfile] = useState('historical'),
    [provider, setProvider] = useState('codex'),
    [model, setModel] = useState(''),
    [reasoning, setReasoning] = useState(''),
    [decision, setDecision] = useState('ai'),
    [duration, setDuration] = useState('continuous'),
    [tab, setTab] = useState(
      new URLSearchParams(window.location.search).get('tab') === 'pnl' ? 'pnl' : 'overview'
    ),
    [timeframe, setTimeframe] = useState('one'),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('')
  const query = <T,>(view: string, interval: number, enabled = true) => ({
    queryKey: ['delta-desk', view, profile],
    queryFn: async (): Promise<T> =>
      (await webClient.get(`/delta-desk/api/${view}`, { params: { profile } })).data,
    refetchInterval: interval,
    enabled,
    retry: 1,
  })
  const status = useQuery(query<Snapshot>('status', 3000)),
    obs = useQuery(query<Observation>('observation', 15000)),
    models = useQuery(query<Models>('models', 30000)),
    research = useQuery(query<Research>('research', 60000))
  const stream = useQuery(
    query<{
      stream: {
        answer: string
        phase: string
        first_token_seconds: number
        elapsed_seconds: number
        updated_at: number
      } | null
    }>('stream', 1000, tab === 'overview' && status.data?.ai_settings.provider === 'ollama')
  )
  const x = status.data,
    s = x?.status,
    r = x?.report,
    p = s?.position,
    view = obs.data,
    a = view?.account
  const accountFresh = !!(
    view?.account_fresh &&
    !obs.error &&
    a &&
    Date.now() / 1000 - a.asof <= 45
  )
  const marketFresh = candleAnalysisFresh(view, !!obs.error)
  const active = !!(s?.process_alive || s?.starting || s?.running),
    blocked = busy || !x || !!status.error
  const pendingStop = x?.pending_command?.action === 'stop'
  const label = status.error
    ? 'UNAVAILABLE'
    : !x
      ? 'LOADING'
      : s?.starting
        ? 'STARTING'
        : pendingStop
          ? 'STOPPING'
          : s?.paused
            ? 'PAUSED'
            : s?.running
              ? 'RUNNING'
              : active
                ? 'INTERRUPTED'
                : 'STOPPED'
  const efforts =
    provider === 'ollama'
      ? ['off', 'on']
      : models.data?.codex[model]?.reasoning || ['low', 'medium', 'high', 'xhigh']
  async function control(action: string) {
    setBusy(true)
    setNotice('')
    try {
      const response = await webClient.post('/delta-desk/api/control', {
        action,
        mode: 'paper',
        profile,
        ...(action === 'start'
          ? {
              minutes: duration === 'continuous' ? null : Number(duration),
              settings: {
                provider,
                model: model || null,
                reasoning: reasoning || null,
                decision_mode: decision,
              },
            }
          : {}),
      })
      setNotice(
        `Request ${response.data.state}. ${action === 'stop' ? 'Wait for stopped, flat and no unresolved intents.' : 'Watch the acknowledged controller status.'}`
      )
      await cache.invalidateQueries({ queryKey: ['delta-desk', 'status'] })
    } catch (e) {
      setNotice(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const lines = () => {
    let paper = 0,
      live = 0
    return [
      {
        name: 'Paper net INR',
        color: '#26a69a',
        data: (x?.equity || [])
          .filter((v) => v.closed_at >= paperDayStart(s?.daily.day))
          .map((v) => ({
            time: Math.floor(v.closed_at),
            value: (paper += Number(v.net_usd) * 85),
          })),
      },
      {
        name: 'Live net INR',
        color: '#2962ff',
        data:
          accountFresh && a?.complete
            ? a.equity_changes.map((v) => ({
                time: Math.floor(v.at),
                value: (live += Number(v.change) * 85),
              }))
            : [],
      },
    ]
  }
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            to="/strategy"
            className="mb-2 inline-flex items-center gap-1 text-sm text-muted-foreground"
          >
            <ArrowLeft className="size-4" />
            Strategies
          </Link>
          <h1 className="text-2xl font-bold">Delta AI scalper</h1>
          <p className="text-sm text-muted-foreground">
            BTCUSD · Continuous paper trading · Python risk management · ₹85 / USD
          </p>
        </div>
        <Badge variant={s?.running && !s?.paused ? 'default' : 'secondary'}>{label}</Badge>
      </header>
      {status.error && (
        <Alert variant="destructive">
          <AlertTitle>Status unavailable</AlertTitle>
          <AlertDescription>{errorText(status.error)}</AlertDescription>
        </Alert>
      )}
      {s?.paused && (
        <Alert>
          <AlertTitle>Entries paused</AlertTitle>
          <AlertDescription>
            {s.pause_reason?.replaceAll('_', ' ')}
            {s.daily.halted ? ' · Daily halt remains active.' : ''} Existing protection continues
            while the controller runs.
          </AlertDescription>
        </Alert>
      )}
      {!!s?.unresolved_intents.length && (
        <Alert variant="destructive">
          <AlertTitle>Reconciliation required</AlertTitle>
          <AlertDescription>
            {s.unresolved_intents.length} unresolved intents. Reconcile before restarting.
          </AlertDescription>
        </Alert>
      )}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Metric label="Paper cash" value={money(x?.paper_balance.cash_usd)} />
        <Metric label="Paper realized net · all runs" value={money(r?.net_usd)} />
        <Metric label="Paper fees · closed trades" value={money(r?.fees_usd)} />
        <Metric
          label="Paper open net estimate"
          value={!x ? 'Unavailable' : p ? money(p.net_estimate) : money(0)}
        />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Run controls</CardTitle>
          <CardDescription>
            Uses the existing Delta controller and ledger. This page always controls paper,
            independently of OpenAlgo’s global Analyze / Live setting.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <Choice
              label="Risk profile"
              value={profile}
              onChange={(v) => {
                setProfile(v)
                setNotice('')
              }}
              options={[
                ['historical', 'Historical · paper only'],
                ['baseline', 'Baseline'],
              ]}
            />
            <Choice
              label="AI provider"
              value={provider}
              onChange={(v) => {
                setProvider(v)
                setModel(v === 'ollama' ? 'deepseek-r1:1.5b' : '')
                setReasoning(v === 'ollama' ? 'off' : '')
              }}
              disabled={active || busy}
              options={[
                ['codex', 'Codex CLI'],
                ['ollama', 'Local DeepSeek · Ollama'],
              ]}
            />
            <Choice
              label="Model for next run"
              value={model}
              onChange={(v) => {
                setModel(v)
                setReasoning(provider === 'ollama' ? 'off' : '')
              }}
              disabled={active || busy}
              options={
                provider === 'codex'
                  ? [
                      ['', 'Configured CLI default'],
                      ...Object.entries(models.data?.codex || {}).map(
                        ([k, v]): [string, string] => [k, v.name]
                      ),
                    ]
                  : [
                      ['deepseek-r1:1.5b', 'DeepSeek R1 1.5B'],
                      ...(models.data?.local.models || [])
                        .filter((m) => m.name !== 'deepseek-r1:1.5b')
                        .map((m): [string, string, boolean] => [
                          m.name,
                          m.selectable ? m.name : `${m.name} · research only`,
                          !m.selectable,
                        ]),
                    ]
              }
            />
            <Choice
              label={provider === 'ollama' ? 'Local inference mode' : 'Reasoning for next run'}
              value={reasoning}
              onChange={setReasoning}
              disabled={active || busy}
              options={[
                ['', 'Provider default'],
                ...efforts.map((e): [string, string] => [
                  e,
                  e === 'off' ? 'Fast JSON' : e === 'on' ? 'Extended reasoning' : e,
                ]),
              ]}
            />
            <Choice
              label="Decision mode"
              value={decision}
              onChange={setDecision}
              disabled={active || busy}
              options={[
                ['ai', 'AI chooses trades, exits and tighter SL'],
                ['filter', 'EMA strategy with AI approval'],
              ]}
            />
            <Choice
              label="Run duration"
              value={duration}
              onChange={setDuration}
              disabled={active || busy}
              options={[
                ['continuous', 'Continuous · until stopped'],
                ['30', '30 minutes'],
                ['120', '2 hours'],
                ['480', '8 hours'],
              ]}
            />
          </div>
          <p className="text-sm">
            {profile === 'historical'
              ? '$10 trade loss · $35 margin · $5,500 notional · $20 daily loss · 200×/100×/50×'
              : '$1 trade loss · $5 margin · $1,000 notional · $3 daily loss · 200×'}
            . Fees, slippage and liquidation checks apply. Three consecutive losses halt entries.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => control('start')}
              disabled={
                blocked ||
                active ||
                s?.paused ||
                s?.daily.halted ||
                !!s?.unresolved_intents.length ||
                !!p ||
                !x?.paper_balance.ready
              }
            >
              <Play className="mr-2 size-4" />
              Start paper
            </Button>
            <Button
              variant="outline"
              onClick={() => control('pause')}
              disabled={blocked || !active || s?.paused || pendingStop}
            >
              <Pause className="mr-2 size-4" />
              Pause entries
            </Button>
            <Button
              variant="outline"
              onClick={() => control('resume')}
              disabled={blocked || (!s?.paused && !s?.daily.halted) || pendingStop}
            >
              <RotateCw className="mr-2 size-4" />
              Resume entries
            </Button>
            <Button
              variant="destructive"
              onClick={() => control('stop')}
              disabled={blocked || !active || pendingStop}
            >
              <Square className="mr-2 size-4" />
              Stop paper
            </Button>
          </div>
          {notice && (
            <p role="status" className="text-sm">
              {notice}
            </p>
          )}
          {!x?.paper_balance.ready && (
            <p className="text-sm text-amber-600">
              {x?.paper_balance.reason || 'Waiting for the paper ledger.'}
            </p>
          )}
          <div className="border-t pt-3 text-sm">
            <p>
              Active / last run: {x?.ai_settings.provider || '—'} ·{' '}
              {x?.ai_settings.model || 'configured default'} ·{' '}
              {x?.ai_settings.reasoning || 'default reasoning'} · {x?.decision_mode || '—'}
            </p>
            <p className="text-muted-foreground">
              Heartbeat {when(s?.runtime.heartbeat)} · Last candle scan {when(s?.last_scan?.at)} ·
              Prices {x?.feed_fresh ? 'fresh' : 'stale / disconnected'} · MCP{' '}
              {x?.mcp_fresh ? 'fresh' : 'stale / unavailable'}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Closing this page leaves the controller running. Keep the Mac awake. Stop is a
              request; verify flat and no unresolved intents. Settings above apply to the next run.
            </p>
          </div>
        </CardContent>
      </Card>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="mb-4 flex h-auto flex-wrap justify-start">
          <TabsTrigger value="overview">Market & AI</TabsTrigger>
          <TabsTrigger value="pnl">Live / paper P&L</TabsTrigger>
          <TabsTrigger value="research">Models & training</TabsTrigger>
          <TabsTrigger value="history">Runs & activity</TabsTrigger>
          <TabsTrigger value="readiness">Live readiness</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>BTCUSD · live analysis</CardTitle>
              <CardDescription>
                {marketFresh
                  ? 'Fresh market data and completed candles'
                  : 'Market data or candle analysis stale / loading'}{' '}
                · {when(view?.market?.asof)}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {(obs.error || view?.market_error) && (
                <p className="text-destructive">
                  {obs.error ? errorText(obs.error) : view?.market_error}
                </p>
              )}
              <Choice
                label="Candle interval"
                value={timeframe}
                onChange={setTimeframe}
                options={[
                  ['one', '1 minute · EMA9'],
                  ['five', '5 minutes · EMA20 / EMA50'],
                ]}
              />
              {view?.market && (
                <Chart
                  key={timeframe}
                  candles={timeframe === 'one' ? view.market.one : view.market.five}
                  levels={
                    p
                      ? { 'Paper entry': p.entry, 'Paper SL': p.ack_stop, 'Paper target': p.target }
                      : {}
                  }
                />
              )}
              <p className="text-sm">
                5m trend: {marketFresh ? view?.market?.analysis.trend : 'stale / unavailable'} ·
                EMA20 slope: {marketFresh ? view?.market?.analysis.ema20_slope : '—'} · ATR14:{' '}
                {num(marketFresh ? view?.market?.analysis.atr14_1m : null)}. Decisions use completed
                candles; chart refreshes every 15 seconds. Trading controls use the controller’s
                live feed.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>AI decision & stop management</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Badge variant="outline">
                {s?.runtime.ai_pending
                  ? 'Evaluating'
                  : x?.last_ai_analysis?.action.toUpperCase() || 'Waiting for a decision'}
              </Badge>
              <p>
                {x?.last_ai_analysis?.reason || s?.last_scan?.reason || 'No decision recorded.'}
              </p>
              <p className="text-xs text-muted-foreground">
                {when(x?.last_ai_analysis?.at)} · {x?.last_ai_analysis?.state} ·{' '}
                {x?.last_ai_analysis?.execution_reason}
              </p>
              <p>
                AI proposed SL {num(x?.last_ai_analysis?.proposed_stop)} · Acknowledged SL{' '}
                {num(p?.ack_stop)} · Peak net {money(p?.peak)}
              </p>
              {stream.data?.stream && (
                <div className="rounded-md border p-3">
                  <p className="text-sm">
                    Local output · {stream.data.stream.phase} · First output{' '}
                    {num(stream.data.stream.first_token_seconds, ' s')} · Elapsed{' '}
                    {num(stream.data.stream.elapsed_seconds, ' s')}
                  </p>
                  <pre className="max-h-44 overflow-auto whitespace-pre-wrap text-xs">
                    {stream.data.stream.answer}
                  </pre>
                  <p className="text-xs text-muted-foreground">
                    Partial output is display only. Only a complete validated decision can affect
                    the controller.
                  </p>
                </div>
              )}
              <p className="text-sm text-muted-foreground">
                AI can request entries, exits and tighter stops. Python enforces fees, sizing,
                monotonic stops and the 29-minute deadline. No valid timely decision means HOLD.
              </p>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="pnl" className="space-y-4">
          <TradeDetails report={a?.trade_report} fresh={accountFresh} />
          <div className="grid gap-4 md:grid-cols-2">
            <Metric label="Paper realized today" value={money(s?.daily.net)} />
            <Metric
              label="Live account trading result today"
              value={money(accountFresh && a?.complete ? a.net_usd : null)}
            />
            <Metric
              label="Live unrealized gross"
              value={money(accountFresh ? a?.unrealized_gross_usd : null)}
            />
            <Metric label="Live fees today" value={money(accountFresh ? a?.fees_usd : null)} />
          </div>
          <p className="text-sm text-muted-foreground">
            Live is the entire Delta account for the India day, including manual trades. Open live
            P&L is gross; paper open P&L includes estimated costs. Separate ledgers · account
            snapshot {when(a?.asof)}.
          </p>
          {!accountFresh && (
            <Alert>
              <AlertTitle>Live account data unavailable or stale</AlertTitle>
              <AlertDescription>{view?.account_error || errorText(obs.error)}</AlertDescription>
            </Alert>
          )}
          {a?.issues?.map((v) => (
            <p key={v} className="text-amber-600">
              {v}
            </p>
          ))}
          <Card>
            <CardHeader>
              <CardTitle>Today’s net P&L · INR</CardTitle>
            </CardHeader>
            <CardContent>
              <Chart lines={lines()} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Paper performance</CardTitle>
              <CardDescription>
                {r?.trades ?? 0} completed market-paper trades. Synthetic scenarios and model
                evaluation are excluded.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 md:grid-cols-3">
                {[
                  ['Win rate', num(r?.win_rate_percent, '%')],
                  ['Net expectancy', money(r?.net_expectancy_usd)],
                  ['Max drawdown', money(r?.max_drawdown_usd)],
                  ['Mean hold', num(r?.mean_holding_seconds, ' s')],
                  ['Maker fill rate', num(r?.entry_maker_fill_rate_percent, '%')],
                  ['REST ack median', num(r?.rest_ack_median_ms, ' ms')],
                ].map(([k, v]) => (
                  <div key={k}>
                    <p className="text-xs text-muted-foreground">{k}</p>
                    <p>{v}</p>
                  </div>
                ))}
              </div>
              <Rows
                rows={r?.trade_details || []}
                fields={[
                  ['side', 'Side'],
                  ['contracts', 'Contracts'],
                  ['gross_usd', 'Gross USD'],
                  ['fees_usd', 'Fees USD'],
                  ['net_usd', 'Net USD'],
                  ['net_inr', 'Net INR'],
                  ['close_reason', 'Exit reason'],
                ]}
              />
            </CardContent>
          </Card>
          {a && (
            <Card>
              <CardHeader>
                <CardTitle>Live account · read only</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <p>
                  Available {money(a.available_usd)} · Cash fees {money(a.cash_fees_usd)} · Fee
                  credits used {money(a.credits_used_usd)} · Promotional awards{' '}
                  {money(a.promo_credits_usd)} · Funding {money(a.funding_usd)}
                </p>
                <Rows
                  rows={a.positions}
                  fields={[
                    ['symbol', 'Position'],
                    ['contracts', 'Contracts'],
                    ['entry', 'Entry'],
                    ['mark', 'Mark'],
                    ['liquidation', 'Liquidation'],
                  ]}
                />
                <Rows
                  rows={a.orders}
                  fields={[
                    ['product_symbol', 'Order'],
                    ['side', 'Side'],
                    ['state', 'State'],
                    ['size', 'Quantity'],
                    ['limit_price', 'Limit'],
                    ['stop_price', 'Stop'],
                  ]}
                />
              </CardContent>
            </Card>
          )}
        </TabsContent>
        <TabsContent value="research">
          {research.error ? (
            <Alert variant="destructive">
              <AlertDescription>{errorText(research.error)}</AlertDescription>
            </Alert>
          ) : (
            <ResearchPanel data={research.data} models={models.data} />
          )}
        </TabsContent>
        <TabsContent value="history" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Runs · latest 50</CardTitle>
            </CardHeader>
            <CardContent>
              <Rows
                rows={(x?.runs || []).map((v) => ({
                  started: when(v.started),
                  state: v.state,
                  trades: v.trades,
                  net: money(v.net_usd),
                  provider: v.ai.provider || 'codex',
                  model: v.ai.model || 'default',
                }))}
                fields={[
                  ['started', 'Started'],
                  ['state', 'State'],
                  ['trades', 'Trades'],
                  ['net', 'Net'],
                  ['provider', 'AI provider'],
                  ['model', 'Model'],
                ]}
              />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Rejected signals & recent activity</CardTitle>
            </CardHeader>
            <CardContent>
              <Rows
                rows={Object.entries(x?.rejected_reasons || {}).map(([reason, count]) => ({
                  reason,
                  count,
                }))}
                fields={[
                  ['reason', 'Rejection reason'],
                  ['count', 'Count'],
                ]}
              />
              <div className="mt-4 max-h-[420px] overflow-auto">
                {x?.events.map((e) => (
                  <div key={e.id} className="border-b py-2">
                    <p className="text-xs text-muted-foreground">
                      {when(e.ts)} · {e.kind}
                    </p>
                    <p className="text-sm">
                      {String(
                        e.value.reason || e.value.action || e.value.error_type || 'Status updated'
                      )}
                    </p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="readiness">
          <Card>
            <CardHeader>
              <CardTitle>Live execution readiness</CardTitle>
              <CardDescription>OpenAlgo integration does not enable live orders.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <p>
                Selected profile:{' '}
                {x?.readiness.profile_supported
                  ? 'Baseline supported'
                  : 'Historical remains paper only'}
              </p>
              <p>
                Rotated execution credentials:{' '}
                {x?.readiness.credentials_ready ? 'configured' : 'required'}
              </p>
              <p>
                Current-build testnet qualification:{' '}
                {x?.readiness.qualification_ready ? 'passed' : 'required'}
              </p>
              <p>
                Remaining:{' '}
                {x?.readiness.missing?.join(', ') ||
                  'Inspect the live doctor for current preflight checks.'}
              </p>
              <p className="text-sm text-muted-foreground">
                Live requires attached-stop activation, partial-fill protection, replacement-stop
                handover, amendments, reduce-only closure, exchange preflight and explicit CLI
                arming. Read-only account access and model training do not satisfy these checks.
                Fyers, Kotak Neo and US-stock execution need their own broker adapters and risk
                rules.
              </p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
