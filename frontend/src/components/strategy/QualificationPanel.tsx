import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import {
  createQualificationCampaign,
  getQualification,
  getQualificationCampaign,
  type QualificationAction,
  qualificationKeys,
  reviewQualificationCampaign,
} from '@/api/strategy-qualification'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import type { QualificationCampaign, QualificationPolicy } from '@/types/strategy-qualification'
import type { CostSchedule, ResearchRun } from '@/types/trading-research'

const selectClass =
  'border-input bg-background h-9 w-full rounded-md border px-3 text-sm focus-visible:outline-2 focus-visible:outline-ring'
const numeric = (value: number | null | undefined, suffix = '') =>
  value == null || !Number.isFinite(value)
    ? 'Unavailable'
    : `${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}${suffix}`
const money = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value)
    ? 'Unavailable'
    : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(value)
const date = (value: string | null | undefined) => {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Unavailable'
  return new Date(value).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}
const costLabels: Record<keyof CostSchedule, string> = {
  schedule_id: 'Schedule',
  source: 'Source',
  effective_from: 'Effective from',
  effective_to: 'Effective until',
  brokerage_per_order: 'Brokerage per order (INR)',
  exchange_rate: 'Exchange fee rate',
  sebi_rate: 'SEBI fee rate',
  gst_rate: 'GST rate',
  stamp_buy_rate: 'Stamp duty buy rate',
  stt_sell_rate: 'STT sell rate',
  slippage_bps: 'Slippage (basis points)',
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 space-y-1">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-mono text-lg tabular-nums break-words">{value}</dd>
    </div>
  )
}

function Progress({ label, value, target }: { label: string; value?: number; target: number }) {
  return (
    <div className="space-y-2 rounded-lg border p-4">
      <div className="flex justify-between gap-3 text-sm">
        <span>{label}</span>
        <span className="font-mono tabular-nums">
          {numeric(value)} / {numeric(target)}
        </span>
      </div>
      <progress
        aria-label={label}
        className="h-2 w-full accent-primary"
        value={value ?? 0}
        max={target}
      />
    </div>
  )
}

