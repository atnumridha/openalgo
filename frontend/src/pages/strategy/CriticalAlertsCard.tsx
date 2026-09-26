import { useQuery } from '@tanstack/react-query'
import { BellRing, ChevronDown, CircleAlert, CircleCheck, Clock3 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { getCriticalAlerts, strategyQueryKeys } from '@/api/strategy_module'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatIst } from '@/types/strategy_module'

export default function CriticalAlertsCard({ savedStrategyIds }: { savedStrategyIds: Set<number> }) {
  const [showAll, setShowAll] = useState(false)
  const alerts = useQuery({
    queryKey: strategyQueryKeys.criticalAlerts(),
    queryFn: getCriticalAlerts,
    refetchInterval: 30_000,
  })
  const visibleAlerts = alerts.data?.filter((alert, index) =>
    showAll || index < 3 || alert.status === 'failed' || alert.status === 'unavailable' || alert.status === 'pending'
  ) ?? []
  const hiddenCount = (alerts.data?.length ?? 0) - visibleAlerts.length

  return (
    <Card aria-labelledby="critical-alerts-heading">
      <CardHeader className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle id="critical-alerts-heading" className="flex items-center gap-2">
            <BellRing aria-hidden="true" className="size-5 text-muted-foreground" />
            Critical safety alerts
          </CardTitle>
          {alerts.data && alerts.data.length > 3 && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-expanded={showAll}
              aria-controls="critical-alerts-list"
              onClick={() => setShowAll((current) => !current)}
            >
              <ChevronDown aria-hidden="true" className={`size-4 transition-transform ${showAll ? 'rotate-180' : ''}`} />
              {showAll ? 'Show fewer alerts' : `Show all ${alerts.data.length} alerts`}
            </Button>
          )}
        </div>
        <CardDescription>
          Delivery status for account and strategy safety events, including deleted strategies.
          WhatsApp upstream acceptance is not human receipt.
          {hiddenCount > 0 && ` Showing the latest three and alerts needing attention; ${hiddenCount} older alerts are hidden.`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {alerts.isError ? (
          <p role="alert" className="text-sm text-destructive">
            Could not load alert delivery status. Check the audit log and broker state directly.
          </p>
        ) : alerts.isPending ? (
          <p className="text-sm text-muted-foreground">Checking safety alerts…</p>
        ) : alerts.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">No critical safety alerts in the retention window.</p>
        ) : (
          <ul id="critical-alerts-list" className={`divide-y divide-border/50 ${showAll ? 'max-h-[28rem] overflow-y-auto pr-2' : ''}`}>
            {visibleAlerts.map((alert) => (
              <li key={alert.id} className="space-y-1 py-3 text-sm first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={alert.status === 'failed' || alert.status === 'unavailable' ? 'destructive' : 'outline'}>
                    {alert.status === 'failed' || alert.status === 'unavailable'
                      ? <CircleAlert aria-hidden="true" className="mr-1 size-3" />
                      : alert.status === 'sent' || alert.status === 'late'
                        ? <CircleCheck aria-hidden="true" className="mr-1 size-3" />
                        : <Clock3 aria-hidden="true" className="mr-1 size-3" />}
                    WhatsApp {alert.status === 'sent' ? 'accepted' : alert.status === 'late' ? 'accepted late' : alert.status}
                  </Badge>
                  {alert.strategy_id === null ? (
                    <span>Account automation</span>
                  ) : savedStrategyIds.has(alert.strategy_id) ? (
                    <Link className="text-primary underline-offset-4 hover:underline focus-visible:underline" to={`/strategy/${alert.strategy_id}`}>
                      Strategy #{alert.strategy_id}
                    </Link>
                  ) : (
                    <span>Deleted strategy #{alert.strategy_id}</span>
                  )}
                  <span className="font-mono text-xs text-muted-foreground">{alert.kind}</span>
                </div>
                <p className="whitespace-pre-wrap break-words">{alert.message}</p>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <span>Original event: {formatIst(alert.event_ts)}</span>
                  {alert.last_attempt_at && <span>Last attempt: {formatIst(alert.last_attempt_at)}</span>}
                  {alert.last_error && <span className="break-words">{alert.last_error}</span>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
