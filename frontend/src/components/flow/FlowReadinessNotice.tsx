import { AlertTriangle, Clock, ExternalLink } from 'lucide-react'
import { Link } from 'react-router'
import type { FlowReadiness } from '@/api/flow'
import { cn } from '@/lib/utils'

export function FlowReadinessNotice({ readiness, className }: {
  readiness?: FlowReadiness
  className?: string
}) {
  if (!readiness?.reasons.length) return null
  const blocked = readiness.reasons.some((reason) => reason.blocking)
  const Icon = blocked ? AlertTriangle : Clock
  return (
    <div role="status" className={cn(
      'min-w-0 rounded-md border p-3 text-sm',
      blocked ? 'border-amber-500/30 bg-amber-500/5' : 'border-border bg-muted/30', className,
    )}>
      <div className="flex items-center gap-2 font-medium">
        <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />
        {readiness.label}
      </div>
      {readiness.reasons.map((reason) => (
        <div key={`${reason.code}-${reason.strategy_id ?? ''}`} className="mt-1 break-words text-muted-foreground">
          <p>{reason.message}</p>
          {reason.link && (
            <Link to={reason.link} onClick={(event) => event.stopPropagation()}
              className="mt-1 inline-flex items-center gap-1 font-medium text-primary underline underline-offset-4">
              {reason.link === '/broker' ? 'Reconnect broker' : reason.link === '/strategy' ? 'View strategies' : reason.link === '/apikey' ? 'Account settings' : 'Review strategy'}
              <ExternalLink aria-hidden="true" className="h-3 w-3" />
            </Link>
          )}
        </div>
      ))}
    </div>
  )
}