function CampaignReview({
  campaign,
  policy,
  unavailable,
  onReviewed,
}: {
  campaign: QualificationCampaign
  policy: QualificationPolicy
  unavailable: boolean
  onReviewed: (campaign: QualificationCampaign, message: string) => void
}) {
  const queryClient = useQueryClient()
  const [reconcileReason, setReconcileReason] = useState('')
  const [costsConfirmed, setCostsConfirmed] = useState(false)
  const [releaseReason, setReleaseReason] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const [revokeReason, setRevokeReason] = useState('')
  const [now, setNow] = useState(Date.now)
  // Expiry remains visible even when a tab stops fetching fresh server evidence.
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15_000)
    return () => window.clearInterval(timer)
  }, [])
  const approval = campaign.approval
  const expiry = approval ? Date.parse(approval.expires_at) : Number.NaN
  const approvalStatus =
    approval?.status === 'approved'
      ? !Number.isFinite(expiry)
        ? 'unavailable'
        : expiry <= now
          ? 'expired'
          : !campaign.qualification.eligible || campaign.reconciliation?.status !== 'current'
            ? 'invalidated'
            : 'approved'
      : approval?.status
  const released = approvalStatus === 'approved' && !unavailable
  const reconciled =
    campaign.reconciliation?.status === 'current' && campaign.reconciliation.costs_confirmed
  const reviewed = useMutation({
    mutationFn: (review: QualificationAction) => reviewQualificationCampaign(campaign.id, review),
    onSuccess: (data, review) => {
      setReconcileReason('')
      setCostsConfirmed(false)
      setReleaseReason('')
      setAcknowledged(false)
      setRevokeReason('')
      onReviewed(
        data,
        review.action === 'reconcile'
          ? 'The current evidence and cost review were recorded.'
          : review.action === 'approve'
            ? 'The live release review was recorded. Check the current release status below; daily authorization and Flow enablement remain separate.'
            : 'Live release revoked. New live entries are blocked by this release gate.'
      )
    },
    onError: async () => {
      setCostsConfirmed(false)
      setAcknowledged(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qualificationKeys.campaign(campaign.id) }),
        queryClient.invalidateQueries({ queryKey: qualificationKeys.overview }),
      ])
    },
  })
  const busy = reviewed.isPending || unavailable
  return (
    <section aria-label="Campaign review" className="space-y-5 border-t pt-5">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="font-semibold">Review and release</h4>
        <Badge variant={released ? 'secondary' : 'outline'}>
          {unavailable
            ? 'Release status unavailable'
            : approvalStatus
              ? `Release ${approvalStatus}`
              : 'No live release approval'}
        </Badge>
        <Badge variant="outline">
          {campaign.reconciliation
            ? `Reconciliation ${campaign.reconciliation.status}`
            : 'Reconciliation required'}
        </Badge>
      </div>
      {campaign.reconciliation && (
        <p className="text-sm text-muted-foreground">
          Reconciled {date(campaign.reconciliation.at)} · {campaign.reconciliation.reason}
        </p>
      )}
      {approval && (
        <p className="text-sm text-muted-foreground">
          Approval expires {date(approval.expires_at)} · {approval.reason}
        </p>
      )}
      {approval?.invalidation_reason && (
        <p className="text-sm text-destructive">{approval.invalidation_reason}</p>
      )}
      <p className="text-sm text-muted-foreground">
        Approval lasts {policy.approval_days} days and binds the reviewed evidence, strategy, Flow,
        source, account, risk policy and costs. New Sandbox evidence, corrections, changed
        configuration, broker authorization or a risk pause can invalidate it. Approval does not
        enable live trading, activate a Flow or submit an order.
      </p>
      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-3 rounded-lg border p-4">
          <h5 className="font-medium">1. Reconcile execution and fees</h5>
          <p className="text-xs text-muted-foreground">
            Review the trade evidence and dated cost assumptions above. Sandbox costs are modeled;
            they are not fees charged by the broker.
          </p>
          <Label htmlFor="qualification-reconcile-reason">Reconciliation reason</Label>
          <Textarea
            id="qualification-reconcile-reason"
            value={reconcileReason}
            onChange={(event) => setReconcileReason(event.target.value)}
            disabled={busy}
          />
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={costsConfirmed}
              disabled={busy}
              onChange={(event) => setCostsConfirmed(event.target.checked)}
            />
            I reviewed the forward fills, unresolved outcomes, and dated fee and slippage
            assumptions.
          </label>
          <Button
            variant="outline"
            disabled={
              busy || !reconcileReason.trim() || !costsConfirmed || !campaign.binding?.costs
            }
            onClick={() =>
              reviewed.mutate({
                action: 'reconcile',
                payload: {
                  reason: reconcileReason.trim(),
                  costs_confirmed: true,
                  expected_revision: campaign.revision,
                  evidence_digest: campaign.evidence_digest,
                },
              })
            }
          >
            Record reconciliation
          </Button>
        </div>
        <div className="space-y-3 rounded-lg border p-4">
          <h5 className="font-medium">2. Approve the reviewed release</h5>
          {!campaign.qualification.eligible && (
            <p className="text-xs text-muted-foreground">
              All qualification checks must pass before approval is available.
            </p>
          )}
          {!reconciled && (
            <p className="text-xs text-muted-foreground">
              Record a current reconciliation before approving this evidence.
            </p>
          )}
          <Label htmlFor="qualification-release-reason">Release review reason</Label>
          <Textarea
            id="qualification-release-reason"
            value={releaseReason}
            onChange={(event) => setReleaseReason(event.target.value)}
            disabled={busy || released}
          />
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={acknowledged}
              disabled={busy || released}
              onChange={(event) => setAcknowledged(event.target.checked)}
            />
            Daily live-session authorization, Flow enablement and protective-stop checks remain
            required. I approve only this reviewed configuration and evidence.
          </label>
          <Button
            disabled={
              busy ||
              released ||
              !campaign.qualification.eligible ||
              !reconciled ||
              !releaseReason.trim() ||
              !acknowledged
            }
            onClick={() =>
              reviewed.mutate({
                action: 'approve',
                payload: {
                  reason: releaseReason.trim(),
                  acknowledged: true,
                  expected_revision: campaign.revision,
                  evidence_digest: campaign.evidence_digest,
                },
              })
            }
          >
            Approve live release
          </Button>
        </div>
      </div>
      {approval && approval.status !== 'revoked' && (
        <div className="space-y-3 rounded-lg border p-4">
          <Label htmlFor="qualification-revoke-reason">Revocation reason</Label>
          <Textarea
            id="qualification-revoke-reason"
            value={revokeReason}
            onChange={(event) => setRevokeReason(event.target.value)}
            disabled={reviewed.isPending}
          />
          <Button
            variant="destructive"
            disabled={reviewed.isPending || !revokeReason.trim()}
            onClick={() =>
              reviewed.mutate({ action: 'revoke', payload: { reason: revokeReason.trim() } })
            }
          >
            Revoke live release
          </Button>
        </div>
      )}
      {reviewed.isPending && <output className="block text-sm">Recording review…</output>}
      {reviewed.error && (
        <p role="alert" className="text-sm text-destructive">
          {reviewed.error.message}
        </p>
      )}
    </section>
  )
}

