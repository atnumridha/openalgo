import { useQuery } from '@tanstack/react-query'
import { neoOverviewApi } from '@/api/neoOverview'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { amount } from './FeeBreakdown'
export function MarketOverview() {
  return import.meta.env.VITE_NEO_DESK_ENABLED === 'true' ? <EnabledOverview /> : null
}
function EnabledOverview() {
  const q = useQuery({
      queryKey: ['neo-overview'],
      queryFn: neoOverviewApi.overview,
      refetchInterval: 30000,
    }),
    d = q.data
  return (
    <Card>
      <CardHeader>
        <CardTitle>NIFTY market overview</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {d ? (
          <>
            <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
              {[
                ['NIFTY last reported', amount(d.price)],
                [
                  'Day change',
                  d.change == null
                    ? 'Unavailable'
                    : `${amount(d.change)} (${Number(d.change_pct).toFixed(2)}%)`,
                ],
                ['RSI 14 · confirmed 15m', d.rsi14 ?? 'Unavailable'],
                ['Advances', d.covered ? String(d.advances) : 'Unavailable'],
                ['Declines', d.covered ? String(d.declines) : 'Unavailable'],
                ['Unchanged', d.covered ? String(d.unchanged) : 'Unavailable'],
              ].map(([label, value]) => (
                <div key={label}>
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <strong className="font-mono">{value}</strong>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              {d.market_session} · constituent coverage {d.covered} / 50 · missing {d.missing}.{' '}
              {d.source}. Observed{' '}
              {new Date(d.observed_at).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' })}{' '}
              IST. {d.timestamp_note}
            </p>
            {d.errors?.length ? (
              <p role="alert" className="text-sm text-destructive">
                {d.errors.join(' ')}
              </p>
            ) : null}
          </>
        ) : (
          <p>Loading source-stamped context…</p>
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
