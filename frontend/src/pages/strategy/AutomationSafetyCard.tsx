import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import {
  getLiveAuthorization,
  grantLiveAuthorization,
  installStarterPack,
  revokeLiveAuthorization,
  strategyQueryKeys,
} from '@/api/strategy_module'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card'
import type { LiveAuthorizationStatus, StarterPackInstallResult, StrategySummary } from '@/types/strategy_module'

const GOVERNOR_LIMITS = [
  'Maximum two simultaneous cash positions',
  'Maximum one simultaneous NIFTY options position',
  'Maximum 4% combined configured open risk of available cash',
  'Maximum 1.5% configured cash risk per trade',
  'Maximum 3% configured long-option risk per minimum lot',
  'At least 20% of available cash remains as a buffer',
  'Protective risk and a reward-to-risk target of at least 1.5 are required',
  '4% daily module loss or three stopped runs blocks new entries',
  'Two stopped runs trigger a 30-minute entry cooldown',
  'Intraday entries: 09:20–15:00 IST; option entries stop at 14:45 IST',
]

const MAX_TIMER_DELAY = 2_147_483_647

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback
}

function sessionExpiryTimestamp(sessionDay: string, expiresAt: string) {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(sessionDay)
  const time = /^(\d{2}):(\d{2})$/.exec(expiresAt)
  if (!day || !time) return Number.NaN

  const year = Number(day[1])
  const month = Number(day[2])
  const date = Number(day[3])
  const hour = Number(time[1])
  const minute = Number(time[2])
  const calendarDay = new Date(Date.UTC(year, month - 1, date))
  if (
    hour > 23 ||
    minute > 59 ||
    calendarDay.getUTCFullYear() !== year ||
    calendarDay.getUTCMonth() !== month - 1 ||
    calendarDay.getUTCDate() !== date
  ) {
    return Number.NaN
  }

  return Date.parse(`${sessionDay}T${expiresAt}:00+05:30`)
}

function formatExpiry(expiresAt: number) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(expiresAt))
  const value = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? ''
  return `${value('day')} ${value('month')} ${value('year')}, ${value('hour')}:${value('minute')} IST`
}

