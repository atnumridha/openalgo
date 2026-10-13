import { useThemeStore } from '@/stores/themeStore'
import { useQuery } from '@tanstack/react-query'
import { neoOverviewApi } from '@/api/neoOverview'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { amount } from './FeeBreakdown'
export function ExecutionFeedback() {
  return import.meta.env.VITE_NEO_DESK_ENABLED === 'true' ? <EnabledFeedback /> : null
}
function EnabledFeedback() {
  const mode = useThemeStore(s => s.appMode)
  const q = useQuery({
      queryKey: ['neo-health', mode],
      queryFn: neoOverviewApi.health,
      refetchInterval: 15000,
    }),
    d = q.data
  return (
    <Card>
      <CardHeader>
        <CardTitle>Execution readiness</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {d ? (
          <>
            <p className="text-sm">
              {d.mode} · {d.activation} · streaming server{' '}
              {d.proxy.alive ? 'running' : 'unavailable'}
            </p>
            <div className="flex flex-wrap gap-6 text-sm">
              <p>
                Broker trading allowance{' '}
                <strong>{amount(d.account.value?.availabletradinglimit)}</strong>
              </p>
              <p>
                Broker cash <strong>{amount(d.account.value?.availablecash)}</strong>
              </p>
              <p>
                Broker refresh age{' '}
                <strong>
                  {d.account.age_seconds == null ? 'Unavailable' : `${d.account.age_seconds}s`}
                </strong>
              </p>
            </div>
            {d.account.error ? (
              <p role="alert" className="text-destructive">
                {d.account.error} Last known funds are retained.
              </p>
            ) : null}
            <p className="text-sm">{d.waiting_reason}</p>
            {d.blockers.length ? (
              <ul className="list-disc pl-5 text-sm">
                {d.blockers.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm">
                Waiting for a qualified confirmed setup. Connection readiness does not imply a trade
                signal.
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              Broker account values are separate from strategy-owned Sandbox results. {d.note}
            </p>
          </>
        ) : (
          <p>Checking source and account readiness…</p>
        )}
        {q.error ? (
          <p role="alert" className="text-destructive">
            {(q.error as Error).message}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}
