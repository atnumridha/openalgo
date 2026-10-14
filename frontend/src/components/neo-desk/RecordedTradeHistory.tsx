import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { neoReportsApi } from '@/api/neoReports'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { amount, FeeBreakdown } from './FeeBreakdown'
import { RecordedTradeReplay } from './RecordedTradeReplay'
export function RecordedTradeHistory() {
  return import.meta.env.VITE_NEO_DESK_ENABLED === 'true' ? <EnabledHistory /> : null
}
function EnabledHistory() {
  const [mode, setMode] = useState('live')
  const [replayId, setReplayId] = useState('')
  const [symbol, setSymbol] = useState(''),
    [start, setStart] = useState(''),
    [end, setEnd] = useState(''),
    [cursor, setCursor] = useState(0),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [costPlan, setCostPlan] = useState(() => {
      try {
        return localStorage.getItem('neo.history.costPlan') === 'trade_free'
          ? 'trade_free'
          : 'free_offer'
      } catch {
        return 'free_offer'
      }
    })
  const q = useQuery({
    queryKey: ['neo-history', symbol, start, end, cursor, costPlan, mode],
    queryFn: () => neoReportsApi.history(symbol, start, end, cursor, costPlan, mode),
    enabled: !(start && end && start > end),
    refetchInterval: 60000,
  })
  const d = q.data
  async function action(fn: () => Promise<unknown>) {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await fn()
      await q.refetch()
    } catch (e) {
      const x = e as { response?: { data?: { message?: string } }; message?: string }
      setError(x.response?.data?.message || x.message || 'Report request failed.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Saved trading reports · {mode === 'live' ? 'Live' : 'Sandbox'}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          SQL history retained across days and restarts. Select any date or range; Live and Sandbox
          records stay separate.
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <Button
            variant="outline"
            onClick={() => {
              const today = new Intl.DateTimeFormat('en-CA', {
                timeZone: 'Asia/Kolkata',
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
              }).format(new Date())
              setStart(today)
              setEnd(today)
              setCursor(0)
              setReplayId('')
            }}
          >
            Today
          </Button>
          <div>
            <Label htmlFor="history-mode">Report mode</Label>
            <select
              id="history-mode"
              className="h-10 rounded border bg-background px-3"
              value={mode}
              onChange={(e) => {
                setMode(e.target.value)
                setReplayId('')
                setCursor(0)
              }}
            >
              <option value="live">Live · Kotak account</option>
              <option value="sandbox">Sandbox · paper trades</option>
            </select>
          </div>
          <div>
            <Label htmlFor="history-date">Recorded date</Label>
            <select
              id="history-date"
              disabled={!d?.coverage.recorded_dates.length}
              className="h-10 rounded border bg-background px-3"
              value={start === end ? start : ''}
              onChange={(e) => {
                setStart(e.target.value)
                setEnd(e.target.value)
                setCursor(0)
              }}
            >
              <option value="">All dates / custom range</option>
              {[...(d?.coverage.recorded_dates ?? [])].reverse().map((day) => (
                <option key={day} value={day}>
                  {day}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="history-symbol">History symbol</Label>
            <select
              id="history-symbol"
              className="h-10 rounded border bg-background px-3"
              value={symbol}
              onChange={(e) => {
                setSymbol(e.target.value)
                setCursor(0)
              }}
            >
              <option value="">All symbols</option>
              {d?.symbols.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="history-start">From</Label>
            <input
              id="history-start"
              type="date"
              value={start}
              onChange={(e) => {
                setStart(e.target.value)
                setCursor(0)
              }}
              className="h-10 rounded border bg-background px-3"
            />
          </div>
          <div>
            <Label htmlFor="history-end">Through</Label>
            <input
              id="history-end"
              type="date"
              value={end}
              onChange={(e) => {
                setEnd(e.target.value)
                setCursor(0)
              }}
              className="h-10 rounded border bg-background px-3"
            />
          </div>
          <div>
            <Label htmlFor="history-plan">Charge estimate plan</Label>
            <select
              id="history-plan"
              className="h-10 rounded border bg-background px-3"
              value={costPlan}
              onChange={(e) => {
                setCostPlan(e.target.value)
                try {
                  localStorage.setItem('neo.history.costPlan', e.target.value)
                } catch {
                  /* Browser storage may be disabled. */
                }
              }}
            >
              <option value="free_offer">Active free-brokerage offer · estimate</option>
              <option value="trade_free">Trade Free · ₹10 per executed order</option>
            </select>
          </div>
          <Button
            variant="outline"
            onClick={() => {
              const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(
                new Date()
              )
              setStart(today)
              setEnd(today)
              setCursor(0)
            }}
          >
            Today
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              setStart('')
              setEnd('')
              setCursor(0)
            }}
          >
            All recorded dates
          </Button>
          {mode === 'live' ? (
            <Button disabled={busy} onClick={() => action(neoReportsApi.refresh)}>
              Refresh broker fills
            </Button>
          ) : null}
          <Button variant="outline" onClick={() => q.refetch()}>
            Refresh archive
          </Button>
        </div>
        {start && end && start > end ? (
          <p role="alert" className="text-destructive">
            From date must be before Through date.
          </p>
        ) : null}
        {error || q.error ? (
          <p role="alert" className="text-destructive">
            {error || (q.error as Error).message}
          </p>
        ) : null}
        {d ? (
          <>
            <p className="text-sm">Lifetime completeness unverified</p>
            <p className="text-xs text-muted-foreground">
              Selected dates: {start || 'First recorded date'} → {end || 'Latest recorded date'} ·
              IST · SQL saved history
            </p>
            {d.summary.fill_count === 0 ? (
              <output className="block text-sm">
                No recorded {mode === 'live' ? 'Live' : 'Sandbox'} executions for these dates.
                Choose a stored date or widen the range.
              </output>
            ) : null}
            <p className="text-xs text-muted-foreground">
              {d.coverage.fill_count} fills · {d.coverage.recorded_dates.length} recorded days. Date
              coverage does not prove complete lifetime history or opening inventory.
            </p>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[
                ['Gross P&L before fees · resolved subtotal', d.summary.gross_pnl],
                ['Actual fees paid', d.summary.actual_fees],
                ['Estimated charges', d.summary.estimated_fees],
                ['Net P&L after actual fees', d.summary.net_pnl],
              ].map(([label, value]) => (
                <div key={label!} className="rounded border p-3">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <strong className="font-mono">
                    {value != null
                      ? amount(value)
                      : label === 'Actual fees paid'
                        ? mode === 'sandbox'
                          ? 'No broker fees on paper trades'
                          : 'Not reported by Kotak'
                        : label === 'Net P&L after actual fees'
                          ? 'Waiting for paid charges'
                          : 'No resolved values'}
                  </strong>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              {d.summary.gross_known_count ?? 0} / {d.summary.closed_count ?? 0} matched closes have
              resolved gross P&L; {d.summary.fees_known_fill_count} / {d.summary.fill_count} fills
              have reported paid charges.
            </p>
            <p className="text-sm">
              Estimate covers {d.fee_estimate.fill_count ?? d.summary.fill_count} executions in{' '}
              {d.fee_estimate.executed_order_count ?? 'the recorded'} executed orders
              {d.fee_estimate.recorded_dates?.length
                ? ` · ${d.fee_estimate.recorded_dates.join(' to ')}`
                : ''}
              . Zero-fill cancelled orders are excluded; filled portions of cancelled orders remain
              included.
            </p>
            <p className="text-xs text-muted-foreground">
              Gross P&L excludes fees. The table's estimated net subtracts estimated charges; actual
              paid fees and actual net require broker reports. Same-second fills at different prices
              need execution sequence to establish exact FIFO P&L.
            </p>
            <FeeBreakdown {...d.fee_estimate} />
            <div className="overflow-auto">
              <table className="w-full text-sm">
                <caption className="text-left text-xs text-muted-foreground py-2">
                  FIFO by exchange, symbol and product. Unknown inventory or charges remain
                  unresolved.
                </caption>
                <thead>
                  <tr>
                    {[
                      'Symbol / status',
                      'Entry → exit IST',
                      'Qty',
                      'Prices',
                      'Gross P&L',
                      'Estimated charges',
                      'Estimated net P&L',
                      'Actual paid fees',
                      'Chart replay',
                    ].map((h) => (
                      <th key={h} className="p-2 text-left">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {d.rows.map((row) => (
                    <tr key={row.trade_id} className="border-t">
                      <td className="p-2">
                        {row.symbol}
                        <br />
                        <span className="text-xs text-muted-foreground">
                          {row.status === 'ambiguous_execution_order'
                            ? 'Execution sequence unresolved'
                            : row.status === 'unresolved_opening_inventory'
                              ? 'Opening inventory missing'
                              : row.status === 'partial_close'
                                ? 'Partial close'
                                : 'Closed'}
                        </span>
                      </td>
                      <td className="p-2">
                        {new Date(row.entry_time).toLocaleString('en-IN', {
                          timeZone: 'Asia/Kolkata',
                        })}
                        <br />
                        {new Date(row.exit_time).toLocaleString('en-IN', {
                          timeZone: 'Asia/Kolkata',
                        })}
                      </td>
                      <td>{row.quantity}</td>
                      <td>
                        {row.entry_price} → {row.exit_price}
                      </td>
                      <td>
                        {row.gross_pnl == null
                          ? row.status === 'ambiguous_execution_order'
                            ? 'Needs fill sequence'
                            : 'Needs opening inventory'
                          : amount(row.gross_pnl)}
                      </td>
                      <td>
                        {row.estimated_fees == null
                          ? 'Needs fee estimate'
                          : amount(row.estimated_fees)}
                      </td>
                      <td>
                        {row.estimated_net_pnl == null
                          ? 'Needs resolved gross P&L'
                          : amount(row.estimated_net_pnl)}
                      </td>
                      <td>
                        {row.fees == null ? (
                          <span title="The Trade API does not report paid charges">
                            Not reported
                          </span>
                        ) : (
                          amount(row.fees)
                        )}
                      </td>
                      <td>
                        <Button
                          variant={replayId === row.trade_id ? 'default' : 'outline'}
                          onClick={() => setReplayId(row.trade_id)}
                          aria-label={`Replay recorded trade ${row.symbol} at ${row.entry_time}`}
                        >
                          Replay trade
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!d.rows.length ? (
                <p className="p-4 text-sm">No matched closes for this selection.</p>
              ) : null}
            </div>
            {replayId ? <RecordedTradeReplay tradeId={replayId} mode={mode} /> : null}
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                disabled={!cursor}
                onClick={() => setCursor(Math.max(0, cursor - 50))}
              >
                Previous
              </Button>
              <span>
                {Math.min(cursor + 50, d.total)} of {d.total} matched closes
              </span>
              <Button
                variant="outline"
                disabled={cursor + 50 >= d.total}
                onClick={() => setCursor(cursor + 50)}
              >
                Next
              </Button>
            </div>
            {d.open_inventory.length ? (
              <details>
                <summary>Recorded open or unresolved inventory ({d.open_inventory.length})</summary>
                {d.open_inventory.map((p, i) => (
                  <p key={`${p.symbol}-${i}`} className="text-sm">
                    {p.symbol} · {p.quantity} · {p.status}
                  </p>
                ))}
              </details>
            ) : null}
          </>
        ) : (
          <p>Loading recorded executions…</p>
        )}
        {mode === 'live' ? (
          <details>
            <summary className="cursor-pointer text-sm">
              Import older executions and actual charges
            </summary>
            <p className="text-xs text-muted-foreground py-2">
              Execution IDs and full timestamps required. Contract notes must be converted to the
              execution template. Duplicate IDs are checked.
            </p>
            <a className="text-primary underline" href="/neodesk/api/history/template">
              CSV template
            </a>
            <Label htmlFor="history-import" className="block mt-3">
              Execution CSV
            </Label>
            <input
              id="history-import"
              type="file"
              accept=".csv,text/csv"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) action(async () => neoReportsApi.importCSV(await file.text()))
              }}
            />
          </details>
        ) : null}
        <a
          className="text-primary underline text-sm"
          href={`/neodesk/api/history/export?${new URLSearchParams({ symbol, start, end, mode })}`}
        >
          Export matched history
        </a>
      </CardContent>
    </Card>
  )
}
