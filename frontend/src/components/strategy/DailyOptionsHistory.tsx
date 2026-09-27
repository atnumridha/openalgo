import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import {
  cancelDailyArchive,
  dailyBase,
  dailyKey,
  getDailyArchive,
  getDailySnapshot,
  updateDailyArchive,
} from '@/api/nse-daily'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const count = (value?: number) => (value ?? 0).toLocaleString('en-IN')

export default function DailyOptionsHistory() {
  const client = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const query = useQuery({
    queryKey: dailyKey,
    queryFn: getDailyArchive,
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 3_000 : 30_000),
  })
  const data = query.data
  const refresh = () => void client.invalidateQueries({ queryKey: dailyKey })
  const update = useMutation({
    mutationFn: updateDailyArchive,
    onSuccess: (result) => {
      client.setQueryData(dailyKey, result)
      refresh()
    },
  })
  const cancel = useMutation({ mutationFn: cancelDailyArchive, onSuccess: refresh })
  const snapshot = useQuery({
    queryKey: [...dailyKey, 'snapshot', data?.end],
    queryFn: getDailySnapshot,
    enabled: expanded && Boolean(data?.end),
  })
  const running = data?.status === 'running' || update.isPending
  const error = update.isError || cancel.isError

  return (
    <Card className="border-l-4 border-l-primary">
      <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <CardTitle>Daily options history</CardTitle>
          <CardDescription>
            Official NSE prices, volume and open interest. No broker login or file upload needed.
          </CardDescription>
        </div>
        <Badge variant="outline" className="w-fit shrink-0">
          Daily analysis
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div aria-live="polite" className="space-y-1">
            <p className="text-lg font-semibold tabular-nums">
              {count(data?.session_count)} sessions saved
            </p>
            {data?.start && data.end ? (
              <p className="text-sm text-muted-foreground">
                {data.start} to {data.end}
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                Download history from April 2020 through the last completed day.
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => {
                cancel.reset()
                update.mutate()
              }}
              disabled={running || query.isPending}
            >
              {running ? (
                <RefreshCw className="size-4 motion-safe:animate-spin" />
              ) : (
                <Download className="size-4" />
              )}
              {running
                ? 'Downloading…'
                : data?.session_count
                  ? 'Update NSE history'
                  : 'Download NSE history'}
            </Button>
            {running && (
              <Button
                variant="outline"
                disabled={cancel.isPending || cancel.isSuccess}
                onClick={() => cancel.mutate()}
              >
                {cancel.isPending || cancel.isSuccess ? 'Pausing…' : 'Pause download'}
              </Button>
            )}
            {data?.end && (
              <Button variant="outline" asChild>
                <a href={`${dailyBase}/export?session=${data.end}&symbol=NIFTY`}>
                  Download latest NIFTY CSV
                </a>
              </Button>
            )}
          </div>
        </div>
        {running && (
          <div className="space-y-2">
            <progress
              aria-label="Daily history download progress"
              value={data?.processed_dates ?? 0}
              max={data?.total_dates || 1}
              className="h-2 w-full accent-primary"
            />
            <p className="text-sm text-muted-foreground">
              {count(data?.processed_dates)} of {count(data?.total_dates)} dates checked. Recent
              sessions download first; you can leave this page.
            </p>
          </div>
        )}
        {query.isError && (
          <p role="alert" className="text-sm text-destructive">
            Daily history could not be loaded.{' '}
            <button type="button" className="underline" onClick={refresh}>
              Try again
            </button>
            .
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            The download could not {cancel.isError ? 'pause' : 'start'}. Try again.
          </p>
        )}
        {data?.message && !running && <output className="block text-sm">{data.message}</output>}
        <p className="rounded-md bg-muted/50 p-3 text-sm text-muted-foreground">
          Use this for daily market context. It cannot test five-minute entries, stop-losses or
          execution quality. Intraday strategy tests still require matching intraday option prices
          below.
        </p>
        <details onToggle={(event) => setExpanded(event.currentTarget.open)}>
          <summary className="cursor-pointer text-sm font-medium">
            View coverage and latest NIFTY activity
          </summary>
          <div className="mt-4 space-y-3 text-sm">
            <p>{count(data?.option_rows)} option observations saved across NSE underlyings.</p>
            <p className="text-muted-foreground">
              NSE returned no file for {count(data?.unavailable_count)} checked dates, which may
              include weekends or holidays. {count(data?.error_count)} dates need another download
              attempt. Missing prices are never filled in.
            </p>
            <a
              className="underline underline-offset-4"
              href="https://www.nseindia.com/all-reports-derivatives"
              target="_blank"
              rel="noreferrer"
            >
              Official NSE source
            </a>
            {snapshot.isError && (
              <p role="alert">
                The saved daily view could not be read. Update history to verify and repair the
                files.
              </p>
            )}
            {snapshot.data?.session && (
              <>
                <p>
                  Most active NIFTY contracts on {snapshot.data.session}. Open interest is in
                  underlying units; volume is in contracts. These are daily observations, not fill
                  guarantees.
                </p>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Expiry</TableHead>
                        <TableHead>Strike / type</TableHead>
                        <TableHead>Close</TableHead>
                        <TableHead>Volume</TableHead>
                        <TableHead>Open interest</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {snapshot.data.contracts.slice(0, 10).map((row) => (
                        <TableRow key={`${row.expiry}-${row.strike}-${row.option_type}`}>
                          <TableCell>{row.expiry}</TableCell>
                          <TableCell>
                            {row.strike} {row.option_type}
                          </TableCell>
                          <TableCell>₹{count(row.close)}</TableCell>
                          <TableCell>{count(row.traded_contracts)}</TableCell>
                          <TableCell>{count(row.open_interest_units)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </>
            )}
          </div>
        </details>
      </CardContent>
    </Card>
  )
}
