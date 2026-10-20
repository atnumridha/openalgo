import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { webClient } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  useBrokerCurrencyFormatter,
  useBrokerPriceFormatter,
} from '@/hooks/useBrokerCurrencyFormatter'
import type { TradingTerminal } from '@/lib/trading/terminal'

type Config = {
  mode: 'paper' | 'live'
  entry_mode: 'review' | 'auto'
  leverage: number
  max_quantity: number
  max_risk: number
  max_margin: number
  max_notional: number
  daily_loss: number
  max_trades: number
  slippage: number
  min_net_rr: number
  counter_atr: number
  expiry_bars: number
  shorts: boolean
  manual_level: number
  manual_target: number
  manual_side: 'Low' | 'High'
  max_hold_seconds: number
}
type Plan = {
  setup_id?: string
  blocked?: string
  entry?: number
  stop?: number
  target?: number
  quantity?: number
  net_risk?: number
  net_target?: number
  estimated_fees?: number
  partial_quantity?: number
  partial_target?: number
}
type Position = {
  risk?: string
  planned_net_target?: string
  side: string
  entry: string
  ack_stop?: string
  stop: string
  target: string
  open_qty: number
  filled: number
  qty: number
  partial_quantity?: number
  partial_target?: string
  net_estimate?: string
  protected?: boolean
}
type View = {
  plan_revision?: string
  asof?: number
  mode?: string
  status?: string
  message?: string
  plan?: Plan
  position?: Position
  candidate?: {
    stage: string
    direction: string
    trigger?: number
    reference?: { price: number; frame: string }
  }
  daily?: { entries: number; entry_limit: number; net: string; halted: boolean }
  execution_enabled?: boolean
}
type Snapshot = {
  view?: View
  position?: Position
  paused?: boolean
  command?: unknown
  unresolved?: number
  trades?: {
    id: string
    net: string
    side: string
    filled: number
    entry: string
    close_reason: string
  }[]
}
type Status = {
  configured: boolean
  running: boolean
  config: Config
  strategy_id: string
  paper: Snapshot
  live: Snapshot
}
const API = '/liquidity-strategy/api'
const stages: Record<string, string> = {
  FIRST_BUYER: 'Level touched · waiting for the first bounce',
  COUNTERATTACK: 'First bounce skipped · waiting for a counterattack',
  RENEWED_CONFIRMATION: 'Counterattack formed · waiting for renewed strength',
  WATCHING: 'Confirmation formed · watching the trigger',
  TRIGGERED: 'Price break observed',
  DATA_GAP: 'Data gap · waiting for a new setup',
  EXPIRED: 'Setup expired',
  NO_TARGET: 'No opposing liquidity target',
  INVALIDATED: 'Pattern invalidated',
  TARGET_TAKEN: 'Target already taken',
}
const errorText = (e: unknown) =>
  (e as { response?: { data?: { message?: string } } })?.response?.data?.message ||
  'Could not verify the strategy status.'

