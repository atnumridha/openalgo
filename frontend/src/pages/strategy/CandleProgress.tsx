import { useQuery } from '@tanstack/react-query'
import { getAutomationLogs, type MonitorStrategy } from '@/api/automation_monitor'

type CandleHistory = { symbol: string; interval: string; candles: number; last_bar_at: string }
function isHistory(value: unknown): value is CandleHistory {
  if (!value || typeof value !== 'object') return false
  const item = value as CandleHistory
  return (
    typeof item.symbol === 'string' &&
    typeof item.interval === 'string' &&
    Number.isInteger(item.candles) &&
    item.candles >= 0 &&
    typeof item.last_bar_at === 'string'
  )
}
const stamp = (value: string) => {
  const date = new Date(value)
  return Number.isFinite(date.getTime())
    ? date.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false }) + ' IST'
    : 'Time unavailable'
}

/** Read retained evidence; a between-candle poll must not hide warm-up progress. */
export default function CandleProgress({ row, clock }: { row: MonitorStrategy; clock: number }) {
  const profile = row.configuration.profile
  const query = useQuery({
    queryKey: ['automation-candle-progress', row.id, row.mode, profile],
    queryFn: () => getAutomationLogs(row.id, 'events'),
    refetchInterval: 10000,
    retry: false,
  })
  const assessment = query.data?.items.find((item) => {
    if (item.kind !== 'signal_evaluation' || !item.details || typeof item.details !== 'object')
      return false
    const detail = item.details as Record<string, unknown>
    return (
      detail.mode === row.mode &&
      detail.profile === profile &&
      Array.isArray(detail.history) &&
      detail.history.some(isHistory)
    )
  })
  const detail = assessment?.details as Record<string, unknown> | undefined
  const history = Array.isArray(detail?.history) ? detail.history.filter(isHistory) : []
  const recorded = Date.parse(assessment?.at ?? '')
  const historical = !Number.isFinite(recorded) || clock - recorded > 360000
  return (
    <section className="rounded-xl border bg-card p-5" aria-label="Candle collection">
      <h3 className="font-semibold">
        Candle collection · {row.mode === 'live' ? 'Live' : 'Sandbox'}
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Candle collection is separate from a trade. These rules need completed market candles
        before they can evaluate an entry.
      </p>
      {query.isError ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          Candle assessment unavailable. Displayed evidence may be old.
        </p>
      ) : null}
      {assessment ? (
        <>
          <p className="mt-3 text-xs text-muted-foreground">
            Last recorded candle assessment: {stamp(assessment.at ?? '')}
          </p>
          {historical && (
            <p className="mt-2 text-sm text-amber-600 dark:text-amber-400">
              Historical assessment — more than 6 minutes old or timestamp unavailable.
            </p>
          )}
          <p className="mt-2 text-sm">
            {typeof detail?.reason === 'string' ? detail.reason : 'Recorded candle history'}
          </p>
          <ul className="mt-3 space-y-2 text-sm">
            {history.map((item, index) => {
              const required =
                item.interval === '5m'
                  ? profile === 'receiver_trend'
                    ? 35
                    : 10
                  : item.interval === '15m'
                    ? 2
                    : null
              return (
                <li key={`${item.symbol}-${item.interval}-${index}`}>
                  <span className="font-medium">
                    {item.symbol} · {item.interval}
                  </span>
                  <div>
                    {item.candles}
                    {required === null ? '' : ` / ${required}`} completed candles · last close{' '}
                    {stamp(item.last_bar_at)}
                  </div>
                </li>
              )
            })}
          </ul>
        </>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">
          {query.isPending
            ? 'Loading recorded candle progress…'
            : 'No candle assessment recorded in the latest events for this mode.'}
        </p>
      )}
      <p className="mt-3 text-xs text-muted-foreground">
        Counts alone do not confirm readiness: candles must be contiguous and fresh; the signal,
        option data and risk checks must also pass. Sandbox uses market signals for simulated fills.
      </p>
    </section>
  )
}
