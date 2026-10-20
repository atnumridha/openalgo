import { useQuery } from '@tanstack/react-query'
import { Activity, ExternalLink, RefreshCw } from 'lucide-react'
import { useRef } from 'react'
import { Link } from 'react-router'
import { pythonStrategyApi } from '@/api/python-strategy'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { executionStage, parseExecutionLog } from '@/lib/strategyExecution'
import type { ExecutionReport } from '@/lib/strategyExecution'

const price = (value: number | null) =>
  value === null ? '—' : value.toLocaleString('en-IN', { maximumFractionDigits: 2 })
const money = (value: number) => `$${value.toFixed(2)} / ₹${(value * 85).toFixed(2)}`
const time = (date: string) =>
  new Date(date).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })

export function supportsExecutionPanel(fileName: string) {
  return /^delta_confluence_strategy(?:_\d+)?\.py$/.test(fileName)
}

export function StrategyExecutionPanel({
  strategyId,
  compact = false,
}: {
  strategyId: string
  compact?: boolean
}) {
  const cached = useRef<{ key: string; report: ExecutionReport | null; updated: string } | null>(
    null
  )
  const query = useQuery({
    queryKey: ['python-execution', strategyId],
    queryFn: async () => {
      const [strategy, files] = await Promise.all([
        pythonStrategyApi.getStrategy(strategyId),
        pythonStrategyApi.getLogFiles(strategyId),
      ])
      const latest = [...files].sort(
        (a, b) => Date.parse(b.last_modified) - Date.parse(a.last_modified)
      )[0]
      if (
        !latest ||
        (strategy.last_started &&
          Date.parse(latest.last_modified) < Date.parse(strategy.last_started))
      ) {
        cached.current = null
        return { strategy, report: null, updated: null }
      }
      const key = `${strategyId}:${latest.name}:${latest.last_modified}:${latest.size_kb}`
      if (cached.current?.key !== key) {
        const log = await pythonStrategyApi.getLogContent(strategyId, latest.name)
        cached.current = { key, report: parseExecutionLog(log.content), updated: log.last_updated }
      }
      return { strategy, ...cached.current }
    },
    refetchInterval: 3000,
    retry: false,
  })
  const data = query.data
  const report = data?.report
  const running = data?.strategy.status === 'running'
  const age = data?.updated ? Date.now() - Date.parse(data.updated) : Number.NaN
  const stale = !!report && (!Number.isFinite(age) || age > 90000 || age < -5000)
  const title = query.isError
    ? 'Execution status unavailable'
    : !data
      ? 'Reading execution status…'
      : !running
        ? 'Process stopped'
        : !report
          ? 'Waiting for execution report'
          : stale
            ? 'Report is stale'
            : executionStage(report)
  const position = report?.position
  const current = running && !stale && !query.isError
  const executed = current && (position?.open ?? 0) > 0
  return (
    <section
      aria-label="Strategy execution"
      className="rounded-lg border bg-muted/25 p-3 space-y-3 text-sm min-w-0"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold flex items-center gap-2">
          <Activity className="h-4 w-4" />
          Execution
        </span>
        <div className="flex items-center gap-2">
          {report && (
            <Badge variant="outline">{report.mode === 'live' ? 'LIVE' : 'PAPER · simulated'}</Badge>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            aria-label="Refresh execution status"
            onClick={() => query.refetch()}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${query.isFetching ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>
      <output
        className={`block font-medium ${executed ? 'text-emerald-700 dark:text-emerald-400' : 'text-amber-700 dark:text-amber-400'}`}
      >
        {title}
      </output>
      {(stale || query.isError || !running) && report && (
        <p className="text-xs text-muted-foreground">
          Last reported values below; verify current orders and exposure in Trade Book / Positions.
        </p>
      )}
      {report && (
        <>
          {report.reasons.length > 0 && (
            <ul className="list-disc pl-4 space-y-1 text-xs">
              {report.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          {position ? (
            <dl
              className={`grid ${compact ? 'grid-cols-2' : 'grid-cols-2 md:grid-cols-4'} gap-x-4 gap-y-2 text-xs`}
            >
              <div>
                <dt className="text-muted-foreground">Direction</dt>
                <dd className="font-medium">{position.side}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Entry order ID</dt>
                <dd className="font-mono break-all">{position.orderId || 'Not reported'}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {report.mode === 'live' ? 'Entry filled' : 'Simulated fill'}
                </dt>
                <dd>
                  {position.filled ?? '—'} / {position.quantity ?? '—'} contracts
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Open quantity</dt>
                <dd>{position.open ?? '—'}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Entry price</dt>
                <dd>{price(position.entry)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {report.mode === 'live' ? 'Acknowledged SL' : 'Simulated SL'}
                </dt>
                <dd>{price(position.stop)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Planned target</dt>
                <dd>{price(position.target)}</dd>
              </div>
              {position.net !== null && (
                <div>
                  <dt className="text-muted-foreground">Est. open net after costs</dt>
                  <dd>{money(position.net)}</dd>
                </div>
              )}
            </dl>
          ) : (
            <p className="text-xs">
              {report.positionKnown ? 'No open position reported' : 'Position state not reported'}
            </p>
          )}
          {report.dailyNet !== null && (
            <div className="flex flex-wrap justify-between gap-1 text-xs">
              <span className="text-muted-foreground">Today’s realized net · after fees</span>
              <span className="font-mono">{money(report.dailyNet)}</span>
            </div>
          )}
          {report.signal && (
            <div className="border-t pt-2 text-xs">
              <span className="text-muted-foreground">Last signal: </span>
              <strong>{report.signal}</strong>
              <span className="text-muted-foreground"> · a signal is not a fill</span>
              {!compact && report.signalReason && <p className="mt-1">{report.signalReason}</p>}
            </div>
          )}
          {!compact && report.warnings.length > 0 && (
            <details className="text-xs text-muted-foreground">
              <summary>Execution warnings</summary>
              <ul className="list-disc pl-4 mt-1">
                {report.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
      <div className="text-[11px] text-muted-foreground space-y-1 border-t pt-2">
        <p>
          {data?.updated ? `Log updated ${time(data.updated)} IST` : 'No current report available'}
        </p>
        <p>
          Checks every 3s. Controller reports about once a minute and on some state changes. This is
          a log snapshot.
        </p>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs">
        <Link
          className="text-primary underline underline-offset-4"
          to={`/python/${strategyId}/logs`}
        >
          Logs
        </Link>
        <Link className="text-primary underline underline-offset-4" to="/orderbook">
          Order Book
        </Link>
        <Link className="text-primary underline underline-offset-4" to="/tradebook">
          Trade Book
        </Link>
        {!compact && (
          <Link
            className="text-primary underline underline-offset-4 flex gap-1 items-center"
            to="/positions"
          >
            Positions
            <ExternalLink className="h-3 w-3" />
          </Link>
        )}
      </div>
      {!compact && (
        <p className="text-xs text-muted-foreground">
          Match the entry order ID to Trade Book to confirm this strategy’s fills. Account books
          also include manual trades. A flat position does not mean there were no earlier trades.
        </p>
      )}
    </section>
  )
}