export function LiquidityStrategy({ target }: { target: () => TradingTerminal | null }) {
  const [open, setOpen] = useState(true),
    [draft, setDraft] = useState<Config | null>(null),
    [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState(''),
    [clock, setClock] = useState(Date.now())
  const cash = useBrokerCurrencyFormatter('deltaexchange'),
    price = useBrokerPriceFormatter('deltaexchange')
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: ['liquidity-strategy'],
    queryFn: async () => (await webClient.get<{ data: Status }>(API + '/status')).data.data,
    refetchInterval: 1000,
    retry: false,
  })
  const data = query.data,
    cfg = data?.config,
    snap = cfg ? data?.[cfg.mode] : undefined,
    v = snap?.view,
    p = v?.plan,
    pos = snap?.position
  const fresh = !!v?.asof && clock / 1000 - v.asof < 5 && clock / 1000 >= v.asof
  const chart = target()?.cryptoResearchSnapshot(),
    eligible = !!chart && !chart.replay
  const dirty = JSON.stringify(draft) !== JSON.stringify(cfg)
  useEffect(() => {
    if (cfg && !draft) setDraft(cfg)
  }, [cfg, draft])
  useEffect(() => {
    const id = setInterval(() => setClock(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  useEffect(() => {
    const terminal = target()
    if (!eligible || !fresh || !open) {
      terminal?.showLiquidityExecutionPlan(null)
      return
    }
    const entry = pos ? Number(pos.entry) : p?.entry,
      stop = pos ? Number(pos.ack_stop ?? pos.stop) : p?.stop,
      targetPrice = pos ? Number(pos.target) : p?.target
    terminal?.showLiquidityExecutionPlan(
      entry && stop && targetPrice
        ? { entry, stop, target: targetPrice, mode: cfg?.mode ?? 'paper' }
        : null
    )
  }, [clock, target, eligible, fresh, open, pos, p, cfg?.mode])
  useEffect(
    () => () => {
      target()?.showLiquidityExecutionPlan(null)
    },
    [target]
  )
  async function act(path: string, body: unknown) {
    setBusy(true)
    setMessage('')
    try {
      const response = await webClient.post(API + path, body)
      setMessage(response.data.message ?? 'Settings saved')
      await qc.invalidateQueries({ queryKey: ['liquidity-strategy'] })
    } catch (e) {
      setMessage(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const control = (action: string) =>
    act('/control', { mode: cfg?.mode, action, setup_id: p?.setup_id, revision: v?.plan_revision })
  const field = (key: keyof Config, label: string, step = 1) =>
    draft && (
      <label key={key} className="grid gap-1 text-xs">
        {label}
        <input
          type="number"
          step={step}
          min="0"
          className="h-10 w-full rounded border bg-background px-2 tabular-nums"
          value={Number.isFinite(draft[key]) ? Number(draft[key]) : ''}
          onChange={(e) =>
            setDraft({ ...draft, [key]: e.target.value === '' ? NaN : Number(e.target.value) })
          }
        />
      </label>
    )
  const amount = (n: number | undefined) => (n === undefined ? '—' : price(n))
  const validPlan =
    fresh &&
    !query.isError &&
    !p?.blocked &&
    !!p?.setup_id &&
    !!v?.plan_revision &&
    v?.execution_enabled &&
    !v?.daily?.halted
  return (
    <section aria-label="Liquidity strategy execution" className="shrink-0 border-t bg-background">
      <button
        className="flex min-h-11 w-full items-center justify-between gap-3 px-4 text-left text-sm font-medium hover:bg-accent"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span>
          Liquidity extra confirmation · BTCUSD{' '}
          <span className="ml-2 text-xs text-muted-foreground">
            {data?.running
              ? `${cfg?.mode.toUpperCase()} · ${fresh ? 'Monitoring' : 'Checking connection'}`
              : 'Not started'}
          </span>
        </span>
        <span>{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && (
        <div className="max-h-80 overflow-y-auto border-t px-4 py-3 text-sm">
          {query.isError && (
            <p role="alert" className="text-destructive">
              {errorText(query.error)}
            </p>
          )}
          {!data && !query.isError && <p>Loading strategy status…</p>}
          {data && (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <p className="font-semibold">
                  {pos
                    ? `${pos.side === 'buy' ? 'LONG' : 'SHORT'} · ${pos.open_qty} / ${pos.filled} contracts open`
                    : v?.candidate
                      ? (stages[v.candidate.stage] ?? v.candidate.stage)
                      : 'Waiting for a new 1H / 4H / 1D liquidity touch'}
                </p>
                {v?.candidate?.trigger && (
                  <span className="tabular-nums">
                    {v.candidate.direction === 'LONG' ? 'Buy above' : 'Sell below'}{' '}
                    {price(v.candidate.trigger)}
                  </span>
                )}
                {v?.daily && (
                  <span className="text-xs text-muted-foreground">
                    Entries {v.daily.entries}/{v.daily.entry_limit} · Day net{' '}
                    {cash(Number(v.daily.net))}
                  </span>
                )}
              </div>
              <div className="my-3 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
                {[
                  ['Entry', amount(pos ? Number(pos.entry) : p?.entry)],
                  ['Stop loss', amount(pos ? Number(pos.ack_stop ?? pos.stop) : p?.stop)],
                  ['Runner target', amount(pos ? Number(pos.target) : p?.target)],
                  ['Contracts', String(pos?.open_qty ?? p?.quantity ?? '—')],
                  [
                    'Planned net risk',
                    pos?.risk
                      ? cash(Number(pos.risk))
                      : p?.net_risk === undefined
                        ? '—'
                        : cash(p.net_risk),
                  ],
                  [
                    'Planned net reward',
                    pos?.planned_net_target
                      ? cash(Number(pos.planned_net_target))
                      : p?.net_target === undefined
                        ? '—'
                        : cash(p.net_target),
                  ],
                  [
                    'Net P&L',
                    pos?.net_estimate === undefined ? '—' : cash(Number(pos.net_estimate)),
                  ],
                ].map(([label, value]) => (
                  <div key={label} className="rounded border px-3 py-2">
                    <p className="text-xs text-muted-foreground">{label}</p>
                    <p className="mt-1 font-medium tabular-nums">{value}</p>
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                {(pos?.partial_quantity ?? p?.partial_quantity ?? 0) > 0
                  ? `Partial: ${pos?.partial_quantity ?? p?.partial_quantity} contracts at ${amount(pos?.partial_target ? Number(pos.partial_target) : p?.partial_target)}; then protect fee-adjusted breakeven.`
                  : 'One contract uses a single target. Split fills only when at least two contracts fill and the partial covers estimated costs.'}{' '}
                Net peak above $2: lock at least $1.50, then trail $0.50 behind. Stops tighten only.
              </p>
              {(p?.blocked || v?.message || message) && (
                <p role="status" className="my-2 text-sm">
                  {message || v?.message || p?.blocked}
                </p>
              )}
              {!eligible && (
                <p className="my-2 text-sm">
                  Entry controls require the live BTCUSD chart. Replay remains read-only.
                </p>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => setEditing(!editing)}>
                  {editing ? 'Hide settings' : 'Settings'}
                </Button>
                <Button
                  size="sm"
                  disabled={busy || data.running || dirty || !eligible || !data.configured}
                  onClick={() => act('/start', { mode: cfg?.mode })}
                >
                  Start {cfg?.mode.toUpperCase()}
                </Button>
                <Button
                  size="sm"
                  disabled={
                    busy || !data.running || !eligible || !validPlan || !!pos || !!snap?.command
                  }
                  onClick={() => control('approve')}
                >
                  Enter {cfg?.mode.toUpperCase()} · {p?.quantity ?? '—'} contract
                  {p?.quantity === 1 ? '' : 's'}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy || !data.running || !!snap?.command}
                  onClick={() => control(snap?.paused ? 'resume' : 'pause')}
                >
                  {snap?.paused ? 'Resume entries' : 'Pause entries'}
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={busy || !data.running || !pos || !!snap?.command}
                  onClick={() => control('close')}
                >
                  Close owned trade
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy || !data.running}
                  onClick={() => act('/stop', { mode: cfg?.mode })}
                >
                  Stop runner & close owned trade
                </Button>
                <a href="/python" className="self-center px-2 text-xs underline">
                  Process & logs
                </a>
              </div>
              {!data.configured && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Open Settings and save your risk limits to enable Start.
                </p>
              )}
              {editing && draft && (
                <div className="mt-4 border-t pt-3">
                  <p className="mb-3 text-xs text-muted-foreground">
                    App assumptions: strict 2+2 HTF swings; counterattack body ≥ selected ATR
                    fraction; renewed close beyond its high/low; subsequent price break. Short is an
                    inferred mirror. REST snapshots can miss intervening ticks. Prices stay USD;
                    cash amounts follow your display currency.
                  </p>
                  <fieldset
                    disabled={data.running || busy}
                    className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6 disabled:opacity-60"
                  >
                    <label className="grid gap-1 text-xs">
                      Execution
                      <select
                        className="h-10 rounded border bg-background px-2"
                        value={draft.mode}
                        onChange={(e) =>
                          setDraft({ ...draft, mode: e.target.value as Config['mode'] })
                        }
                      >
                        <option value="paper">Paper</option>
                        <option value="live">Live Delta</option>
                      </select>
                    </label>
                    <label className="grid gap-1 text-xs">
                      Entries
                      <select
                        className="h-10 rounded border bg-background px-2"
                        value={draft.entry_mode}
                        onChange={(e) =>
                          setDraft({ ...draft, entry_mode: e.target.value as Config['entry_mode'] })
                        }
                      >
                        <option value="review">Review each entry</option>
                        <option value="auto">Automatic entries</option>
                      </select>
                    </label>
                    {field('leverage', 'Leverage ×')}
                    {field('max_quantity', 'Maximum contracts')}
                    {field('max_risk', 'Total risk cap $', 0.1)}
                    {field('max_margin', 'Margin cap $')}
                    {field('daily_loss', 'Daily loss cap $', 0.1)}
                    {field('max_trades', 'Daily entry limit')}
                    {field('min_net_rr', 'Minimum net R:R', 0.1)}
                    {field('counter_atr', 'Counterattack / ATR', 0.1)}
                    {field('manual_level', 'Manual liquidity USD · 0 = auto', 0.5)}
                    {field('manual_target', 'Manual target USD · 0 = auto', 0.5)}
                    <label className="grid gap-1 text-xs">
                      Manual level side
                      <select
                        className="h-10 rounded border bg-background px-2"
                        value={draft.manual_side}
                        onChange={(e) =>
                          setDraft({
                            ...draft,
                            manual_side: e.target.value as Config['manual_side'],
                          })
                        }
                      >
                        <option value="Low">Low · long context</option>
                        <option value="High">High · short context</option>
                      </select>
                    </label>
                    <label className="flex items-center gap-2 text-xs">
                      <input
                        type="checkbox"
                        checked={draft.shorts}
                        onChange={(e) => setDraft({ ...draft, shorts: e.target.checked })}
                      />
                      Enable inferred short mirror
                    </label>
                    <Button size="sm" onClick={() => act('/configure', draft)}>
                      Save settings
                    </Button>
                  </fieldset>
                </div>
              )}
              {!!snap?.trades?.length && (
                <details className="mt-3 text-xs">
                  <summary>Recent strategy trades · {snap.trades.length}</summary>
                  {snap.trades.map((t) => (
                    <p key={t.id} className="mt-2">
                      {t.side.toUpperCase()} · {t.filled} contracts · entry {price(Number(t.entry))}{' '}
                      · net {cash(Number(t.net))} · {t.close_reason}
                    </p>
                  ))}
                </details>
              )}
            </>
          )}
        </div>
      )}
    </section>
  )
}
