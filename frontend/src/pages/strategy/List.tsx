// pages/strategy/List.tsx
// Saved strategies: status, mode and P&L at a glance.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUpRight,
  Play,
  Plus,
  Power,
  PowerOff,
  RotateCcw,
  ShieldCheck,
  ShieldOff,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import {
  deleteStrategy,
  disableStrategyAutomation,
  enableStrategyAutomation,
  executeSandboxReset,
  getLiveAuthorization,
  listStrategies,
  previewSandboxReset,
  setLiveEnabled,
  startAllLiveStrategies,
  startAllSandboxStrategies,
  startRun,
  strategyQueryKeys,
  useStrategyListPnl,
} from '@/api/strategy_module'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import {
  type AutomationControlResult,
  type AutomationState,
  type BulkAutomationResult,
  formatIst,
  formatListPnl,
  formatPnl,
  pnlToneClass,
  type RunMode,
  type StrategyStatus,
  type StrategySummary,
  universeTabLabel,
} from '@/types/strategy_module'
import { showToast } from '@/utils/toast'
import AutomationSafetyCard from './AutomationSafetyCard'
import CriticalAlertsCard from './CriticalAlertsCard'

function statusBadgeVariant(
  status: StrategyStatus
): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'running':
      return 'default'
    case 'paused':
      return 'secondary'
    case 'errored':
      return 'destructive'
    default:
      return 'outline'
  }
}

function automationLabel(state: AutomationState): string {
  switch (state) {
    case 'armed':
      return 'Armed'
    case 'closing':
      return 'Closing…'
    case 'close_failed':
      return 'Close failed'
    default:
      return 'Disabled'
  }
}

function automationVariant(
  state: AutomationState
): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (state === 'armed') return 'default'
  if (state === 'close_failed') return 'destructive'
  if (state === 'closing') return 'secondary'
  return 'outline'
}

