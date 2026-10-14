import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { type ChartCoverage, neoReportsApi } from '@/api/neoReports'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { NeoMarketChart } from './NeoMarketChart'

const key = (c: ChartCoverage) => `${c.exchange}:${c.symbol}:${c.interval}`
const dateTime = (s: string) => new Date(s).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })

export function SavedCharts() {
  const storage = useQuery({
    queryKey: ['neo-sql-storage'],
    queryFn: neoReportsApi.storage,
    refetchInterval: 30000,
  })
  const [identity, setIdentity] = useState(''),
    [start, setStart] = useState(''),
    [end, setEnd] = useState('')
  const [loaded, setLoaded] = useState<{ chart: ChartCoverage; start: string; end: string } | null>(
    null
  )
  const charts = storage.data?.charts ?? []
  const selected = charts.find((c) => key(c) === identity)
  useEffect(() => {
    if (identity || !charts.length) return
    const initial = charts.find((c) => c.symbol === 'NIFTY' && c.interval === '15m') ?? charts[0]
    setIdentity(key(initial))
    setStart(initial.start)
    setEnd(initial.end)
  }, [charts, identity])
  const invalid = Boolean(start && end && start > end)
  const error =
    (storage.error as Error)?.message ||
    storage.data?.backup_error ||
    storage.data?.sync_error ||
    storage.data?.chart_backfill_error ||
    storage.data?.trade_chart_error
  return (
    <Card>
      <CardHeader>
        <CardTitle>SQL history & saved charts</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm">
          Paper and Live records are retained separately. Chart candles and replay sources remain
          saved after a restart.
        </p>
        {storage.data ? (
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <span>
              Live fills <strong>{storage.data.live_fills}</strong>
            </span>
            <span>
              Paper fills <strong>{storage.data.paper_fills}</strong>
            </span>
            <span>
              History events <strong>{storage.data.history_events}</strong>
            </span>
            <span>
              Last verified backup:{' '}
              <strong>
                {storage.data.last_backup ? dateTime(storage.data.last_backup) : 'Not yet verified'}
              </strong>
            </span>
          </div>
        ) : (
          <p>Loading SQL archive status…</p>
        )}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1">
            <Label htmlFor="saved-chart-instrument">Saved instrument / timeframe</Label>
            <select
              id="saved-chart-instrument"
              value={identity}
              className="h-10 w-full rounded border bg-background px-3"
              onChange={(e) => {
                setIdentity(e.target.value)
                const c = charts.find((row) => key(row) === e.target.value)
                if (c) {
                  setStart(c.start)
                  setEnd(c.end)
                }
              }}
            >
              {charts.map((c) => (
                <option key={key(c)} value={key(c)}>
                  {c.symbol} · {c.exchange} · {c.interval === 'D' ? 'Daily' : c.interval}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="saved-chart-start">Chart from</Label>
            <input
              id="saved-chart-start"
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="h-10 rounded border bg-background px-3"
            />
          </div>
          <div>
            <Label htmlFor="saved-chart-end">Chart through</Label>
            <input
              id="saved-chart-end"
              type="date"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              className="h-10 rounded border bg-background px-3"
            />
          </div>
          <Button
            disabled={!selected || !start || !end || invalid}
            onClick={() => selected && setLoaded({ chart: selected, start, end })}
          >
            Load saved chart
          </Button>
        </div>
        {invalid ? (
          <p role="alert" className="text-sm text-destructive">
            From date must be before Through date.
          </p>
        ) : null}
        {selected ? (
          <p className="text-xs text-muted-foreground">
            {selected.count.toLocaleString('en-IN')} saved candles · {selected.start} →{' '}
            {selected.end}. Stored candles have no automatic deletion. Missing dates or
            expired-contract observations are not invented.
          </p>
        ) : (
          <p className="text-sm">
            No saved chart series yet. Broker candle downloads are archived automatically.
          </p>
        )}
        {loaded ? (
          <div className="h-[600px]">
            <NeoMarketChart
              key={`${key(loaded.chart)}:${loaded.start}:${loaded.end}`}
              symbol={loaded.chart.symbol}
              exchange={loaded.chart.exchange}
              interval={loaded.chart.interval === 'D' ? '1d' : loaded.chart.interval}
              savedRange={{ start: loaded.start, end: loaded.end }}
            />
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