function CampaignEvidence({
  campaign,
  strategyName,
  policy,
  unavailable,
  onReviewed,
}: {
  campaign: QualificationCampaign
  strategyName: string
  policy: QualificationPolicy
  unavailable: boolean
  onReviewed: (campaign: QualificationCampaign, message: string) => void
}) {
  const metrics = campaign.qualification.metrics
  const binding = campaign.binding
  return (
    <section aria-label="Campaign evidence" className="space-y-5 rounded-lg border p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h3 className="font-semibold">
            Campaign #{campaign.id} · {strategyName}
          </h3>
          <p className="text-xs text-muted-foreground">
            Enrolled {date(campaign.created_at)} · Strategy #{campaign.strategy_id}
          </p>
          <p className="text-xs text-muted-foreground">
            Historical research reference: run #{campaign.final_run_id}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{campaign.status.replaceAll('_', ' ')}</Badge>
          <Badge variant="outline">
            {unavailable
              ? 'Evidence unavailable'
              : campaign.qualification.eligible
                ? 'Eligible for review'
                : 'Not yet qualified'}
          </Badge>
        </div>
      </div>
      <p className="text-sm text-muted-foreground">
        Forward evidence measures this bound deployed strategy and Flow. The linked historical run
        is a screening reference; it does not prove that the deployed algorithm is identical.
      </p>
      {campaign.binding_problem && (
        <p className="text-sm text-destructive">{campaign.binding_problem}</p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Progress
          label="Forward trading sessions"
          value={metrics.session_count}
          target={policy.min_sessions}
        />
        <Progress
          label="Closed forward trades"
          value={metrics.closed_trade_count}
          target={policy.min_closed_trades}
        />
      </div>
      <dl className="grid grid-cols-2 gap-5 md:grid-cols-4">
        <Metric label="Net P&L" value={money(metrics.net_pnl)} />
        <Metric label="Net expectancy / trade" value={money(metrics.expectancy)} />
        <Metric
          label="Profit factor"
          value={
            metrics.profit_factor_unbounded ? 'No losing trades' : numeric(metrics.profit_factor)
          }
        />
        <Metric label="Stressed net P&L" value={money(metrics.stressed_net_pnl)} />
        <Metric label="Observed marked drawdown" value={numeric(metrics.max_drawdown_pct, '%')} />
        <Metric label="Unresolved trades" value={numeric(metrics.unresolved_count)} />
        <Metric label="Invalid evidence" value={numeric(metrics.invalid_count)} />
        <Metric
          label="Risk breach"
          value={
            metrics.risk_breach == null
              ? 'Unavailable'
              : metrics.risk_breach
                ? 'Recorded'
                : 'None recorded'
          }
        />
      </dl>
      <div className="space-y-3">
        <h4 className="font-medium">Qualification checks</h4>
        {campaign.qualification.checks.length === 0 ? (
          <p className="text-sm text-muted-foreground">Qualification checks are unavailable.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {campaign.qualification.checks.map((check) => (
              <li key={check.code} className="flex items-start gap-2">
                <Badge variant={check.passed ? 'secondary' : 'outline'}>
                  {check.passed ? 'Passed' : 'Blocked'}
                </Badge>
                <span>{check.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer font-medium">
          Bound configuration and cost assumptions
        </summary>
        <section aria-label="Bound configuration" className="mt-3 space-y-4 rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">
            These are the recorded campaign assumptions. Fee rates are decimal fractions.
            Configuration changes require a new campaign.
          </p>
          <dl className="grid gap-4 sm:grid-cols-2">
            {(
              [
                ['Broker', binding?.broker],
                ['Pinned account', binding?.broker_connection_id],
                ['Risk policy', binding?.risk_policy_version],
                ['Campaign binding', campaign.binding_hash],
                ['Strategy fingerprint', binding?.strategy_hash],
                ['Flow fingerprint', binding?.workflow_hash],
                ['Execution source fingerprint', binding?.source_hash],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="min-w-0 space-y-1">
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="break-all font-mono text-xs">{value ?? 'Unavailable'}</dd>
              </div>
            ))}
            {(Object.keys(costLabels) as Array<keyof CostSchedule>).map((key) => (
              <div key={key} className="min-w-0 space-y-1">
                <dt className="text-xs text-muted-foreground">{costLabels[key]}</dt>
                <dd className="break-words">{binding?.costs?.[key] ?? 'Unavailable'}</dd>
              </div>
            ))}
          </dl>
        </section>
      </details>
      <details className="text-sm">
        <summary className="cursor-pointer font-medium">
          Forward trade evidence ({campaign.trades?.length ?? 0})
        </summary>
        {campaign.trades?.length ? (
          <section
            aria-label="Scrollable forward trade evidence"
            // biome-ignore lint/a11y/noNoninteractiveTabindex: Keyboard users must focus this horizontal scrolling region to inspect every column.
            tabIndex={0}
            className="overflow-x-auto pt-3 focus-visible:outline-2 focus-visible:outline-ring"
          >
            <table aria-label="Forward trade evidence" className="w-full caption-bottom text-sm">
              <TableHeader>
                <TableRow>
                  <TableHead>Trade</TableHead>
                  <TableHead>Session</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Orders</TableHead>
                  <TableHead>Net P&L</TableHead>
                  <TableHead>Stressed P&L</TableHead>
                  <TableHead>Evidence</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {campaign.trades.map((trade) => (
                  <TableRow key={trade.trade_ref}>
                    <TableCell className="font-mono text-xs">{trade.trade_ref}</TableCell>
                    <TableCell>{trade.session_day ?? 'Unavailable'}</TableCell>
                    <TableCell>{trade.status}</TableCell>
                    <TableCell>{numeric(trade.orders_count)}</TableCell>
                    <TableCell>{money(trade.net_pnl)}</TableCell>
                    <TableCell>{money(trade.stressed_net_pnl)}</TableCell>
                    <TableCell>
                      {trade.valid ? 'Complete' : 'Incomplete'}
                      {trade.issues?.length > 0 && (
                        <ul className="min-w-48 list-disc pl-4">
                          {trade.issues.map((issue) => (
                            <li key={issue}>{issue}</li>
                          ))}
                        </ul>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </table>
          </section>
        ) : (
          <p className="mt-3 text-muted-foreground">
            No forward trade evidence yet. Existing automated Sandbox execution collects evidence
            after enrollment.
          </p>
        )}
      </details>
      <CampaignReview
        key={`${campaign.id}:${campaign.revision}:${campaign.evidence_digest}:${campaign.reconciliation?.status}:${campaign.approval?.status}`}
        campaign={campaign}
        policy={policy}
        unavailable={unavailable}
        onReviewed={onReviewed}
      />
    </section>
  )
}

export default function QualificationPanel({ runs }: { runs: ResearchRun[] }) {
  const queryClient = useQueryClient()
  const [strategyId, setStrategyId] = useState('')
  const [finalRunId, setFinalRunId] = useState('')
  const [selectedCampaign, setSelectedCampaign] = useState<number | null>(null)
  const [notice, setNotice] = useState('')
  const overview = useQuery({
    queryKey: qualificationKeys.overview,
    queryFn: getQualification,
    refetchInterval: 15_000,
  })
  const campaigns = overview.data?.campaigns ?? []
  const strategies = overview.data?.strategies ?? []
  const campaignId = selectedCampaign ?? campaigns[0]?.id ?? null
  const detail = useQuery({
    queryKey: qualificationKeys.campaign(campaignId),
    queryFn: () => getQualificationCampaign(campaignId!),
    enabled: campaignId !== null,
    refetchInterval: 15_000,
  })
  const finalRuns = runs.filter((run) => run.kind === 'final' && run.status === 'completed')
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: qualificationKeys.overview })
    if (campaignId !== null)
      void queryClient.invalidateQueries({ queryKey: qualificationKeys.campaign(campaignId) })
  }
  const onReviewed = (campaign: QualificationCampaign, message: string) => {
    queryClient.setQueryData(qualificationKeys.campaign(campaign.id), campaign)
    setNotice(message)
    refresh()
  }
  const enrolled = useMutation({
    mutationFn: createQualificationCampaign,
    onSuccess: (campaign) => {
      setSelectedCampaign(campaign.id)
      queryClient.setQueryData(qualificationKeys.campaign(campaign.id), campaign)
      setNotice(
        'Sandbox campaign enrolled. Enrollment does not start trading. Forward Sandbox evidence is collected automatically from the bound strategy.'
      )
      void queryClient.invalidateQueries({ queryKey: qualificationKeys.overview })
    },
  })
  const policy = overview.data?.policy
  const unavailable = Boolean(overview.error || detail.error)
  return (
    <Card id="forward-qualification">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1.5">
            <CardTitle>
              <h2>Forward Sandbox qualification and live release</h2>
            </CardTitle>
            <CardDescription>
              Enroll the exact managed strategy, collect prospective Sandbox evidence, then review a
              separate live release.
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={overview.isFetching || detail.isFetching}
            onClick={refresh}
          >
            Refresh qualification
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {policy && (
          <p className="rounded-lg bg-muted/30 p-4 text-sm text-muted-foreground">
            Policy {policy.version}: a complete, profitable final screen with at least{' '}
            {policy.min_final_trades} trades, then {policy.min_sessions} forward sessions and{' '}
            {policy.min_closed_trades} closed trades, positive net expectancy, profit factor ≥{' '}
            {policy.min_profit_factor}, positive stressed net P&L, and observed marked drawdown ≤{' '}
            {policy.max_drawdown_pct}%. No unresolved trades, invalid execution evidence, risk
            breach or stale configuration. These fixed thresholds do not promise future returns.
          </p>
        )}
        {overview.isPending && (
          <p className="text-sm text-muted-foreground">Loading qualification evidence…</p>
        )}
        {overview.error && (
          <p role="alert" className="text-sm text-destructive">
            Qualification evidence is unavailable. {overview.error.message}
          </p>
        )}
        <div className="space-y-4 rounded-lg border p-4">
          <h3 className="font-medium">Enroll a prospective Sandbox campaign</h3>
          <p className="text-sm text-muted-foreground">
            Enrollment records the current strategy, Flow, pinned account, risk policy and cost
            assumptions. It does not start trading. Continue the bound automated strategy in Sandbox
            to collect new evidence.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="qualification-strategy">Deployed strategy</Label>
              <select
                id="qualification-strategy"
                className={selectClass}
                value={strategyId}
                disabled={enrolled.isPending || !overview.data || Boolean(overview.error)}
                onChange={(event) => setStrategyId(event.target.value)}
              >
                <option value="">Select a strategy</option>
                {strategies.map((strategy) => (
                  <option key={strategy.id} value={strategy.id}>
                    {strategy.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="qualification-final-run">Final research reference</Label>
              <select
                id="qualification-final-run"
                className={selectClass}
                value={finalRunId}
                disabled={enrolled.isPending}
                onChange={(event) => setFinalRunId(event.target.value)}
              >
                <option value="">Select a completed final run</option>
                {finalRuns.map((run) => (
                  <option key={run.id} value={run.id}>
                    Run #{run.id} · {run.candidate.replaceAll('_', ' ')}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {overview.data && strategies.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No managed strategies are available for enrollment.
            </p>
          )}
          {finalRuns.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Complete a sealed final research run to add a screening reference.
            </p>
          )}
          <Button
            variant="outline"
            disabled={
              enrolled.isPending ||
              !overview.data ||
              Boolean(overview.error) ||
              !strategies.some((item) => String(item.id) === strategyId) ||
              !finalRuns.some((run) => String(run.id) === finalRunId)
            }
            onClick={() => {
              setNotice('')
              enrolled.mutate({ strategy_id: Number(strategyId), final_run_id: Number(finalRunId) })
            }}
          >
            {enrolled.isPending ? 'Enrolling…' : 'Enroll Sandbox campaign'}
          </Button>
          {enrolled.error && (
            <p role="alert" className="text-sm text-destructive">
              {enrolled.error.message}
            </p>
          )}
        </div>
        {notice && (
          <output aria-label="Qualification action result" className="block text-sm">
            {notice}
          </output>
        )}
        {campaigns.length > 0 && (
          <div className="max-w-xl space-y-2">
            <Label htmlFor="qualification-campaign">Sandbox campaign</Label>
            <select
              id="qualification-campaign"
              className={selectClass}
              value={campaignId ?? ''}
              onChange={(event) => {
                setSelectedCampaign(Number(event.target.value))
                setNotice('')
              }}
            >
              {campaigns.map((campaign) => (
                <option key={campaign.id} value={campaign.id}>
                  Campaign #{campaign.id} ·{' '}
                  {strategies.find((strategy) => strategy.id === campaign.strategy_id)?.name ??
                    `Strategy #${campaign.strategy_id}`}{' '}
                  · {campaign.status.replaceAll('_', ' ')}
                </option>
              ))}
            </select>
          </div>
        )}
        {overview.data && !overview.error && campaigns.length === 0 && !detail.data && (
          <p className="text-sm text-muted-foreground">
            No forward campaigns yet. Enrollment starts a prospective evidence record.
          </p>
        )}
        {detail.isFetching && !detail.data && (
          <p className="text-sm text-muted-foreground">Loading campaign…</p>
        )}
        {detail.error && (
          <p role="alert" className="text-sm text-destructive">
            Campaign evidence is unavailable. {detail.error.message}
          </p>
        )}
        {detail.data && policy && (
          <CampaignEvidence
            campaign={detail.data}
            policy={policy}
            unavailable={unavailable}
            strategyName={
              strategies.find((strategy) => strategy.id === detail.data.strategy_id)?.name ??
              `Strategy #${detail.data.strategy_id}`
            }
            onReviewed={onReviewed}
          />
        )}
      </CardContent>
    </Card>
  )
}
