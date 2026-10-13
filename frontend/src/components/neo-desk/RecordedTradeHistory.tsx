import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { neoReportsApi } from '@/api/neoReports'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { FeeBreakdown, amount } from './FeeBreakdown'
export function RecordedTradeHistory() {
  return import.meta.env.VITE_NEO_DESK_ENABLED === 'true' ? <EnabledHistory /> : null
}
function EnabledHistory() {
  const [symbol, setSymbol] = useState(''),
    [start, setStart] = useState(''),
    [end, setEnd] = useState(''),
    [cursor, setCursor] = useState(0),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false)
  const q = useQuery({
    queryKey: ['neo-history', symbol, start, end, cursor],
    queryFn: () => neoReportsApi.history(symbol, start, end, cursor),
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
        <CardTitle>Recorded Kotak executions</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Broker account history, separate from strategy-owned Sandbox results.
        </p>
        <div className="flex flex-wrap items-end gap-3">
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
          <Button disabled={busy} onClick={() => action(neoReportsApi.refresh)}>
            Refresh broker fills
          </Button>
          <Button variant="outline" onClick={() => q.refetch()}>
            Refresh archive
          </Button>
        </div>
        {error || q.error ? (
          <p role="alert" className="text-destructive">
            {error || (q.error as Error).message}
          </p>
        ) : null}
        {d ? (
          <>
            <p className="text-sm">Lifetime completeness unverified</p>
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
                  <strong className="font-mono">{amount(value)}</strong>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              {d.summary.gross_known_count ?? 0} / {d.summary.closed_count ?? 0} matched closes have
              resolved gross P&L; {d.summary.fees_known_fill_count} / {d.summary.fill_count} fills
              have reported paid charges.
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
                      'Actual fees',
                      'Net P&L',
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
                        <span className="text-xs text-muted-foreground">{row.status}</span>
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
                      <td>{amount(row.gross_pnl)}</td>
                      <td>{amount(row.fees)}</td>
                      <td>{amount(row.net_pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!d.rows.length ? (
                <p className="p-4 text-sm">No matched closes for this selection.</p>
              ) : null}
            </div>
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
        <a
          className="text-primary underline text-sm"
          href={'/neodesk/api/history/export?' + new URLSearchParams({ symbol, start, end })}
        >
          Export matched history
        </a>
      </CardContent>
    </Card>
  )
}
