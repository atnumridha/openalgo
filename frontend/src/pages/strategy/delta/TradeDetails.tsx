import { useDeltaDisplayCurrency } from '@/hooks/useDeltaDisplayCurrency'
import { useAuthStore } from '@/stores/authStore'
import type { DeltaDisplayCurrency } from '@/lib/deltaCurrency'
import { Fragment, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { when, type Amount, type TradeReport } from './types'

export default function TradeDetails({ report, fresh }: { report?: TradeReport; fresh: boolean }) {
  const {user} = useAuthStore()
  const [currency, setCurrency] = useDeltaDisplayCurrency(user?.username)
  const [expanded, setExpanded] = useState<string | null>(null)
  const fmt = (amount: Amount) =>
    amount == null
      ? 'Unavailable'
      : new Intl.NumberFormat('en-IN', {
          style: 'currency',
          currency,
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        }).format(Number(amount) * (currency === 'INR' ? 85 : 1))
  const color = (amount: Amount) =>
    amount == null
      ? 'text-muted-foreground'
      : Number(amount) > 0
        ? 'text-emerald-600 dark:text-emerald-400'
        : Number(amount) < 0
          ? 'text-red-600 dark:text-red-400'
          : ''
  const time = (at: number | null) =>
    at
      ? new Date(at * 1000).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false })
      : 'Prior / unknown entry'
  return (
    <Card id="live-trades">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>Live Delta · per-trade P&L</CardTitle>
            <CardDescription>
              {report?.day || 'Today'} · India time · Actual account fills and wallet charges
            </CardDescription>
          </div>
          <label className="flex items-center gap-2 text-sm">
            Currency
            <select
              aria-label="Trade report currency"
              value={currency}
              onChange={(e) => setCurrency(e.target.value as DeltaDisplayCurrency)}
              className="rounded-md border bg-background px-3 py-2"
            >
              <option value="INR">INR · ₹85 per USD</option>
              <option value="USD">USD</option>
            </select>
          </label>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {!report ? (
          <p className="text-sm text-muted-foreground">
            Waiting for the read-only Delta trade report. No result is assumed.
          </p>
        ) : (
          <>
            {!fresh && (
              <Alert variant="destructive">
                <AlertDescription>
                  Snapshot is stale. These are previously fetched trade records, not a current
                  account view.
                </AlertDescription>
              </Alert>
            )}
            {report.issues.map((issue) => (
              <Alert key={issue} variant="destructive">
                <AlertDescription>{issue}</AlertDescription>
              </Alert>
            ))}
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {[
                ['P&L without fees', 'gross_usd'],
                ['Total fees incl. GST', 'fees_usd'],
                ['P&L after full costs', 'net_usd'],
                ['Cash-wallet trading impact', 'cash_net_usd'],
              ].map(([label, key]) => (
                <div key={key} className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p
                    className={`mt-1 text-xl font-semibold tabular-nums ${key === 'fees_usd' ? '' : color(report.totals[key])}`}
                  >
                    {fmt(report.totals[key])}
                  </p>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              {report.closed_count} fully reconstructed closed trades. Gross excludes fees and
              funding. Net = gross − cash fees − fee credits used + funding + rebates. GST is
              already included. Promotional credits awarded are shown separately and do not increase
              net P&L.
            </p>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    {[
                      'Trade',
                      'Entry → exit · IST',
                      'Prices · USD',
                      'Gross / no fees',
                      'Entry fee',
                      'Exit fee',
                      'Funding',
                      'Net / full costs',
                      '',
                    ].map((h, i) => (
                      <TableHead key={h || i} className="whitespace-nowrap">
                        {h}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {!report.rows.length && (
                    <TableRow>
                      <TableCell colSpan={9} className="h-24 text-center text-muted-foreground">
                        {report.issues.length
                          ? 'Trade details are unavailable for this snapshot.'
                          : 'No executed trades in this day’s snapshot.'}
                      </TableCell>
                    </TableRow>
                  )}
                  {report.rows.map((row) => (
                    <Fragment key={row.id}>
                      <TableRow>
                        <TableCell className="min-w-32">
                          <p className="font-medium">{row.symbol}</p>
                          <p className="text-xs">
                            {row.direction} · {row.contracts ?? 'Unknown'} contracts
                          </p>
                          <Badge variant="outline" className="mt-1">
                            {row.status === 'closed'
                              ? 'Closed'
                              : row.status === 'open'
                                ? 'Open'
                                : 'Incomplete'}
                          </Badge>
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          <p>
                            {time(row.opened_at)} → {row.closed_at ? time(row.closed_at) : 'Open'}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {row.holding_seconds != null
                              ? `${Math.floor(row.holding_seconds / 60)}m ${Math.floor(row.holding_seconds % 60)}s`
                              : ''}
                          </p>
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          <p>
                            {row.entry_price == null
                              ? 'Unknown'
                              : Number(row.entry_price).toLocaleString('en-IN', {
                                  maximumFractionDigits: 4,
                                })}
                          </p>
                          <p>
                            →{' '}
                            {row.exit_price == null
                              ? '—'
                              : Number(row.exit_price).toLocaleString('en-IN', {
                                  maximumFractionDigits: 4,
                                })}
                          </p>
                        </TableCell>
                        <TableCell
                          className={`whitespace-nowrap tabular-nums ${color(row.gross_usd)}`}
                        >
                          {fmt(row.gross_usd)}
                        </TableCell>
                        <TableCell className="whitespace-nowrap tabular-nums">
                          {fmt(row.entry_fees_usd)}
                        </TableCell>
                        <TableCell className="whitespace-nowrap tabular-nums">
                          {fmt(row.exit_fees_usd)}
                        </TableCell>
                        <TableCell className="whitespace-nowrap tabular-nums">
                          {fmt(row.funding_usd)}
                        </TableCell>
                        <TableCell
                          className={`whitespace-nowrap font-semibold tabular-nums ${color(row.net_usd)}`}
                        >
                          {fmt(row.net_usd)}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-expanded={expanded === row.id}
                            aria-label={`Details for ${row.entry_order_ids[0] || row.exit_order_ids[0]}`}
                            onClick={() => setExpanded(expanded === row.id ? null : row.id)}
                          >
                            {expanded === row.id ? 'Hide' : 'Details'}
                          </Button>
                        </TableCell>
                      </TableRow>
                      {expanded === row.id && (
                        <TableRow>
                          <TableCell colSpan={9} className="bg-muted/25 p-4">
                            <div className="space-y-4">
                              {row.issues.map((issue) => (
                                <p
                                  key={issue}
                                  className="text-sm text-amber-700 dark:text-amber-400"
                                >
                                  {issue}
                                </p>
                              ))}
                              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                                {[
                                  ['Cash-paid fees', row.cash_fees_usd],
                                  ['Fee credits used', row.credits_used_usd],
                                  ['Funding received / paid', row.funding_usd],
                                  ['Fee rebates', row.rebates_usd],
                                  ['Promotional credits awarded', row.promo_credits_usd],
                                  ['Cash-wallet trading impact', row.cash_net_usd],
                                ].map(([label, value]) => (
                                  <div key={label}>
                                    <p className="text-xs text-muted-foreground">{label}</p>
                                    <p className="tabular-nums">{fmt(value)}</p>
                                  </div>
                                ))}
                              </div>
                              <div className="text-xs">
                                <p>
                                  Entry orders:{' '}
                                  {row.entry_order_ids.join(', ') || 'Not in loaded day'}
                                </p>
                                <p>
                                  Exit orders: <span>{row.exit_order_ids.join(', ') || '—'}</span>
                                </p>
                                <p>
                                  Opened {when(row.opened_at)} · Closed {when(row.closed_at)}
                                </p>
                              </div>
                              <Table>
                                <TableHeader>
                                  <TableRow>
                                    {[
                                      'Order ID',
                                      'Fill time · IST',
                                      'Leg / side',
                                      'Execution',
                                      'Contracts',
                                      'Price USD',
                                      'Full fee',
                                      'Cash paid',
                                      'Credits used',
                                    ].map((h) => (
                                      <TableHead key={h}>{h}</TableHead>
                                    ))}
                                  </TableRow>
                                </TableHeader>
                                <TableBody>
                                  {row.fills.map((f, i) => (
                                    <TableRow key={`${f.fill_id}-${i}`}>
                                      <TableCell>{f.order_id}</TableCell>
                                      <TableCell className="whitespace-nowrap">
                                        {time(f.at)}
                                      </TableCell>
                                      <TableCell>
                                        {f.role} · {f.side}
                                      </TableCell>
                                      <TableCell>{f.liquidity}</TableCell>
                                      <TableCell>{f.contracts}</TableCell>
                                      <TableCell>{f.price}</TableCell>
                                      <TableCell>{fmt(f.fee_usd)}</TableCell>
                                      <TableCell>{fmt(f.cash_fee_usd)}</TableCell>
                                      <TableCell>{fmt(f.credits_used_usd)}</TableCell>
                                    </TableRow>
                                  ))}
                                </TableBody>
                              </Table>
                              <p className="text-xs text-muted-foreground">
                                Partial fills are grouped into one flat-to-flat trade. Reversal
                                fills allocate fees in proportion to contracts. A zero exit fee is a
                                reported charge, not an assumed waiver. Cash impact excludes
                                fee-credit consumption and promotional credit awards.
                              </p>
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  ))}
                </TableBody>
              </Table>
            </div>
            {report.unattributed.length > 0 && (
              <Alert>
                <AlertDescription>
                  Some wallet adjustments could not be linked to a trade and are excluded from the
                  trade totals:{' '}
                  {report.unattributed.map((v) => `${v.kind}: ${fmt(v.amount_usd)}`).join('; ')}.
                  The account summary remains separate.
                </AlertDescription>
              </Alert>
            )}
            <p className="text-xs text-muted-foreground">
              Snapshot {when(report.asof)}. {report.scope}{' '}
              {report.total_rows && report.total_rows > report.rows.length
                ? `Showing the latest ${report.rows.length} of ${report.total_rows} trades.`
                : ''}{' '}
              Per-trade rounding may differ slightly from totals.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}
