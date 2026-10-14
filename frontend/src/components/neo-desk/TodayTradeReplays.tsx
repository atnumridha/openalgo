import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { neoReportsApi } from '@/api/neoReports'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { amount } from './FeeBreakdown'
import { RecordedTradeReplay } from './RecordedTradeReplay'

export function TodayTradeReplays() {
  const [mode, setMode] = useState('live'),
    [cursor, setCursor] = useState(0),
    [selected, setSelected] = useState('')
  const today = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
  const q = useQuery({
    queryKey: ['neo-today-replay-trades', today, mode, cursor],
    queryFn: () => neoReportsApi.history('', today, today, cursor, 'free_offer', mode),
    refetchInterval: 60000,
  })
  return (
    <Card>
      <CardHeader>
        <CardTitle>Today’s trade replays</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-3 items-center">
          <p className="text-sm">{today} · IST · recorded executions</p>
          <Label htmlFor="today-replay-mode">Trade mode</Label>
          <select
            id="today-replay-mode"
            value={mode}
            onChange={(e) => {
              setMode(e.target.value)
              setCursor(0)
              setSelected('')
            }}
            className="h-10 rounded border bg-background px-3"
          >
            <option value="live">Live · Kotak account</option>
            <option value="sandbox">Sandbox · paper trades</option>
          </select>
        </div>
        {q.error ? (
          <p role="alert" className="text-destructive">
            {q.error.message}
          </p>
        ) : null}
        {!q.data ? (
          <output>Loading today’s recorded trades…</output>
        ) : (
          <>
            <p className="text-sm">
              {q.data.total} matched closes · {q.data.summary.fill_count} fills today. Open
              inventory appears in the saved trade report.
            </p>
            {!q.data.rows.length ? (
              <output className="block text-sm">
                No recorded {mode === 'live' ? 'Live' : 'Sandbox'} closes today. Backtested trades
                are shown separately below.
              </output>
            ) : (
              <div className="overflow-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      {[
                        'Instrument',
                        'Entry → exit IST',
                        'Quantity',
                        'Fill prices',
                        'Gross P&L',
                        'Replay',
                      ].map((h) => (
                        <th key={h} className="text-left p-2">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {q.data.rows.slice(0, 10).map((r) => (
                      <tr key={r.trade_id} className="border-t">
                        <td className="p-2">
                          {r.symbol}
                          <p className="text-xs text-muted-foreground">
                            {r.status.replaceAll('_', ' ')}
                          </p>
                        </td>
                        <td>
                          {new Date(r.entry_time).toLocaleTimeString('en-GB', {
                            timeZone: 'Asia/Kolkata',
                          })}{' '}
                          →{' '}
                          {new Date(r.exit_time).toLocaleTimeString('en-GB', {
                            timeZone: 'Asia/Kolkata',
                          })}
                        </td>
                        <td>{r.quantity}</td>
                        <td>
                          ₹{r.entry_price} → ₹{r.exit_price}
                        </td>
                        <td>{amount(r.gross_pnl)}</td>
                        <td>
                          <Button
                            variant={selected === r.trade_id ? 'default' : 'outline'}
                            onClick={() => setSelected(r.trade_id)}
                            aria-label={`Replay today's trade ${r.symbol} at ${r.entry_time}`}
                          >
                            Replay trade
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {q.data.total > 10 ? (
              <div className="flex gap-3 items-center">
                <Button
                  variant="outline"
                  disabled={!cursor}
                  onClick={() => {
                    setCursor(Math.max(0, cursor - 10))
                    setSelected('')
                  }}
                >
                  Previous trades
                </Button>
                <span>
                  {Math.min(cursor + 10, q.data.total)} / {q.data.total}
                </span>
                <Button
                  variant="outline"
                  disabled={cursor + 10 >= q.data.total}
                  onClick={() => {
                    setCursor(cursor + 10)
                    setSelected('')
                  }}
                >
                  Next trades
                </Button>
              </div>
            ) : null}
          </>
        )}
        {selected ? <RecordedTradeReplay tradeId={selected} mode={mode} /> : null}
      </CardContent>
    </Card>
  )
}
