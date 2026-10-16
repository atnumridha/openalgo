import { useRef, useState, type ReactNode } from 'react'
import { kotakAssistantApi, type Trade, type Quote } from '@/api/kotakAssistant'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { errorMessage, money, executableQuote } from './model'
import { OptionLevels } from './PriceLevels'
import { openTradeCosts } from './feeEstimates'
import { TradeIndicators } from './TradeIndicators'

export function ManagedTrades({
  trades,
  refresh,
  quote,
  brokerage = 0,
  interval = '5m',
  trackingCount = 0,
  children,
}: {
  trades: Trade[]
  refresh: () => void
  quote: (t: Trade) => Quote | undefined
  brokerage?: number
  interval?: string
  trackingCount?: number
  children?: ReactNode
}) {
  const [busy, setBusy] = useState<string | null>(null),
    [message, setMessage] = useState(''),
    [lots, setLots] = useState<Record<string, string>>({}),
    [stops, setStops] = useState<Record<string, string>>({})
  const lock = useRef(false)
  const now = Date.now() / 1000
  const act = async (t: Trade, kind: 'full' | 'partial' | 'stop') => {
    if (lock.current) return
    lock.current = true
    setBusy(t.id)
    try {
      if (kind === 'stop') await kotakAssistantApi.stop(t.mode, t.id, Number(stops[t.id]))
      else
        await kotakAssistantApi.exit(
          t.mode,
          t.id,
          crypto.randomUUID(),
          kind === 'partial' ? Number(lots[t.id]) * t.lot : undefined
        )
      setMessage('Request recorded; monitoring broker fills')
      refresh()
    } catch (e) {
      setMessage(errorMessage(e))
      refresh()
    } finally {
      lock.current = false
      setBusy(null)
    }
  }
  const exitAll = async () => {
    if (lock.current) return
    lock.current = true
    setBusy('all')
    try {
      for (const t of trades) await kotakAssistantApi.exit(t.mode, t.id, crypto.randomUUID())
      setMessage('Exits recorded for managed trades; awaiting fills')
      refresh()
    } catch (e) {
      setMessage(errorMessage(e))
      refresh()
    } finally {
      lock.current = false
      setBusy(null)
    }
  }
  return (
    <Card className="gap-0 py-0">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h3
            id="kotak-open-trades"
            tabIndex={-1}
            className="scroll-mt-20 font-semibold focus-visible:outline-2"
          >
            Open trades & live monitoring
          </h3>
          <Button variant="destructive" disabled={!trades.length || !!busy} onClick={exitAll}>
            Exit all managed
          </Button>
        </div>
        {!trades.length && !trackingCount && (
          <p className="text-sm text-muted-foreground">
            No open terminal trades or additional broker positions.
          </p>
        )}
        {trades.map((t) => {
          const q = quote(t)
          const fresh = executableQuote(q, now)
          const price = q?.ltp != null && Number.isFinite(q.ltp) && q.ltp > 0 ? q.ltp : null
          const age = q ? now - q.time : NaN
          const timestampValid = !!q && Number.isFinite(q.time) && q.time > 0 && age >= 0
          const priceFresh = price != null && timestampValid && age <= 5
          const updated = timestampValid
            ? new Date(q!.time * 1000).toLocaleTimeString('en-IN', {
                timeZone: 'Asia/Kolkata',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false,
              })
            : null
          const costs = openTradeCosts(t, q, brokerage)
          return (
            <section
              key={`${t.mode}:${t.id}`}
              aria-label={`Open trade ${t.symbol}`}
              className="rounded-lg border p-4 space-y-3"
            >
              <div className="flex flex-wrap justify-between gap-2">
                <div>
                  <strong>{t.symbol}</strong>
                  <p className="text-xs">
                    {t.mode === 'live' ? 'LIVE KOTAK' : 'PAPER'} · {t.product} · {t.remaining}{' '}
                    remaining / {t.entry_quantity} filled
                  </p>
                </div>
              </div>
              <div className="grid gap-3 rounded-md border bg-muted/30 p-3 sm:grid-cols-2">
                <div>
                  <span className="text-xs text-muted-foreground">
                    {price != null && !priceFresh ? 'Last price (LTP)' : 'Current price (LTP)'}
                  </span>
                  <div className="flex flex-wrap items-center gap-2">
                    <output
                      aria-label="Current market price"
                      aria-live="off"
                      className="text-2xl font-bold tabular-nums"
                    >
                      {money(price)}
                    </output>
                    <Badge variant={priceFresh ? 'secondary' : 'outline'}>
                      {priceFresh
                        ? q?.source === 'Live feed'
                          ? 'Live'
                          : 'Fresh'
                        : price == null || !timestampValid
                          ? 'Unavailable'
                          : 'Stale'}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {price != null && updated
                      ? `Updated ${updated} IST · ${Math.floor(age)}s ago · ${q?.source || 'Latest quote'}`
                      : 'Waiting for a fresh market price'}
                  </p>
                </div>
                <div className="sm:text-right">
                  <span className="text-xs text-muted-foreground">
                    Estimated net P&L after charges
                  </span>
                  <output
                    aria-label="Net open P&L after charges"
                    aria-live="off"
                    className="block text-lg font-bold tabular-nums"
                  >
                    {money(costs?.net)}
                  </output>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3 rounded-md bg-muted/30 p-3 text-sm tabular-nums">
                <div>
                  <span className="text-xs text-muted-foreground">Gross open P&L</span>
                  <output aria-label="Gross open P&L" aria-live="off" className="block font-bold">
                    {money(costs?.gross)}
                  </output>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">
                    Estimated charges · entry + exit
                  </span>
                  <output
                    aria-label="Estimated open charges"
                    aria-live="off"
                    className="block font-bold"
                  >
                    {money(costs?.charges)}
                  </output>
                </div>
                <p className="col-span-2 text-xs text-muted-foreground">
                  Remaining quantity at current exit bid · brokerage {money(brokerage)}/order. Net
                  is estimated until the exit fills.
                </p>
              </div>
              <TradeIndicators
                symbol={t.symbol}
                exchange={t.exchange}
                interval={interval}
                quote={q}
                now={now}
              />
              <OptionLevels
                actual
                entry={t.average_entry_verified === false ? null : t.average_entry}
                sl={t.current_sl}
                target={t.target}
                protectedStop={t.status === 'protected'}
                autoTarget={t.auto_target}
              />
              <p className="text-sm">
                {fresh ? 'Current exit bid' : 'Last exit bid'}: {money(q?.bid)} · full exit sells{' '}
                {t.remaining} units
              </p>
              <p className="text-sm font-medium">
                {fresh ? t.reason : 'DATA UNAVAILABLE · latest quote unavailable/stale'}
              </p>
              <p className="text-xs text-muted-foreground">
                {t.status} · Frozen SL {money(t.sl)} · Observed peak net {money(t.peak_net)}
              </p>
              {t.ops
                .filter(
                  (o) =>
                    o.role === 'sl' &&
                    o.state === 'accepted' &&
                    !['complete', 'cancelled', 'rejected'].includes(o.broker_status || '')
                )
                .map((o) => (
                  <p key={o.orderid} className="text-xs text-muted-foreground">
                    SL order {o.orderid || 'pending'} · trigger {money(o.trigger_price)} · limit{' '}
                    {money(o.price)} · {o.broker_status || 'awaiting confirmation'}
                  </p>
                ))}
              {t.ops
                .filter((o) => o.message)
                .map((o, i) => (
                  <p key={`${o.orderid || o.role}:${i}`} className="text-sm text-destructive">
                    {o.role}: {o.message}
                  </p>
                ))}
              <div className="flex flex-wrap items-end gap-2">
                <Button variant="destructive" disabled={!!busy} onClick={() => act(t, 'full')}>
                  {busy === t.id ? 'Processing…' : 'Exit full'}
                </Button>
                {t.remaining >= t.lot * 2 && (
                  <>
                    <label className="text-xs">
                      Exit lots
                      <Input
                        className="w-24"
                        type="number"
                        min="1"
                        max={t.remaining / t.lot - 1}
                        step="1"
                        value={lots[t.id] || '1'}
                        onChange={(e) => setLots({ ...lots, [t.id]: e.target.value })}
                      />
                    </label>
                    <Button
                      variant="outline"
                      disabled={!!busy}
                      onClick={() => {
                        if (!lots[t.id]) lots[t.id] = '1'
                        act(t, 'partial')
                      }}
                    >
                      Exit selected lots
                    </Button>
                  </>
                )}
                <label className="text-xs">
                  Tighter SL
                  <Input
                    className="w-28"
                    type="number"
                    step={t.tick}
                    value={stops[t.id] || ''}
                    onChange={(e) => setStops({ ...stops, [t.id]: e.target.value })}
                  />
                </label>
                <Button
                  variant="outline"
                  disabled={!!busy || !stops[t.id]}
                  onClick={() => act(t, 'stop')}
                >
                  Tighten SL
                </Button>
              </div>
            </section>
          )
        })}
        {children}
        <output className="block text-sm">{message}</output>
      </CardContent>
    </Card>
  )
}