function StrategyLinks({
  id,
  title,
  strategies,
}: {
  id: string
  title: string
  strategies: StrategySummary[]
}) {
  if (strategies.length === 0) return null
  return (
    <section aria-labelledby={id} className="space-y-2">
      <h3 id={id} className="text-sm font-medium">
        {title}
      </h3>
      <ul className="space-y-1 text-sm">
        {strategies.map((strategy) => (
          <li key={strategy.id}>
            <Link
              to={`/strategy/${strategy.id}`}
              className="rounded-sm text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {strategy.name}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

function DialogError({ message }: { message: string }) {
  if (!message) return null
  return (
    <p role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
      {message}
    </p>
  )
}

export default function AutomationSafetyCard() {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState<'grant' | 'revoke' | 'install' | null>(null)
  const [result, setResult] = useState<StarterPackInstallResult | null>(null)
  const [statusMessage, setStatusMessage] = useState('')
  const [dialogError, setDialogError] = useState('')
  const [now, setNow] = useState(() => Date.now())

  const authorizationQuery = useQuery({
    queryKey: strategyQueryKeys.liveAuthorization(),
    queryFn: getLiveAuthorization,
    staleTime: 30_000,
  })
  const authorization = authorizationQuery.data
  const expiresAt = authorization
    ? sessionExpiryTimestamp(authorization.session_day, authorization.expires_at)
    : Number.NaN
  const authorizationActive =
    authorization?.active === true && Number.isFinite(expiresAt) && expiresAt > now
  const authorizationExpired =
    authorization?.active === true && (!Number.isFinite(expiresAt) || expiresAt <= now)
  const authorizationUnavailable = !authorization && authorizationQuery.isError

  useEffect(() => {
    if (!authorization?.active || !Number.isFinite(expiresAt)) return
    const delay = expiresAt - now
    if (delay <= 0) return
    const timeout = window.setTimeout(() => {
      setNow(Date.now())
      void authorizationQuery.refetch()
    }, Math.min(delay, MAX_TIMER_DELAY))
    return () => window.clearTimeout(timeout)
  }, [authorization?.active, authorizationQuery.refetch, expiresAt, now])

  const openConfirmation = (action: 'grant' | 'revoke' | 'install') => {
    setDialogError('')
    setConfirming(action)
  }

  const closeConfirmation = (open: boolean) => {
    if (!open) {
      setDialogError('')
      setConfirming(null)
    }
  }

  const mutationError = (error: unknown, fallback: string) => {
    const message = errorMessage(error, fallback)
    setDialogError(message)
    setStatusMessage(message)
  }

  const applyAuthorization = (next: LiveAuthorizationStatus, message: string) => {
    queryClient.setQueryData(strategyQueryKeys.liveAuthorization(), next)
    setNow(Date.now())
    setDialogError('')
    setStatusMessage(message)
    setConfirming(null)
  }

  const grantMutation = useMutation({
    mutationFn: grantLiveAuthorization,
    onSuccess: (next) => applyAuthorization(next, 'Live authorization granted for this session.'),
    onError: (error) => mutationError(error, 'Could not authorize live automation.'),
  })

  const revokeMutation = useMutation({
    mutationFn: revokeLiveAuthorization,
    onSuccess: (next) => applyAuthorization(next, 'Live authorization revoked.'),
    onError: (error) => mutationError(error, 'Could not revoke live authorization.'),
  })

  const installMutation = useMutation({
    mutationFn: installStarterPack,
    onSuccess: (next) => {
      setResult(next)
      setStatusMessage(
        next.created.length > 0
          ? 'Recommended starter pack installed. Review the created strategies below.'
          : 'Recommended starter pack is already installed.'
      )
      queryClient.invalidateQueries({ queryKey: strategyQueryKeys.strategies() })
      setDialogError('')
      setConfirming(null)
    },
    onError: (error) => mutationError(error, 'Could not install the starter pack.'),
  })

  const isMutating = grantMutation.isPending || revokeMutation.isPending || installMutation.isPending
  const authorizationBadge = authorizationUnavailable
    ? 'Authorization unavailable'
    : authorizationExpired
      ? 'Authorization expired'
      : authorizationActive
        ? 'Session authorization active'
        : 'Sandbox only'
  const authorizationHeading = authorizationQuery.isLoading
    ? 'Checking live automation authorization…'
    : authorizationUnavailable
      ? 'Live automation authorization status unavailable'
      : authorizationExpired
        ? 'Live automation authorization has expired'
        : authorizationActive
          ? 'Live automation authorized for this session'
          : 'Live automation authorization is inactive'

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1">
            <h2 className="text-lg leading-none font-semibold">Automation safety controls</h2>
            <CardDescription>
              Sandbox strategies can run without this authorization. New automated live entries
              must pass every gate below.
            </CardDescription>
          </div>
          <Badge
            variant={authorizationUnavailable || authorizationExpired ? 'destructive' : authorizationActive ? 'default' : 'secondary'}
            className="w-fit"
          >
            {authorizationBadge}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <section aria-labelledby="live-authorization-heading" className="rounded-lg border bg-muted/30 p-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1">
              <h3 id="live-authorization-heading" className="font-medium">
                {authorizationHeading}
              </h3>
              {authorization && Number.isFinite(expiresAt) ? (
                <p className="text-sm text-muted-foreground">
                  Expires: {formatExpiry(expiresAt)}
                </p>
              ) : authorization ? (
                <p className="text-sm text-destructive">Authorization expiry is unavailable.</p>
              ) : authorizationQuery.error ? (
                <p className="text-sm text-destructive">Could not load authorization status.</p>
              ) : null}
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button
                type="button"
                variant="outline"
                className="min-h-11"
                disabled={authorizationQuery.isFetching || isMutating}
                onClick={() => void authorizationQuery.refetch()}
              >
                Refresh status
              </Button>
              {authorizationActive ? (
                <Button
                  type="button"
                  variant="destructive"
                  className="min-h-11"
                  disabled={isMutating}
                  onClick={() => openConfirmation('revoke')}
                >
                  Revoke authorization
                </Button>
              ) : (
                <Button
                  type="button"
                  className="min-h-11"
                  disabled={!authorization || isMutating}
                  onClick={() => openConfirmation('grant')}
                >
                  Authorize live automation
                </Button>
              )}
            </div>
          </div>
          <p className="mt-3 text-sm text-muted-foreground">
            Each strategy must also be individually live-enabled.
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Revoking authorization blocks new live entries; existing stops, targets, and exits
            remain allowed.
          </p>
        </section>

        <section aria-labelledby="governor-heading" className="space-y-3">
          <div>
            <h3 id="governor-heading" className="font-medium">
              Portfolio governor defaults
            </h3>
            <p className="text-sm text-muted-foreground">
              These limits apply to Strategy Module live automation before a new entry is sent.
              Sandbox runs are unaffected.
            </p>
          </div>
          <ul className="grid gap-2 text-sm sm:grid-cols-2">
            {GOVERNOR_LIMITS.map((limit) => (
              <li key={limit} className="rounded-md border bg-background px-3 py-2">
                {limit}
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="starter-pack-heading" className="rounded-lg border border-dashed p-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1">
              <h3 id="starter-pack-heading" className="font-medium">
                Recommended sandbox starter pack
              </h3>
              <p className="text-sm text-muted-foreground">
                Six stopped, sandbox-only templates for deterministic Flow or Agent signal producers.
              </p>
              <p className="text-sm font-medium">Installing does not start trading.</p>
            </div>
            <Button
              type="button"
              variant="secondary"
              className="min-h-11"
              disabled={isMutating}
              onClick={() => openConfirmation('install')}
            >
              Install recommended starter pack
            </Button>
          </div>
        </section>

        <section aria-labelledby="next-steps-heading" className="space-y-2">
          <h3 id="next-steps-heading" className="font-medium">
            Safe next steps
          </h3>
          <p className="text-sm text-muted-foreground">
            Use the Agent to draft a Flow, then review and activate that Flow separately after
            testing your strategies in sandbox mode.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button asChild variant="outline" className="min-h-11">
              <Link to="/agent">Open Agent</Link>
            </Button>
            <Button asChild variant="outline" className="min-h-11">
              <Link to="/flow">Review Flows</Link>
            </Button>
          </div>
        </section>

        {result ? (
          <section aria-labelledby="starter-pack-results-heading" className="space-y-4 rounded-lg bg-muted/30 p-4">
            <h3 id="starter-pack-results-heading" className="font-medium">
              Starter pack results
            </h3>
            <StrategyLinks id="created-strategies" title="Created strategies" strategies={result.created} />
            <StrategyLinks id="existing-strategies" title="Existing strategies" strategies={result.existing} />
            {Object.entries(result.webhook_tokens).length > 0 ? (
              <div className="space-y-2">
                <h4 className="text-sm font-medium">New webhook tokens — copy now</h4>
                {Object.entries(result.webhook_tokens).map(([name, token]) => (
                  <p key={name} className="rounded-md border bg-background p-2 text-sm">
                    <span className="font-medium">{name}: </span>
                    <code className="break-all">{token}</code>
                  </p>
                ))}
              </div>
            ) : null}
          </section>
        ) : null}

        <output aria-live="polite" className="block min-h-5 text-sm text-muted-foreground">
          {statusMessage}
        </output>
      </CardContent>

      <AlertDialog open={confirming === 'grant'} onOpenChange={closeConfirmation}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Authorize live automation for this session?</AlertDialogTitle>
            <AlertDialogDescription>
              This permits new automated live entries only for the current trading session. Every
              strategy still needs its own live-enabled setting and governor approval.
            </AlertDialogDescription>
            <DialogError message={dialogError} />
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="min-h-11" disabled={grantMutation.isPending}>
              Cancel
            </AlertDialogCancel>
            <Button
              type="button"
              variant="destructive"
              className="min-h-11"
              disabled={grantMutation.isPending}
              onClick={() => grantMutation.mutate()}
            >
              {grantMutation.isPending ? 'Authorizing…' : 'Authorize for this session'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirming === 'revoke'} onOpenChange={closeConfirmation}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke live automation authorization?</AlertDialogTitle>
            <AlertDialogDescription>
              New automated live entries will be blocked for this session. Existing exits, stops,
              and protective behavior remain allowed.
            </AlertDialogDescription>
            <DialogError message={dialogError} />
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="min-h-11" disabled={revokeMutation.isPending}>
              Cancel
            </AlertDialogCancel>
            <Button
              type="button"
              variant="destructive"
              className="min-h-11"
              disabled={revokeMutation.isPending}
              onClick={() => revokeMutation.mutate()}
            >
              {revokeMutation.isPending ? 'Revoking…' : 'Revoke authorization'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirming === 'install'} onOpenChange={closeConfirmation}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Review recommended starter pack</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-3 text-sm text-muted-foreground">
                <p>
                  Every installed strategy is stopped, sandbox-only, live-disabled, and
                  unscheduled.
                </p>
                <p>Installing does not start trading.</p>
                <p>
                  You can delete these strategies later through the existing strategy controls.
                  Their signal producers remain separately reviewed and activated.
                </p>
              </div>
            </AlertDialogDescription>
            <DialogError message={dialogError} />
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="min-h-11" disabled={installMutation.isPending}>
              Cancel
            </AlertDialogCancel>
            <Button
              type="button"
              className="min-h-11"
              disabled={installMutation.isPending}
              onClick={() => installMutation.mutate()}
            >
              {installMutation.isPending ? 'Installing…' : 'Install sandbox starter pack'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