export default function StrategyList() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [deleteTargetId, setDeleteTargetId] = useState<number | null>(null)
  const [resetOpen, setResetOpen] = useState(false)
  const [disableTarget, setDisableTarget] = useState<StrategySummary | null>(null)
  const [bulkResult, setBulkResult] = useState<BulkAutomationResult | null>(null)
  const [liveStartOpen, setLiveStartOpen] = useState(false)
  const [liveEnableTarget, setLiveEnableTarget] = useState<StrategySummary | null>(null)
  const [liveConfirmation, setLiveConfirmation] = useState('')
  const [controlResult, setControlResult] = useState<AutomationControlResult | null>(null)
  const [controlError, setControlError] = useState<string | null>(null)
  const [startTarget, setStartTarget] = useState<StrategySummary | null>(null)
  const [startMode, setStartMode] = useState<RunMode>('sandbox')
  const [startConfirmation, setStartConfirmation] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: strategyQueryKeys.list({}),
    queryFn: () => listStrategies({}),
    refetchInterval: 30_000,
  })

  const rows = data ?? []
  const liveAuthorizationQuery = useQuery({
    queryKey: strategyQueryKeys.liveAuthorization(),
    queryFn: getLiveAuthorization,
    enabled: startTarget !== null && startMode === 'live',
    staleTime: 0,
  })
  const authorizationExpiry = liveAuthorizationQuery.data
    ? Date.parse(liveAuthorizationQuery.data.expires_at)
    : Number.NaN
  const liveAuthorizationActive = Boolean(
    liveAuthorizationQuery.data?.active &&
      Number.isFinite(authorizationExpiry) &&
      authorizationExpiry > Date.now()
  )

  const refreshAutomation = () => {
    void queryClient.invalidateQueries({ queryKey: strategyQueryKeys.strategies() })
    void queryClient.invalidateQueries({ queryKey: strategyQueryKeys.criticalAlerts() })
  }

  const controlMutation = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'enable' | 'disable' }) =>
      action === 'enable' ? enableStrategyAutomation(id) : disableStrategyAutomation(id),
    onSuccess: (result) => {
      setControlError(null)
      setControlResult(result)
      setDisableTarget(null)
      refreshAutomation()
    },
    onError: (error: Error) => {
      const item = (error as Error & { response?: { data?: { data?: AutomationControlResult } } })
        .response?.data?.data
      if (item) {
        setControlResult(item)
        refreshAutomation()
      } else {
        void queryClient.invalidateQueries({ queryKey: strategyQueryKeys.strategies() })
        void queryClient.invalidateQueries({ queryKey: strategyQueryKeys.criticalAlerts() })
      }
      setControlError(item?.reason || error.message || 'Automation control failed')
      setDisableTarget(null)
    },
  })

  const startMutation = useMutation({
    mutationFn: ({ id, mode }: { id: number; mode: RunMode }) => startRun(id, mode),
    onSuccess: (result) => {
      const rejected = result.legs.filter((leg) => leg.ok === false || leg.status === 'rejected')
      if (result.acknowledged === false) {
        showToast.warning(
          'Run started, but broker acknowledgement is pending. Check Orders and Events.'
        )
      } else if (rejected.length > 0) {
        showToast.warning(`Run started, but ${rejected.length} leg(s) were rejected. Check Orders.`)
      } else {
        showToast.success(`Run started — ${result.legs.length} legs placed`)
      }
      setStartTarget(null)
      setStartConfirmation('')
      refreshAutomation()
    },
    onError: (error: Error) => showToast.error(error.message || 'Could not start strategy'),
  })

  const liveModeMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => setLiveEnabled(id, enabled),
    onSuccess: (enabled) => {
      setLiveEnableTarget(null)
      showToast.success(enabled ? 'Live mode enabled' : 'Live mode disabled')
      void queryClient.invalidateQueries({ queryKey: strategyQueryKeys.strategies() })
    },
    onError: (error: Error) => {
      showToast.error(error.message || 'Could not change live mode')
      void queryClient.invalidateQueries({ queryKey: strategyQueryKeys.strategies() })
    },
  })

  const bulkMutation = useMutation({
    mutationFn: startAllSandboxStrategies,
    onSuccess: (result) => {
      setBulkResult(result)
      setControlError(null)
      refreshAutomation()
    },
    onError: (error: Error) => {
      setControlError(error.message || 'Sandbox automation could not be started')
      void queryClient.invalidateQueries({ queryKey: strategyQueryKeys.strategies() })
      void queryClient.invalidateQueries({ queryKey: strategyQueryKeys.criticalAlerts() })
    },
  })
  const liveBulkMutation = useMutation({
    mutationFn: () => startAllLiveStrategies(liveConfirmation),
    onSuccess: (result) => {
      setBulkResult(result)
      setControlError(null)
      setLiveStartOpen(false)
      setLiveConfirmation('')
      refreshAutomation()
    },
    onError: (error: Error) => {
      const status = (error as Error & { response?: { status?: number } }).response?.status
      setControlError(
        status === 403
          ? 'Live automation authorization is inactive. Authorize live automation above, then try again.'
          : error.message || 'Live strategies could not be started'
      )
      refreshAutomation()
    },
  })
  const feedbackRow = controlResult && rows.find((row) => row.id === controlResult.strategy_id)
  const feedbackState = feedbackRow?.automation_state
  const feedbackAction = controlMutation.variables?.action
  const pendingCloseAheadOfList = Boolean(
    controlResult?.close_pending &&
      controlResult.state === 'closing' &&
      feedbackAction === 'disable' &&
      (!feedbackRow || feedbackState === 'armed')
  )
  const feedbackWaiting =
    Boolean(controlResult) &&
    (!feedbackRow ||
      (feedbackAction === 'disable' &&
        feedbackState === 'armed' &&
        controlResult?.outcome !== 'failed') ||
      (feedbackAction === 'enable' &&
        feedbackState === 'disabled' &&
        controlResult?.outcome !== 'failed'))
  const feedbackText =
    controlResult &&
    (pendingCloseAheadOfList
      ? `${controlResult.name}: Closing… — Closing until confirmed flat. Waiting for the strategy list to refresh.`
      : feedbackWaiting
        ? `${controlResult.name}: Checking latest strategy state…`
        : feedbackState === 'closing'
          ? `${feedbackRow?.name}: Closing… — Closing until confirmed flat.`
          : feedbackState === 'close_failed'
            ? `${feedbackRow?.name}: Close failed — Closing until confirmed flat.`
            : feedbackState === 'disabled' && feedbackAction === 'disable'
              ? `${feedbackRow?.name}: Disabled — confirmed flat.`
              : feedbackState === 'armed' && feedbackAction === 'disable'
                ? `${feedbackRow?.name}: Armed — disable not confirmed.`
                : `${feedbackRow?.name}: ${automationLabel(feedbackState ?? 'disabled')}`)
  const latestControlError = !feedbackRow
    ? controlError
    : feedbackState === 'close_failed'
      ? feedbackRow.automation_state_reason ||
        controlError ||
        'Close process failed; position status requires reconciliation.'
      : controlResult?.outcome === 'failed' &&
          ((feedbackAction === 'disable' && feedbackState === 'armed') ||
            (feedbackAction === 'enable' && feedbackState === 'disabled'))
        ? controlError
        : null
  const pnlById = useStrategyListPnl(rows)
  const resetPreview = useQuery({
    queryKey: strategyQueryKeys.sandboxResetPreview(),
    queryFn: previewSandboxReset,
    enabled: resetOpen,
    staleTime: 0,
    refetchOnMount: 'always',
  })

  const resetMutation = useMutation({
    mutationFn: executeSandboxReset,
    onSuccess: (result) => {
      showToast.success(
        result.already_done
          ? 'No sandbox runs remain in this session'
          : `${result.run_count} sandbox runs cleared; simulated funds reconciled`
      )
      setResetOpen(false)
      queryClient.invalidateQueries()
    },
    onError: (err: Error) => {
      showToast.error(err.message || 'Sandbox reset was refused')
      queryClient.invalidateQueries({ queryKey: strategyQueryKeys.sandboxResetPreview() })
    },
  })

  const rupees = (value: number | null | undefined) =>
    value == null
      ? 'Unavailable'
      : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(value)

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteStrategy(id),
    onSuccess: () => {
      showToast.success('Strategy deleted')
      queryClient.invalidateQueries({ queryKey: strategyQueryKeys.strategies() })
      setDeleteTargetId(null)
    },
    onError: (err: Error) => {
      showToast.error(err.message || 'Delete failed')
    },
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Strategies</h1>
          <p className="text-sm text-muted-foreground">
            Manage cash, index, and commodity strategies. Sandbox is the default; live mode requires
            explicit per-strategy opt-in.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild><Link to="/strategy/research">Research</Link></Button>
          <Button
            variant="secondary"
            disabled={
              bulkMutation.isPending ||
              liveBulkMutation.isPending ||
              controlMutation.isPending ||
              isLoading
            }
            onClick={() => {
              setBulkResult(null)
              setControlResult(null)
              setControlError(null)
              bulkMutation.mutate()
            }}
          >
            <Play aria-hidden="true" className="size-4" />
            {bulkMutation.isPending ? 'Starting sandbox strategies…' : 'Start all (sandbox)'}
          </Button>
          <Button
            variant="destructive"
            disabled={
              bulkMutation.isPending ||
              liveBulkMutation.isPending ||
              controlMutation.isPending ||
              isLoading
            }
            onClick={() => {
              setBulkResult(null)
              setControlResult(null)
              setControlError(null)
              setLiveConfirmation('')
              setLiveStartOpen(true)
            }}
          >
            <Play aria-hidden="true" className="size-4" />
            Start all (live)
          </Button>
          <Button variant="outline" onClick={() => setResetOpen(true)}>
            <RotateCcw aria-hidden="true" className="size-4" />
            Reset today's sandbox tests
          </Button>
          <Button onClick={() => navigate('/strategy/new')}>
            <Plus aria-hidden="true" className="size-4" />
            New strategy
          </Button>
        </div>
      </div>

      <AutomationSafetyCard />
      <CriticalAlertsCard savedStrategyIds={new Set((data ?? []).map((strategy) => strategy.id))} />

      {(bulkMutation.isPending ||
        liveBulkMutation.isPending ||
        controlMutation.isPending ||
        bulkResult ||
        controlResult) && (
        <output
          className="block rounded-lg border bg-muted/30 p-4 text-sm"
          aria-live="polite"
          aria-label="Strategy start results"
        >
          <p className="font-medium">Strategy start results</p>
          {bulkMutation.isPending && (
            <p className="mt-1 text-muted-foreground">
              Starting eligible batch runs and arming signal-driven workflows in sandbox only.
            </p>
          )}
          {liveBulkMutation.isPending && (
            <p className="mt-1 text-destructive">
              Submitting eligible strategies to the live broker through existing risk controls.
            </p>
          )}
          {controlMutation.isPending && (
            <p className="mt-1 text-muted-foreground">Processing automation control…</p>
          )}
          {bulkResult &&
            (bulkResult.items.length === 0 ? (
              <p className="mt-1 text-muted-foreground">No saved strategies to process.</p>
            ) : (
              <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto pr-2">
                {bulkResult.items.map((item) => (
                  <li key={item.strategy_id} className="flex flex-wrap gap-x-2">
                    <span className="font-medium">{item.name}</span>
                    <span>
                      {item.outcome === 'started'
                        ? 'Started'
                        : item.outcome === 'armed'
                          ? 'Armed'
                          : item.outcome === 'skipped'
                            ? 'Skipped'
                            : 'Failed'}
                    </span>
                    {item.reason && <span className="text-muted-foreground">— {item.reason}</span>}
                  </li>
                ))}
              </ul>
            ))}
          {feedbackText && <p className="mt-1">{feedbackText}</p>}
        </output>
      )}

      <Dialog
        open={liveStartOpen}
        onOpenChange={(open) => {
          if (!liveBulkMutation.isPending) {
            setLiveStartOpen(open)
            if (!open) setLiveConfirmation('')
          }
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Start all eligible strategies live?</DialogTitle>
            <DialogDescription>
              This can place real broker orders using real funds. Only individually live-enabled
              strategies may start, and every existing authorization, broker, stop-loss, funds, and
              portfolio-risk gate still applies.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <label htmlFor="confirm-live-bulk" className="text-sm font-medium">
              Type START LIVE to confirm
            </label>
            <Input
              id="confirm-live-bulk"
              value={liveConfirmation}
              onChange={(event) => setLiveConfirmation(event.target.value)}
              autoComplete="off"
            />
          </div>
          {controlError && (
            <div
              className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
              role="alert"
            >
              {controlError}
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={liveBulkMutation.isPending}
              onClick={() => setLiveStartOpen(false)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={liveConfirmation !== 'START LIVE' || liveBulkMutation.isPending}
              onClick={() => {
                setControlError(null)
                liveBulkMutation.mutate()
              }}
            >
              {liveBulkMutation.isPending ? 'Starting live…' : 'Confirm live start'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={liveEnableTarget !== null}
        onOpenChange={(open) => {
          if (!open && !liveModeMutation.isPending) setLiveEnableTarget(null)
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Enable LIVE for {liveEnableTarget?.name}?</DialogTitle>
            <DialogDescription>
              Live starts can place real broker orders using real funds. This enables live mode for
              this strategy; it does not start a run. Existing authorization and risk checks still
              apply to each live entry.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={liveModeMutation.isPending}
              onClick={() => setLiveEnableTarget(null)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={liveModeMutation.isPending || !liveEnableTarget}
              onClick={() => {
                if (liveEnableTarget)
                  liveModeMutation.mutate({ id: liveEnableTarget.id, enabled: true })
              }}
            >
              {liveModeMutation.isPending ? 'Enabling…' : 'Enable LIVE'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={startTarget !== null}
        onOpenChange={(open) => {
          if (!open && !startMutation.isPending) {
            setStartTarget(null)
            setStartConfirmation('')
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Start {startTarget?.name}?</DialogTitle>
            <DialogDescription>
              Sandbox mode is paper-only. Live mode can place real broker orders using real funds.
            </DialogDescription>
          </DialogHeader>
          <div className="flex overflow-hidden rounded-md border">
            {(['sandbox', 'live'] as RunMode[]).map((mode) => (
              <Button
                key={mode}
                type="button"
                className="flex-1 rounded-none"
                variant={startMode === mode ? 'default' : 'ghost'}
                disabled={mode === 'live' && !startTarget?.live_enabled}
                onClick={() => {
                  setStartMode(mode)
                  setStartConfirmation('')
                }}
              >
                {mode.toUpperCase()}
              </Button>
            ))}
          </div>
          {startMode === 'live' && (
            <div className="space-y-2">
              {liveAuthorizationQuery.isFetching ? (
                <p className="text-sm text-muted-foreground">
                  Checking live session authorization…
                </p>
              ) : !liveAuthorizationActive ? (
                <p className="text-sm text-destructive" role="alert">
                  Live automation is not authorized for this trading session. Use the authorization
                  controls above first.
                </p>
              ) : null}
              <label htmlFor="confirm-single-live" className="text-sm font-medium">
                Type START LIVE to confirm real trading
              </label>
              <Input
                id="confirm-single-live"
                autoComplete="off"
                value={startConfirmation}
                onChange={(event) => setStartConfirmation(event.target.value)}
              />
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={startMutation.isPending}
              onClick={() => setStartTarget(null)}
            >
              Cancel
            </Button>
            <Button
              variant={startMode === 'live' ? 'destructive' : 'default'}
              disabled={
                startMutation.isPending ||
                !startTarget ||
                (startMode === 'live' &&
                  (!startTarget.live_enabled ||
                    !liveAuthorizationActive ||
                    liveAuthorizationQuery.isFetching ||
                    startConfirmation !== 'START LIVE'))
              }
              onClick={() => {
                if (
                  startTarget &&
                  startTarget.strategy_kind === 'batch' &&
                  startTarget.status === 'stopped'
                ) {
                  startMutation.mutate({ id: startTarget.id, mode: startMode })
                }
              }}
            >
              {startMutation.isPending ? 'Starting…' : `Start ${startMode}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {(latestControlError || bulkResult?.items.some((item) => item.outcome === 'failed')) && (
        <div
          className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
          role="alert"
        >
          {latestControlError ||
            bulkResult?.items
              .filter((item) => item.outcome === 'failed')
              .map((item) => `${item.name}: ${item.reason || 'Automation failed'}`)
              .join('; ')}
        </div>
      )}

      <Dialog
        open={disableTarget !== null}
        onOpenChange={(open) => {
          if (!open && !controlMutation.isPending) setDisableTarget(null)
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Disable automation for {disableTarget?.name}?</DialogTitle>
            <DialogDescription>
              New entries stop immediately. Any open position will be sent through the existing
              close process and remains Closing until confirmed flat.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={controlMutation.isPending}
              onClick={() => setDisableTarget(null)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={controlMutation.isPending}
              onClick={() => {
                if (disableTarget) {
                  setBulkResult(null)
                  setControlError(null)
                  setControlResult(null)
                  controlMutation.mutate({ id: disableTarget.id, action: 'disable' })
                }
              }}
            >
              {controlMutation.isPending ? 'Disabling…' : 'Confirm disable'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={resetOpen}
        onOpenChange={(open) => {
          if (!resetMutation.isPending) setResetOpen(open)
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Reset today's sandbox tests?</DialogTitle>
            <DialogDescription>
              Clears only this trading session's simulated strategy runs after verifying every fill.
              Saved strategies, workflows, older history, and live trading are unchanged.
            </DialogDescription>
          </DialogHeader>
          {resetPreview.isPending ? (
            <output className="block text-sm text-muted-foreground">
              Checking sandbox ledgers…
            </output>
          ) : resetPreview.isError ? (
            <p
              className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
              role="alert"
            >
              Could not check the sandbox state. Nothing can be reset until the preview loads.
            </p>
          ) : resetPreview.data ? (
            <div className="space-y-4 text-sm">
              <div className="rounded-lg border bg-muted/30 p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Current test session
                </p>
                <p className="mt-1 font-medium">
                  {formatIst(resetPreview.data.session_start_utc)} to{' '}
                  {formatIst(resetPreview.data.session_end_utc)}
                </p>
                <div className="mt-3 grid grid-cols-3 gap-3 border-t pt-3 text-center">
                  <div>
                    <strong className="block font-mono text-lg">
                      {resetPreview.data.run_count}
                    </strong>
                    <span className="text-muted-foreground">runs</span>
                  </div>
                  <div>
                    <strong className="block font-mono text-lg">
                      {resetPreview.data.order_count}
                    </strong>
                    <span className="text-muted-foreground">orders</span>
                  </div>
                  <div>
                    <strong className="block font-mono text-lg">
                      {resetPreview.data.trade_count}
                    </strong>
                    <span className="text-muted-foreground">trades</span>
                  </div>
                </div>
              </div>
              <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-2 rounded-lg border p-4">
                <dt className="text-muted-foreground">Verified realised P&amp;L</dt>
                <dd className="text-right font-mono">{rupees(resetPreview.data.realised_pnl)}</dd>
                <dt className="text-muted-foreground">Simulated funds now</dt>
                <dd className="text-right font-mono">{rupees(resetPreview.data.funds_before)}</dd>
                <dt className="border-t pt-2 font-medium">Funds after reset</dt>
                <dd className="border-t pt-2 text-right font-mono font-semibold">
                  {rupees(resetPreview.data.funds_after)}
                </dd>
              </dl>
              {resetPreview.data.blockers.length > 0 && (
                <div
                  className="rounded-lg border border-destructive/40 bg-destructive/10 p-4"
                  role="alert"
                >
                  <p className="font-medium text-destructive">Reset is blocked</p>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-destructive">
                    {resetPreview.data.blockers.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="text-xs text-muted-foreground">
                A verified backup and reset audit are retained. This does not place, modify, or
                cancel any order.
              </p>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setResetOpen(false)}
              disabled={resetMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={
                resetMutation.isPending ||
                resetPreview.isFetching ||
                !resetPreview.data ||
                resetPreview.data.run_count === 0 ||
                resetPreview.data.blockers.length > 0
              }
              onClick={() => {
                if (resetPreview.data) resetMutation.mutate(resetPreview.data.version)
              }}
            >
              {resetMutation.isPending ? 'Resetting…' : 'Confirm reset'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Card>
        <CardHeader>
          <CardTitle>Saved strategies</CardTitle>
          <CardDescription>
            P&amp;L columns are live for running strategies and reflect the last-run snapshot for
            stopped strategies. Status shows whether a run is currently active. Automation shows
            whether the linked sandbox workflow is enabled. Start all starts every eligible batch
            strategy in sandbox and arms signal-driven workflows. Risk controls may reject
            individual starts.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error ? (
            <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              Failed to load strategies. Check the backend logs.
            </p>
          ) : isLoading ? (
            <p className="py-8 text-center text-sm text-muted-foreground">Loading…</p>
          ) : rows.length === 0 ? (
            <div className="space-y-3 py-8 text-center">
              <p className="text-sm text-muted-foreground">No strategies yet.</p>
              <Button variant="secondary" onClick={() => navigate('/strategy/new')}>
                Create your first strategy
              </Button>
            </div>
          ) : (
            <Table className="w-max min-w-full">
              <TableHeader>
                <TableRow>
                  <TableHead className="sticky left-0 z-10 w-64 min-w-64 bg-card">Name</TableHead>
                  <TableHead className="w-32 min-w-32 text-right lg:sticky lg:left-64 lg:z-10 lg:bg-card">
                    Realized
                  </TableHead>
                  <TableHead className="w-32 min-w-32 text-right lg:sticky lg:left-[24rem] lg:z-10 lg:bg-card">
                    Unrealized
                  </TableHead>
                  <TableHead className="w-32 min-w-32 border-r text-right lg:sticky lg:left-[32rem] lg:z-10 lg:bg-card">
                    Total P&amp;L
                  </TableHead>
                  <TableHead className="min-w-20">Status</TableHead>
                  <TableHead>Automation</TableHead>
                  <TableHead>Mode</TableHead>
                  <TableHead>Underlying</TableHead>
                  <TableHead>Tab</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row, index) => {
                  const pnl = pnlById.get(row.id)
                  const state = row.automation_state ?? 'disabled'
                  const pending =
                    controlMutation.isPending && controlMutation.variables?.id === row.id
                  const displayState =
                    pendingCloseAheadOfList && controlResult?.strategy_id === row.id
                      ? 'closing'
                      : state
                  const shouldDisable =
                    state === 'armed' || state === 'close_failed' || row.status === 'running'
                  const ineligibleReason = row.live_enabled
                    ? 'Live-enabled strategies cannot use sandbox automation controls'
                    : undefined
                  return (
                    <TableRow key={row.id} className={index % 2 === 0 ? 'bg-muted/30' : ''}>
                      <TableCell
                        className={cn(
                          'sticky left-0 z-10 w-64 min-w-64 max-w-64 whitespace-normal break-words',
                          index % 2 === 0 ? 'bg-muted' : 'bg-card'
                        )}
                      >
                        <Link
                          to={`/strategy/${row.id}`}
                          className="block font-medium underline-offset-4 hover:underline focus-visible:underline"
                        >
                          {row.name}
                        </Link>
                        {row.strategy_kind === 'batch' && row.status === 'stopped' && (
                          <Button
                            size="sm"
                            variant="secondary"
                            className="mt-2"
                            aria-label={`Start run for ${row.name}`}
                            disabled={
                              startMutation.isPending ||
                              bulkMutation.isPending ||
                              liveBulkMutation.isPending
                            }
                            onClick={() => {
                              setStartTarget(row)
                              setStartMode('sandbox')
                              setStartConfirmation('')
                            }}
                          >
                            <Play aria-hidden="true" className="size-4" />
                            Start run
                          </Button>
                        )}
                        {row.strategy_kind === 'signal' &&
                          state === 'disabled' &&
                          !row.live_enabled &&
                          row.status === 'stopped' && (
                            <Button
                              size="sm"
                              variant="secondary"
                              className="mt-2"
                              aria-label={`Arm signals for ${row.name}`}
                              disabled={
                                pending || bulkMutation.isPending || controlMutation.isPending
                              }
                              onClick={() => {
                                setBulkResult(null)
                                setControlError(null)
                                setControlResult(null)
                                controlMutation.mutate({ id: row.id, action: 'enable' })
                              }}
                            >
                              <Power aria-hidden="true" className="size-4" />
                              Arm signals
                            </Button>
                          )}
                      </TableCell>
                      <TableCell
                        className={cn(
                          'w-32 min-w-32 text-right font-mono lg:sticky lg:left-64 lg:z-10',
                          index % 2 === 0 ? 'lg:bg-muted' : 'lg:bg-card',
                          pnlToneClass(pnl?.realized)
                        )}
                      >
                        {pnl?.finalized ? formatPnl(pnl.realized) : formatListPnl(pnl?.realized)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          'w-32 min-w-32 text-right font-mono lg:sticky lg:left-[24rem] lg:z-10',
                          index % 2 === 0 ? 'lg:bg-muted' : 'lg:bg-card',
                          pnlToneClass(pnl?.unrealized)
                        )}
                      >
                        {pnl?.finalized
                          ? formatPnl(pnl.unrealized)
                          : formatListPnl(pnl?.unrealized)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          'w-32 min-w-32 border-r text-right font-mono font-medium lg:sticky lg:left-[32rem] lg:z-10',
                          index % 2 === 0 ? 'lg:bg-muted' : 'lg:bg-card',
                          pnlToneClass(pnl?.total)
                        )}
                      >
                        {pnl?.finalized ? formatPnl(pnl.total) : formatListPnl(pnl?.total)}
                      </TableCell>
                      <TableCell className="min-w-20">
                        <Badge variant={statusBadgeVariant(row.status)}>{row.status}</Badge>
                      </TableCell>
                      <TableCell className="min-w-36">
                        <Badge variant={automationVariant(displayState)}>
                          {pending && controlMutation.variables?.action === 'disable'
                            ? 'Closing…'
                            : automationLabel(displayState)}
                        </Badge>
                        {ineligibleReason && (
                          <p
                            id={`automation-ineligible-${row.id}`}
                            className="mt-1 max-w-44 whitespace-normal text-xs text-muted-foreground"
                          >
                            LIVE mode: sandbox automation unavailable
                          </p>
                        )}
                        {(row.automation_state_reason || state === 'close_failed') && (
                          <p className="mt-1 max-w-52 whitespace-normal text-xs text-muted-foreground">
                            {row.automation_state_reason && <>{row.automation_state_reason} </>}
                            {state === 'close_failed' && 'Closing until confirmed flat.'}
                          </p>
                        )}
                      </TableCell>
                      <TableCell className="min-w-56">
                        <div className="flex items-center gap-2 whitespace-nowrap">
                          <Badge variant={row.live_enabled ? 'destructive' : 'secondary'}>
                            {row.live_enabled ? 'LIVE-enabled' : 'SANDBOX-only'}
                          </Badge>
                          <Button
                            size="sm"
                            variant={row.live_enabled ? 'outline' : 'destructive'}
                            aria-label={`${row.live_enabled ? 'Disable' : 'Enable'} LIVE for ${row.name}`}
                            disabled={row.status !== 'stopped' || liveModeMutation.isPending}
                            title={
                              row.status !== 'stopped'
                                ? 'Stop and close the run before changing live mode'
                                : undefined
                            }
                            onClick={() => {
                              if (row.live_enabled)
                                liveModeMutation.mutate({ id: row.id, enabled: false })
                              else setLiveEnableTarget(row)
                            }}
                          >
                            {row.live_enabled ? (
                              <ShieldOff aria-hidden="true" className="size-4" />
                            ) : (
                              <ShieldCheck aria-hidden="true" className="size-4" />
                            )}
                            {liveModeMutation.isPending && liveModeMutation.variables?.id === row.id
                              ? row.live_enabled
                                ? 'Disabling…'
                                : 'Enabling…'
                              : row.live_enabled
                                ? 'Disable LIVE'
                                : 'Enable LIVE'}
                          </Button>
                        </div>
                      </TableCell>
                      <TableCell className="font-medium">{row.underlying}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {universeTabLabel(row.universe_tab)}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{row.strategy_type}</Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {formatIst(row.updated_at, false)}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2 whitespace-nowrap">
                          {state !== 'closing' &&
                            !(
                              row.strategy_kind === 'signal' &&
                              state === 'disabled' &&
                              !row.live_enabled &&
                              row.status === 'stopped'
                            ) && (
                              <Button
                                size="sm"
                                variant={shouldDisable ? 'outline' : 'secondary'}
                                aria-label={`${state === 'close_failed' ? 'Retry close' : shouldDisable ? 'Disable' : 'Enable'} automation for ${row.name}`}
                                aria-describedby={
                                  ineligibleReason ? `automation-ineligible-${row.id}` : undefined
                                }
                                disabled={
                                  Boolean(ineligibleReason) ||
                                  pending ||
                                  bulkMutation.isPending ||
                                  controlMutation.isPending ||
                                  (controlResult?.strategy_id === row.id && feedbackWaiting)
                                }
                                onClick={() => {
                                  setBulkResult(null)
                                  setControlError(null)
                                  setControlResult(null)
                                  if (shouldDisable) setDisableTarget(row)
                                  else controlMutation.mutate({ id: row.id, action: 'enable' })
                                }}
                              >
                                {shouldDisable ? (
                                  <PowerOff aria-hidden="true" className="size-4" />
                                ) : (
                                  <Power aria-hidden="true" className="size-4" />
                                )}
                                {pending
                                  ? controlMutation.variables?.action === 'disable'
                                    ? 'Disabling…'
                                    : 'Enabling…'
                                  : state === 'close_failed'
                                    ? 'Retry close'
                                    : shouldDisable
                                      ? 'Disable auto'
                                      : 'Enable auto'}
                              </Button>
                            )}
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => navigate(`/strategy/${row.id}`)}
                          >
                            <ArrowUpRight aria-hidden="true" className="size-4" />
                            Open
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            disabled={row.status === 'running'}
                            title={
                              row.status === 'running'
                                ? `Cannot delete while ${row.status}`
                                : undefined
                            }
                            onClick={() => setDeleteTargetId(row.id)}
                          >
                            <Trash2 aria-hidden="true" className="size-4" />
                            Delete
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={deleteTargetId !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTargetId(null)
        }}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-base">Delete this strategy?</DialogTitle>
            <DialogDescription>
              This permanently removes the strategy and its audit trail. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteTargetId(null)}
              disabled={deleteMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              className="min-w-[120px]"
              disabled={deleteMutation.isPending}
              onClick={() => {
                if (deleteTargetId !== null) deleteMutation.mutate(deleteTargetId)
              }}
            >
              {deleteMutation.isPending ? 'Working…' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
