import type { BrokerMonitorSnapshot, BrokerPosition, Quote, Trade } from '@/api/kotakAssistant'
import { money } from './model'
import { feeDay, optionFees } from './feeEstimates'
import { LEVEL_COLORS } from './PriceLevels'
import { TradeIndicators } from './TradeIndicators'

const same = (
  a: { symbol: string; exchange: string; product: string },
  b: { symbol: string; exchange: string; product: string }
) => a.symbol === b.symbol && a.exchange === b.exchange && a.product === b.product
const positive = (value: unknown) =>
  Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : null
const terminal = new Set(['complete', 'completed', 'cancelled', 'canceled', 'rejected'])
const managedQuantity = (p: BrokerPosition, trades: Trade[]) =>
  trades
    .filter((t) => t.mode === 'live' && !['closed', 'rejected'].includes(t.status) && same(p, t))
    .reduce((sum, t) => sum + Math.max(0, Number(t.remaining) || 0), 0)

export function unownedBrokerPositions(data: BrokerMonitorSnapshot | undefined, trades: Trade[]) {
  return (data?.positions || []).filter(
    (p) => p.quantity !== 0 && p.quantity !== managedQuantity(p, trades)
  )
}

export function BrokerPositions({
  data,
  error,
  trades,
  quote,
  interval,
  now,
  brokerage = 0,
}: {
  data?: BrokerMonitorSnapshot
  error?: string
  trades: Trade[]
  quote: (position: BrokerPosition) => Quote | undefined
  interval: string
  now: number
  brokerage?: number
}) {
  const rows = unownedBrokerPositions(data, trades)
  const bookAge = data?.book_time ? now - data.book_time : NaN
  const fresh = !error && !data?.error && bookAge >= 0 && bookAge <= 15
  const savedDayLabel =
    data?.day === feeDay(now * 1000) ? 'today' : `on ${data?.day || 'the last saved day'}`
  return (
    <section className="space-y-3" aria-label="Automatic Kotak Neo tracking">
      <div className="rounded-md border bg-muted/30 p-3 text-sm">
        <div className="flex flex-wrap justify-between gap-2">
          <strong>Live Kotak Neo · automatic tracking</strong>
          <span>
            {fresh
              ? `Synced ${Math.floor(bookAge)}s ago`
              : data?.book_time
                ? 'Last saved broker state'
                : 'Connecting to Kotak Neo…'}
          </span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          App trades appear automatically in either Paper or Live mode. Positions, orders and fills
          are saved on the server and checked again after reconnecting.
        </p>
        {(error || data?.error) && (
          <output className="mt-2 block text-destructive">{error || data?.error}</output>
        )}
        {fresh && !rows.length && (
          <p className="mt-2 text-xs text-muted-foreground">No additional open broker positions.</p>
        )}
      </div>
      {rows.map((p) => {
        const q = quote(p)
        const ltp = positive(q?.ltp)
        const priceFresh = !!q && now - q.time >= 0 && now - q.time <= 5 && ltp != null
        const entry = positive(p.average_entry)
        const options = ['NFO', 'BFO'].includes(p.exchange) && /(?:CE|PE)$/.test(p.symbol)
        const unitPrices = options || ['NSE', 'BSE', 'NFO', 'BFO'].includes(p.exchange)
        const gross =
          fresh && priceFresh && entry != null && p.average_entry_verified && unitPrices
            ? (ltp! - entry) * p.quantity
            : null
        const quantity = Math.abs(p.quantity)
        const overlap = managedQuantity(p, trades)
        const charges =
          gross != null && options
            ? optionFees(
                (p.quantity > 0 ? entry! : ltp!) * quantity,
                (p.quantity > 0 ? ltp! : entry!) * quantity,
                p.exchange,
                brokerage
              )
            : null
        const pending = (data?.orders || [])
          .filter(
            (o) =>
              same(o, p) &&
              !terminal.has(o.order_status?.trim().toLowerCase()) &&
              o.action === (p.quantity > 0 ? 'SELL' : 'BUY')
          )
          .map((o) => {
            const filled = (data?.fills || [])
              .filter((f) => String(f.orderid) === String(o.orderid))
              .reduce((sum, f) => sum + Number(f.quantity), 0)
            return {
              ...o,
              remaining: Math.max(
                0,
                Number(o.quantity) - Math.max(filled, Number(o.filled_quantity) || 0)
              ),
            }
          })
          .filter((o) => o.remaining > 0)
        const stops = pending.filter(
          (o) => ['SL', 'SL-M'].includes(o.pricetype) && positive(o.trigger_price) != null
        )
        const targets = pending.filter(
          (o) =>
            o.pricetype === 'LIMIT' &&
            positive(o.price) != null &&
            entry != null &&
            (p.quantity > 0 ? Number(o.price) > entry : Number(o.price) < entry)
        )
        return (
          <section
            key={`${p.exchange}:${p.symbol}:${p.product}`}
            aria-label={`Broker position ${p.symbol} ${p.product}`}
            className="space-y-3 rounded-lg border p-4"
          >
            <div className="flex flex-wrap justify-between gap-2">
              <div>
                <strong className="break-all">{p.symbol}</strong>
                <p className="mt-1 text-xs text-muted-foreground">
                  {p.exchange} · {p.product} · {p.quantity > 0 ? 'LONG' : 'SHORT'} · {quantity}{' '}
                  units{p.lot ? ` · ${Number((quantity / p.lot).toFixed(3))} lots` : ''}
                </p>
              </div>
              <span className="h-fit rounded border px-2 py-1 text-xs">
                {fresh ? 'LIVE · From Kotak Neo' : 'Last known position · Awaiting sync'}
              </span>
            </div>
            <dl className="grid gap-3 rounded-lg border p-3 sm:grid-cols-3">
              {[
                {
                  label: p.average_entry_verified ? 'Filled entry' : 'Broker average',
                  aria: 'Broker filled entry',
                  text: money(entry),
                  color: LEVEL_COLORS.entry,
                },
                {
                  label: 'Broker stop loss',
                  aria: 'Broker SL',
                  text: stops.length
                    ? stops.map((o) => money(Number(o.trigger_price))).join(' / ')
                    : fresh
                      ? 'Not set at broker'
                      : 'Not present in last saved orders',
                  color: LEVEL_COLORS.stop,
                },
                {
                  label: 'Broker profit target',
                  aria: 'Broker target',
                  text: targets.length
                    ? targets.map((o) => money(Number(o.price))).join(' / ')
                    : fresh
                      ? 'Not set at broker'
                      : 'Not present in last saved orders',
                  color: LEVEL_COLORS.target,
                },
              ].map((level) => (
                <div
                  key={level.aria}
                  className="min-w-0 border-l-4 pl-3"
                  style={{ borderColor: level.color }}
                >
                  <dt className="text-xs text-muted-foreground">{level.label}</dt>
                  <dd className="mt-1 text-xl font-semibold tabular-nums">
                    <output aria-label={level.aria}>{level.text}</output>
                  </dd>
                </div>
              ))}
            </dl>
            {overlap > 0 && (
              <p className="text-sm">
                Broker total includes {overlap} terminal-managed units. This card shows the whole
                broker position; its P&L overlaps the managed trade above.
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              {p.entry_basis}
              {p.average_price_basis === 'carry_forward_valuation'
                ? ' · Overnight valuation; original entry unavailable'
                : ''}
            </p>
            <div className="grid gap-3 rounded-md bg-muted/30 p-3 sm:grid-cols-3">
              <div>
                <p className="text-xs text-muted-foreground">
                  {priceFresh ? 'Current price (LTP)' : 'Last price (LTP)'}
                </p>
                <output
                  aria-label="Broker current price"
                  aria-live="off"
                  className="block text-2xl font-bold tabular-nums"
                >
                  {money(ltp)}
                </output>
                <p className="text-xs text-muted-foreground">
                  {priceFresh
                    ? `${q?.source || 'Live feed'} · ${Math.floor(now - q!.time)}s ago`
                    : 'Waiting for fresh quote'}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Gross open P&L at LTP</p>
                <output
                  aria-label="Broker gross open P&L"
                  aria-live="off"
                  className={`block text-xl font-semibold tabular-nums ${gross == null ? '' : gross < 0 ? 'text-destructive' : 'text-green-700 dark:text-green-400'}`}
                >
                  {money(gross)}
                </output>
                <p className="text-xs text-muted-foreground">
                  Broker day P&L {money(p.pnl == null ? null : Number(p.pnl))} · includes realised
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Estimated net open P&L</p>
                <output
                  aria-label="Broker estimated net open P&L"
                  aria-live="off"
                  className={`block text-xl font-semibold tabular-nums ${gross == null || !charges ? '' : gross - charges.total < 0 ? 'text-destructive' : 'text-green-700 dark:text-green-400'}`}
                >
                  {money(gross != null && charges ? gross - charges.total : null)}
                </output>
                <p className="text-xs text-muted-foreground">
                  {options ? (
                    <>Estimated charges {money(charges?.total)} · before slippage</>
                  ) : (
                    'Net estimate available for supported option charges'
                  )}
                </p>
              </div>
            </div>
            {pending.length > 0 && (
              <div className="space-y-1 text-xs">
                <p className="font-medium">
                  {fresh ? 'Broker exit orders' : 'Last saved broker exit orders'} · remaining
                  quantities
                </p>
                {pending.map((o) => (
                  <p key={o.orderid}>
                    {o.orderid} · {o.action} {o.pricetype} · {o.remaining} units · {o.order_status}
                  </p>
                ))}
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              Read-only tracking. Exits and order changes made in Kotak Neo are picked up
              automatically.
            </p>
            <TradeIndicators
              symbol={p.symbol}
              exchange={p.exchange}
              interval={interval}
              quote={q}
              now={now}
            />
          </section>
        )
      })}
      {data && Object.keys(data.days).length > 0 && (
        <details className="rounded-lg border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            Saved broker fills · {data.fills.length} {savedDayLabel}
          </summary>
          <div className="mt-3 space-y-3">
            {Object.entries(data.days)
              .sort(([a], [b]) => b.localeCompare(a))
              .map(([day, saved]) => (
                <details key={day} open={day === data.day}>
                  <summary className="cursor-pointer text-sm">
                    {day} · {saved.fills.length} fills
                  </summary>
                  <div className="mt-2 overflow-x-auto">
                    <table className="w-full text-left text-xs tabular-nums">
                      <thead>
                        <tr>
                          <th scope="col">Symbol</th>
                          <th scope="col">Side</th>
                          <th scope="col">Units</th>
                          <th scope="col">Fill price</th>
                          <th scope="col">Time (IST) / order</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...saved.fills]
                          .sort(
                            (a, b) =>
                              (b.epoch || 0) - (a.epoch || 0) ||
                              String(b.orderid).localeCompare(String(a.orderid))
                          )
                          .map((f) => (
                            <tr key={`${f.orderid}:${f.tradeid}`} className="border-t">
                              <td className="py-2 pr-3">
                                {f.symbol} · {f.product}
                              </td>
                              <td>{f.action}</td>
                              <td>{f.quantity}</td>
                              <td>{money(Number(f.average_price))}</td>
                              <td>
                                {String(f.timestamp)} · {f.orderid}
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              ))}
          </div>
        </details>
      )}
    </section>
  )
}
