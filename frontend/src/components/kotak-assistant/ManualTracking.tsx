import { useEffect, useRef, useState } from 'react'
import type { Leg, Quote } from '@/api/kotakAssistant'
import { useMarketData } from '@/hooks/useMarketData'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { money, errorMessage, automaticStop, rewardTarget, draftEntry } from './model'
import { optionFees } from './feeEstimates'
import { loadTracking, restoreTracking, saveTracking, type TrackingTrade } from './trackingStore'
import { TradeIndicators } from './TradeIndicators'
import { orderBookQuantities } from './orderBookQuantities'
import { TrackedTradePlan } from './TrackedTradePlan'
import { correctTrackingEntry, trackingPlan } from './trackingPlan'
import { TrackingPersistence } from './TrackingPersistence'

export function useManualTracking(scope: string) {
  const [state, setState] = useState<{
    scope: string
    rows: TrackingTrade[]
    ready: boolean
    error: string
  }>({ scope, rows: [], ready: false, error: '' })
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  useEffect(() => {
    let current = true
    loadTracking(scope)
      .then((rows) => {
        if (current) setState({ scope, rows, ready: true, error: '' })
      })
      .catch((e) => {
        if (current) setState({ scope, rows: [], ready: false, error: errorMessage(e) })
      })
    return () => {
      current = false
    }
  }, [scope])
  const rows = state.scope === scope ? state.rows : []
  const ready = state.scope === scope && state.ready
  const save = async (row: TrackingTrade) => {
    if (lock.current || !ready || row.scope !== scope)
      throw new Error('Tracking database is not ready')
    lock.current = true
    setBusy(true)
    try {
      await saveTracking(row)
      setState((previous) =>
        previous.scope === row.scope
          ? { ...previous, rows: [row, ...previous.rows.filter((r) => r.id !== row.id)], error: '' }
          : previous
      )
    } catch (error) {
      // Reconcile another window's committed close rather than leaving an
      // obsolete open card on screen after a rejected write.
      try {
        const restored = await loadTracking(row.scope)
        setState((previous) =>
          previous.scope === row.scope ? { ...previous, rows: restored } : previous
        )
      } catch {
        /* Keep the original save error visible. */
      }
      throw error
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  const restore = async (trades: TrackingTrade[]) => {
    if (lock.current || !ready || trades.some((r) => r.scope !== scope))
      throw new Error('Tracking database is not ready')
    lock.current = true
    setBusy(true)
    try {
      await restoreTracking(trades)
      const restored = await loadTracking(scope)
      setState((previous) =>
        previous.scope === scope ? { scope, rows: restored, ready: true, error: '' } : previous
      )
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  return {
    rows,
    ready,
    busy,
    error: state.scope === scope ? state.error : '',
    scope,
    save,
    restore,
  }
}
export type ManualTrackingController = ReturnType<typeof useManualTracking>
type Controller = ManualTrackingController

type TrackingTicketProps = {
  controller: Controller
  leg: Leg | null
  exchange: string
  interval?: string
  quote?: Quote
}
export function ManualTrackingTicket(props: TrackingTicketProps) {
  return (
    <TrackingForm
      key={`${props.controller.scope}:${props.exchange}:${props.leg?.symbol}`}
      {...props}
    />
  )
}
function TrackingForm({ controller, leg, exchange, interval = '5m', quote }: TrackingTicketProps) {
  const [entryEdit, setEntryEdit] = useState<string | null>(null),
    [lots, setLots] = useState('1'),
    [slEdit, setSlEdit] = useState<string | null>(null),
    [ratio, setRatio] = useState(2),
    [message, setMessage] = useState('')
  const autoEntry = draftEntry(
    leg ? { ...leg, ask: quote?.ask ?? leg.ask, ltp: quote?.ltp ?? leg.ltp } : null
  ).price
  const entry = entryEdit ?? (autoEntry == null ? '' : String(autoEntry))
  const autoSl = automaticStop(Number(entry), leg?.tick_size || 0)
  const sl = slEdit ?? (autoSl == null ? '' : String(autoSl))
  const targetPrice = rewardTarget(Number(entry), Number(sl), ratio, leg?.tick_size || 0)
  const target = targetPrice == null ? '' : String(targetPrice)
  const valid =
    !!leg &&
    Number.isInteger(Number(lots)) &&
    Number(lots) > 0 &&
    Number.isSafeInteger(Number(lots) * leg.lotsize) &&
    leg.lotsize > 0 &&
    Number.isFinite(Number(entry)) &&
    Number(entry) > 0 &&
    Number(sl) > 0 &&
    Number(sl) < Number(entry) &&
    targetPrice != null
  const add = async () => {
    if (!leg || !valid) return
    try {
      await controller.save({
        id: crypto.randomUUID(),
        scope: controller.scope,
        symbol: leg.symbol,
        exchange,
        lot: leg.lotsize,
        lots: Number(lots),
        entry: Number(entry),
        reward_ratio: ratio,
        automatic_sl: slEdit == null,
        tick: leg.tick_size,
        ...(sl ? { sl: Number(sl) } : {}),
        ...(target ? { target: Number(target) } : {}),
        created: Date.now() / 1000,
      })
      setMessage('Added below to Open trades & live monitoring')
      setEntryEdit('')
    } catch (e) {
      setMessage(errorMessage(e))
    }
  }
  return (
    <Card className="gap-0 py-0">
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold">Manual tracking record</h3>
          <span className="rounded border px-2 py-1 text-xs">Tracking only</span>
        </div>
        <p className="break-all text-sm font-medium">{leg?.symbol || 'Select a strike above'}</p>
        <p className="text-xs text-muted-foreground">
          Connected Kotak Neo trades are detected automatically below. Use this optional record for
          a manually entered fill. Saves in this browser; sends no broker orders.
        </p>
        <div className="grid grid-cols-2 gap-3 min-[1200px]:grid-cols-4">
          <label className="text-sm">
            Entry price ₹
            <Input
              aria-label="Tracked entry price"
              type="number"
              min="0.0001"
              step="any"
              value={entry}
              onChange={(e) => {
                setEntryEdit(e.target.value)
                setSlEdit(null)
              }}
            />
          </label>
          <label className="text-sm">
            Tracking lots
            <Input
              aria-label="Tracked lots"
              type="number"
              min="1"
              step="1"
              value={lots}
              onChange={(e) => setLots(e.target.value)}
            />
          </label>
          <label className="text-sm">
            SL ₹
            <Input
              aria-label="Tracked stop loss"
              type="number"
              min="0.0001"
              step="any"
              value={sl}
              onChange={(e) => setSlEdit(e.target.value)}
            />
          </label>
          <label className="text-sm">
            Tracking target ₹
            <Input
              aria-label="Tracked target"
              type="number"
              min="0.0001"
              step="any"
              value={target}
              readOnly
            />
          </label>
        </div>
        <fieldset className="flex flex-wrap items-center gap-2">
          <legend className="mb-2 text-xs text-muted-foreground">
            Tracking risk : reward · before charges
          </legend>
          {[1.5, 2, 3, 4, 5, 6].map((value) => (
            <Button
              key={value}
              size="sm"
              variant={ratio === value ? 'secondary' : 'outline'}
              aria-label={`Tracking risk reward 1:${value}`}
              aria-pressed={ratio === value}
              onClick={() => setRatio(value)}
            >
              1:{value}
            </Button>
          ))}
          <Button
            size="sm"
            variant="ghost"
            disabled={autoEntry == null}
            onClick={() => {
              setEntryEdit(null)
              setSlEdit(null)
            }}
          >
            Auto fill
          </Button>
        </fieldset>
        <p className="text-xs text-muted-foreground">
          {entryEdit == null
            ? 'Entry follows the selected strike price; edit it to use your actual fill. '
            : 'Your entered fill is retained during live updates. '}
          {slEdit == null
            ? 'Automatic SL: 10% premium buffer, rounded to the tick. '
            : 'Using your custom SL. '}
          Target = entry + (entry − SL) × {ratio}.
        </p>
        {leg && quote && (
          <TradeIndicators
            symbol={leg.symbol}
            exchange={exchange}
            interval={interval}
            quote={quote}
            now={Date.now() / 1000}
            fetchHistory={false}
          />
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            disabled={!valid || !controller.ready || controller.busy}
            onClick={add}
          >
            {controller.busy ? 'Saving…' : 'Add to tracking'}
          </Button>
          <span className="text-xs text-muted-foreground">
            {leg
              ? `${Number(lots) > 0 ? Number(lots) * leg.lotsize : '—'} units · ${leg.lotsize}/lot`
              : 'No strike selected'}
          </span>
        </div>
        <output className="block text-sm">{controller.error || message}</output>
      </CardContent>
    </Card>
  )
}

export function ManualTrackedTrades({
  controller,
  interval,
  brokerage = 0,
}: {
  controller: Controller
  interval: string
  brokerage?: number
}) {
  const [prices, setPrices] = useState<Record<string, string>>({}),
    [entries, setEntries] = useState<Record<string, string>>({}),
    [message, setMessage] = useState('')
  const open = controller.rows.filter((r) => !r.closed)
  const symbols = open.map((r) => ({ symbol: r.symbol, exchange: r.exchange }))
  const feed = useMarketData({ symbols, mode: 'Depth', enabled: open.length > 0 })
  const update = async (row: TrackingTrade, close: boolean) => {
    const value = Number(close ? prices[row.id] : entries[row.id])
    if (!Number.isFinite(value) || value <= 0) return
    try {
      const updated = close
        ? { ...row, exit: value, closed: Date.now() / 1000 }
        : correctTrackingEntry(row, value)
      await controller.save(updated)
      setMessage(
        close
          ? 'Tracking closed at your entered price. No broker order sent.'
          : 'Tracked entry updated'
      )
    } catch (e) {
      setMessage(errorMessage(e))
    }
  }
  return (
    <>
      <TrackingPersistence controller={controller} />
      {open.map((row) => {
        const plan = trackingPlan(row)
        const tick = feed.data.get(`${row.exchange}:${row.symbol}`)
        const q: Quote | undefined = tick?.lastUpdate
          ? {
              ltp: tick.data.ltp,
              volume: tick.data.volume,
              ...orderBookQuantities(tick.data),
              bid: tick.data.bid_price,
              ask: tick.data.ask_price,
              time: tick.lastUpdate / 1000,
              source: tick.updateSource === 'websocket' ? 'Live feed' : 'Broker snapshot',
            }
          : undefined
        const now = Date.now() / 1000,
          age = q ? now - q.time : NaN
        const fresh = age >= 0 && age <= 5 && q?.ltp != null && Number.isFinite(q.ltp) && q.ltp > 0
        const quantity = row.lots * row.lot
        const gross = fresh ? (q.ltp! - row.entry) * quantity : null
        const fees = fresh
          ? optionFees(row.entry * quantity, q.ltp! * quantity, row.exchange, brokerage)
          : null
        const reached =
          fresh && plan.sl && q.ltp! <= plan.sl
            ? 'SL level reached'
            : fresh && plan.target && q.ltp! >= plan.target
              ? 'Target level reached'
              : 'Tracking market price'
        return (
          <section
            key={row.id}
            aria-label={`Tracking only ${row.symbol}`}
            className="space-y-3 rounded-lg border p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <strong>{row.symbol}</strong>
                <p className="mt-1 text-xs text-muted-foreground">
                  {row.exchange} · BUY · {row.lots} lots · {quantity} units · Open
                </p>
              </div>
              <span className="rounded border px-2 py-1 text-xs">
                Entered in Kotak Neo · Tracking
              </span>
            </div>
            <TrackedTradePlan row={row} brokerage={brokerage} />
            <div className="grid gap-3 rounded-md bg-muted/30 p-3 sm:grid-cols-3">
              <div>
                <p className="text-xs text-muted-foreground">
                  {fresh ? 'Current price (LTP)' : 'Last price (LTP)'}
                </p>
                <output
                  aria-label="Tracked current price"
                  aria-live="off"
                  className="block text-xl font-bold tabular-nums"
                >
                  {money(q?.ltp)}
                </output>
                <p className="text-xs text-muted-foreground">
                  {fresh ? `${q?.source} · ${Math.floor(age)}s ago` : 'Waiting for fresh price'}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Gross P&L at LTP</p>
                <output
                  aria-label="Tracked gross P&L"
                  aria-live="off"
                  className="block text-lg font-bold tabular-nums"
                >
                  {money(gross)}
                </output>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Estimated net P&L at LTP</p>
                <output
                  aria-label="Tracked net P&L"
                  aria-live="off"
                  className="block text-lg font-bold tabular-nums"
                >
                  {money(gross != null && fees ? gross - fees.total : null)}
                </output>
                <p className="text-xs text-muted-foreground">
                  Estimated charges {money(fees?.total)}
                </p>
              </div>
            </div>
            <TradeIndicators
              symbol={row.symbol}
              exchange={row.exchange}
              interval={interval}
              quote={q}
              now={now}
              fetchHistory={false}
            />
            <p className="text-sm">{reached} · levels are tracking alerts</p>
            <div className="flex flex-wrap items-end gap-2">
              <label className="text-xs">
                Correct entry ₹
                <Input
                  className="w-32"
                  aria-label={`Correct entry ${row.symbol}`}
                  type="number"
                  step="any"
                  value={entries[row.id] ?? ''}
                  onChange={(e) => setEntries({ ...entries, [row.id]: e.target.value })}
                />
              </label>
              <Button
                variant="outline"
                disabled={controller.busy || !(Number(entries[row.id]) > 0)}
                onClick={() => update(row, false)}
              >
                Save entry
              </Button>
              <label className="text-xs">
                Closing price ₹
                <Input
                  className="w-32"
                  aria-label={`Closing price ${row.symbol}`}
                  type="number"
                  step="any"
                  value={prices[row.id] ?? ''}
                  onChange={(e) => setPrices({ ...prices, [row.id]: e.target.value })}
                />
              </label>
              <Button
                variant="secondary"
                disabled={controller.busy || !(Number(prices[row.id]) > 0)}
                onClick={() => update(row, true)}
              >
                Record close
              </Button>
            </div>
          </section>
        )
      })}
      {controller.rows.some((row) => row.closed) && (
        <details className="rounded-lg border p-3">
          <summary className="cursor-pointer text-sm font-medium">Closed tracking trades</summary>
          <div className="mt-3 space-y-2">
            {controller.rows
              .filter((r) => r.closed)
              .map((row) => {
                const quantity = row.lots * row.lot,
                  gross = (row.exit! - row.entry) * quantity,
                  fees = optionFees(
                    row.entry * quantity,
                    row.exit! * quantity,
                    row.exchange,
                    brokerage,
                    new Intl.DateTimeFormat('en-CA', {
                      timeZone: 'Asia/Kolkata',
                      year: 'numeric',
                      month: '2-digit',
                      day: '2-digit',
                    }).format(new Date(row.closed! * 1000))
                  )
                return (
                  <p key={row.id} className="text-sm tabular-nums">
                    <strong>{row.symbol}</strong> · {quantity} units · Entry {money(row.entry)} →
                    Close {money(row.exit)} · Gross {money(gross)} · Estimated charges{' '}
                    {money(fees?.total)} · Net {money(fees ? gross - fees.total : null)}
                  </p>
                )
              })}
          </div>
        </details>
      )}
      <output className="block text-sm">{controller.error || message}</output>
    </>
  )
}
