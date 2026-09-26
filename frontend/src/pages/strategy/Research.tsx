import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import {
  createResearchRun,
  getResearch,
  getResearchRun,
  getTradingRisk,
  importResearchDataset,
  researchKeys,
  researchRunAction,
  resumeTradingRisk,
  saveRiskCosts,
} from '@/api/trading-research'
import QualificationPanel from '@/components/strategy/QualificationPanel'
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
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import type {
  CostSchedule,
  ResearchCandidateId,
  ResearchMetrics,
  ResearchRun,
  RiskAccount,
} from '@/types/trading-research'

const money = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value)
    ? 'Unavailable'
    : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(value)
const number = (value: number | null | undefined, suffix = '') =>
  value == null || !Number.isFinite(value)
    ? 'Unavailable'
    : `${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}${suffix}`
const selectClass =
  'border-input bg-background h-9 w-full rounded-md border px-3 text-sm focus-visible:outline-2 focus-visible:outline-ring'
const activeRun = (run?: ResearchRun) => run?.status === 'queued' || run?.status === 'running'

const costFields = [
  ['schedule_id', 'Schedule name', 'text'],
  ['source', 'Fee source or reference', 'text'],
  ['effective_from', 'Effective from', 'date'],
  ['effective_to', 'Effective until', 'date'],
  ['brokerage_per_order', 'Brokerage per order (INR)', 'number'],
  ['exchange_rate', 'Exchange fee rate', 'number'],
  ['sebi_rate', 'SEBI fee rate', 'number'],
  ['gst_rate', 'GST rate', 'number'],
  ['stamp_buy_rate', 'Stamp duty buy rate', 'number'],
  ['stt_sell_rate', 'STT sell rate', 'number'],
  ['slippage_bps', 'Slippage (basis points)', 'number'],
] as const

const parameterLabels: Record<string, string> = {
  lookback: 'Lookback bars',
  stop_pct: 'Premium stop fraction',
  target_pct: 'Premium target fraction',
  volume_ratio: 'Volume ratio',
  pullback_tolerance: 'VWAP pullback tolerance',
}

const datasetTemplate = {
  name: 'REPLACE_WITH_DATASET_NAME',
  provider: 'REPLACE_WITH_PROVIDER',
  metadata: {
    underlying_symbol: 'REPLACE_WITH_UNDERLYING',
    timezone: 'Asia/Kolkata',
    bar_minutes: 5,
    timestamp_convention: 'bar_close',
    session_open: 'HH:MM',
    session_close: '15:25',
    source_reference: 'REPLACE_WITH_EXPORT_REFERENCE',
    contracts: [
      {
        symbol: 'REPLACE_WITH_OPTION_SYMBOL',
        underlying: 'REPLACE_WITH_UNDERLYING',
        exchange: 'NFO',
        option_type: 'CE',
        strike: 0,
        expiry: 'YYYY-MM-DD',
        lot_size: 0,
        multiplier: 0,
        segment: 'index',
      },
    ],
  },
  rows: [],
}

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('The file could not be read. Choose it again.'))
    reader.readAsText(file)
  })
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-mono text-lg tabular-nums">{value}</dd>
    </div>
  )
}

function Budget({
  name,
  account,
  enabled,
}: {
  name: string
  account: RiskAccount | null
  enabled: boolean
}) {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const [reconciled, setReconciled] = useState(false)
  const mode = name === 'Sandbox' ? 'sandbox' : 'live'
  const resumed = useMutation({
    mutationFn: resumeTradingRisk,
    onSuccess: () => {
      setReason('')
      setReconciled(false)
      void queryClient.invalidateQueries({ queryKey: researchKeys.risk })
    },
  })
  return (
    <section aria-label={`${name} risk budget`} className="rounded-lg border p-4 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-medium">{name}</h3>
        <Badge variant={enabled && account?.paused ? 'destructive' : 'outline'}>
          {!enabled
            ? 'Profile inactive'
            : account
              ? account.paused
                ? 'Entries paused'
                : 'Budget monitored'
              : 'Unavailable'}
        </Badge>
      </div>
      <dl className="grid grid-cols-2 gap-4">
        <Metric label="First filled trade remaining" value={money(account?.first_remaining)} />
        <Metric label="All later trades remaining" value={money(account?.later_remaining)} />
        <Metric label="Daily remaining" value={money(account?.daily_remaining)} />
        <Metric label="Drawdown headroom" value={money(account?.drawdown_headroom)} />
        <Metric label="Equity" value={money(account?.equity)} />
        <Metric label="Reserved risk" value={money(account?.reserved_risk)} />
      </dl>
      {account?.pause_reason && <p className="text-sm text-destructive">{account.pause_reason}</p>}
      <p className="text-xs text-muted-foreground">
        {account
          ? `Session ${account.session_day} · Peak equity ${money(account.peak_equity)}`
          : 'No risk ledger evidence is available for this mode yet.'}
      </p>
      {enabled && account?.paused && (
        <div className="space-y-3 border-t pt-4">
          <h4 className="text-sm font-medium">Reconcile before resuming</h4>
          <p className="text-xs text-muted-foreground">
            Resuming sets the equity peak to the reviewed current equity of {money(account.equity)}.
            Daily loss allowances will not reset. Existing strategy and session permissions still
            apply.
          </p>
          <div className="space-y-2">
            <Label htmlFor={`resume-reason-${mode}`}>Review reason</Label>
            <Textarea
              id={`resume-reason-${mode}`}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={reconciled}
              onChange={(event) => setReconciled(event.target.checked)}
            />
            I reconciled positions, fills, costs and the current equity against the account records.
          </label>
          <Button
            variant="outline"
            size="sm"
            disabled={!reason.trim() || !reconciled || resumed.isPending}
            onClick={() => resumed.mutate({ mode, reason: reason.trim(), reconciled: true })}
          >
            {resumed.isPending ? 'Recording review…' : 'Resume after reconciliation'}
          </Button>
          {resumed.error && (
            <p role="alert" className="text-sm text-destructive">
              {resumed.error.message}
            </p>
          )}
        </div>
      )}
      {resumed.isSuccess && (
        <output className="block text-sm">
          The reconciliation review was recorded. Risk status is refreshing.
        </output>
      )}
    </section>
  )
}

function Metrics({ metrics }: { metrics: ResearchMetrics }) {
  return (
    <dl className="grid grid-cols-2 gap-5 md:grid-cols-4">
      <Metric label="Net P&L" value={money(metrics.net_pnl)} />
      <Metric label="Net expectancy / trade" value={money(metrics.expectancy)} />
      <Metric
        label="Profit factor"
        value={metrics.profit_factor_unbounded ? 'No losing trades' : number(metrics.profit_factor)}
      />
      <Metric label="Maximum drawdown" value={number(metrics.max_drawdown_pct, '%')} />
      <Metric label="Trades" value={number(metrics.trade_count)} />
      <Metric label="Win rate" value={number(metrics.win_rate, '%')} />
      <Metric label="Longest losing streak" value={number(metrics.max_losing_streak)} />
      <Metric label="Ending equity" value={money(metrics.ending_equity)} />
      <Metric label="Bars with exposure" value={number(metrics.exposure_bars)} />
      <Metric
        label="Observed open drawdown"
        value={number(metrics.max_observed_open_drawdown_pct, '%')}
      />
    </dl>
  )
}

export default function Research() {
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [csvMetadata, setCsvMetadata] = useState('')
  const [csvName, setCsvName] = useState('')
  const [csvProvider, setCsvProvider] = useState('')
  const [datasetId, setDatasetId] = useState('')
  const [candidateId, setCandidateId] = useState<ResearchCandidateId>('trend_breakout')
  const [parameters, setParameters] = useState<Record<string, string>>({})
  const [costEdits, setCostEdits] = useState<Record<string, string>>({})
  const [seed, setSeed] = useState('42')
  const [selectedRun, setSelectedRun] = useState<number | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [finalOpen, setFinalOpen] = useState(false)
  const [finalConfirmed, setFinalConfirmed] = useState(false)

  const overview = useQuery({
    queryKey: researchKeys.overview,
    queryFn: getResearch,
    refetchInterval: 15_000,
  })
  const risk = useQuery({
    queryKey: researchKeys.risk,
    queryFn: getTradingRisk,
    refetchInterval: 15_000,
  })
  const detail = useQuery({
    queryKey: researchKeys.run(selectedRun),
    queryFn: () => getResearchRun(selectedRun!),
    enabled: selectedRun !== null,
    refetchInterval: (query) => (activeRun(query.state.data) ? 3_000 : false),
  })
  const candidate = overview.data?.candidates.find((item) => item.id === candidateId)
  const selectedDataset = overview.data?.datasets.find((item) => item.id === Number(datasetId))
  const currentRun = detail.data
  const report = currentRun?.report
  const csv = file?.name.toLowerCase().endsWith('.csv')
  const workerOnline = overview.data?.worker.online === true
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: researchKeys.overview })
  }

  const imported = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a dataset file first.')
      if (file.size > 20 * 1024 * 1024) throw new Error('Choose a file smaller than 20 MB.')
      const contents = await readFile(file)
      let payload: Record<string, unknown>
      if (csv) {
        if (!csvMetadata.trim())
          throw new Error(
            'CSV metadata is required. Supply the contract and source details before importing.'
          )
        let metadata: unknown
        try {
          metadata = JSON.parse(csvMetadata)
        } catch {
          throw new Error('CSV metadata must be valid JSON. Use the format guide below.')
        }
        if (!csvName.trim() || !csvProvider.trim())
          throw new Error('Enter a dataset name and data provider for the CSV.')
        payload = { name: csvName.trim(), provider: csvProvider.trim(), metadata, csv: contents }
      } else {
        try {
          payload = JSON.parse(contents)
        } catch {
          throw new Error('The dataset file must contain valid JSON or be a CSV file.')
        }
        if (!payload || typeof payload !== 'object' || Array.isArray(payload))
          throw new Error('The JSON file must contain a dataset object.')
      }
      return importResearchDataset(payload)
    },
    onSuccess: (data) => {
      setDatasetId(String(data.id))
      refresh()
    },
  })

  const costValue = (key: keyof CostSchedule) =>
    costEdits[key] ?? String(risk.data?.costs?.[key] ?? '')
  const readCosts = (): CostSchedule => {
    const result: Record<string, string | number> = {}
    for (const [key, label, type] of costFields) {
      const value = costValue(key).trim()
      if (!value)
        throw new Error(`Enter ${label.toLowerCase()}. Missing costs cannot be treated as zero.`)
      if (type === 'number') {
        const parsed = Number(value)
        if (!Number.isFinite(parsed) || parsed < 0)
          throw new Error(`${label} must be a non-negative number.`)
        result[key] = parsed
      } else {
        result[key] = value
      }
    }
    return result as unknown as CostSchedule
  }

  const created = useMutation({
    mutationFn: createResearchRun,
    onSuccess: (run) => {
      setSelectedRun(run.id)
      refresh()
    },
  })
  const savedCosts = useMutation({
    mutationFn: saveRiskCosts,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: researchKeys.risk })
    },
  })
  const action = useMutation({
    mutationFn: ({ id, verb }: { id: number; verb: 'freeze' | 'cancel' | 'final-test' }) =>
      researchRunAction(id, verb),
    onSuccess: (run) => {
      setSelectedRun(run.id)
      setFinalOpen(false)
      setFinalConfirmed(false)
      void queryClient.invalidateQueries({ queryKey: researchKeys.run(run.id) })
      refresh()
    },
  })

  const submitRun = () => {
    setFormError(null)
    try {
      if (!datasetId || !candidate)
        throw new Error('Select an imported dataset and candidate first.')
      const parsedParameters: Record<string, number> = {}
      for (const [key, fallback] of Object.entries(candidate.defaults)) {
        const value = parameters[key] ?? String(fallback)
        if (!value.trim() || !Number.isFinite(Number(value)))
          throw new Error(`Enter a valid ${parameterLabels[key] ?? key}.`)
        parsedParameters[key] = Number(value)
      }
      if (!seed.trim() || !Number.isSafeInteger(Number(seed)) || Number(seed) < 0)
        throw new Error('The reproducibility seed must be a non-negative whole number.')
      created.mutate({
        dataset_id: Number(datasetId),
        candidate: candidateId,
        parameters: parsedParameters,
        costs: readCosts(),
        seed: Number(seed),
      })
    } catch (error) {
      setFormError((error as Error).message)
    }
  }

  return (
    <div className="space-y-6 pb-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link to="/strategy" className="text-sm text-muted-foreground hover:underline">
            Strategies
          </Link>
          <h1 className="mt-1 text-2xl font-bold tracking-tight">Research</h1>
          <p className="text-sm text-muted-foreground max-w-2xl">
            Test explicit trading rules against imported market history, after costs. Build evidence
            before risking capital.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">Reviewed release required</Badge>
          <Badge variant={workerOnline ? 'secondary' : 'outline'}>
            {overview.isPending
              ? 'Checking worker'
              : workerOnline
                ? 'Worker online'
                : 'Worker offline'}
          </Badge>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              refresh()
              void risk.refetch()
              if (selectedRun) void detail.refetch()
            }}
          >
            Refresh
          </Button>
        </div>
      </div>

      {overview.error && (
        <p role="alert" className="text-sm text-destructive">
          Research could not be loaded. {overview.error.message}
        </p>
      )}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>Shared long-options capital profile</CardTitle>
            {risk.data && (
              <Badge variant={risk.data.enabled ? 'secondary' : 'outline'}>
                {risk.data.enabled ? 'Capital profile enabled' : 'Capital profile inactive'}
              </Badge>
            )}
          </div>
          <CardDescription>
            {risk.data
              ? `${money(risk.data.policy.capital)} allocation · ${money(risk.data.policy.daily_limit)} daily loss limit · ${number(risk.data.policy.drawdown_pct * 100, '%')} peak-equity drawdown pause · ${number(risk.data.policy.cash_buffer_pct * 100, '%')} cash buffer`
              : 'Loading the configured risk policy…'}
            <span className="block mt-1">
              Profits do not replenish loss allowances. First-trade and later-trade budgets cannot
              transfer to each other.
            </span>
            {risk.data && !risk.data.enabled && (
              <span className="block mt-2">
                Existing flows retain their current risk rules. This profile does not protect their
                entries while inactive. Save verified costs below to explicitly enable it for your
                managed Strategy Module entries.
              </span>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {risk.error ? (
            <p role="alert" className="text-sm text-destructive">
              Risk evidence is unavailable. {risk.error.message}
            </p>
          ) : risk.data ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <Budget
                name="Sandbox"
                account={risk.data.accounts.sandbox}
                enabled={risk.data.enabled}
              />
              <Budget name="Live" account={risk.data.accounts.live} enabled={risk.data.enabled} />
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Loading risk evidence…</p>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <Card>
          <CardHeader>
            <CardTitle>1. Import market history</CardTitle>
            <CardDescription>
              Use licensed or permitted historical data. Imports are immutable and retain their
              source and content fingerprint.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="dataset-file">Dataset file</Label>
              <Input
                id="dataset-file"
                type="file"
                accept=".json,.csv,application/json,text/csv"
                onChange={(event) => {
                  setFile(event.target.files?.[0] ?? null)
                  imported.reset()
                }}
              />
              <p className="text-xs text-muted-foreground">
                JSON bundle or CSV, up to 20 MB including metadata. At least 80 sessions are needed:
                60 remain sealed for final evaluation.
              </p>
            </div>
            {csv && (
              <div className="space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="csv-name">Dataset name</Label>
                  <Input
                    id="csv-name"
                    value={csvName}
                    onChange={(event) => setCsvName(event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="csv-provider">Data provider</Label>
                  <Input
                    id="csv-provider"
                    value={csvProvider}
                    onChange={(event) => setCsvProvider(event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="csv-metadata">CSV metadata (JSON)</Label>
                  <Textarea
                    id="csv-metadata"
                    rows={7}
                    className="font-mono text-xs"
                    value={csvMetadata}
                    onChange={(event) => setCsvMetadata(event.target.value)}
                    placeholder="Paste the metadata object from the format guide"
                  />
                </div>
              </div>
            )}
            <Button disabled={!file || imported.isPending} onClick={() => imported.mutate()}>
              {imported.isPending ? 'Importing…' : 'Import dataset'}
            </Button>
            {imported.error && (
              <p role="alert" className="text-sm text-destructive">
                {imported.error.message}
              </p>
            )}
            {imported.data && (
              <output aria-label="Import result" className="block text-sm">
                Imported {imported.data.name}. {number(imported.data.row_count)} bars validated.
              </output>
            )}
            <details className="rounded-lg border p-3 text-sm">
              <summary className="cursor-pointer font-medium">Required dataset format</summary>
              <div className="space-y-3 pt-3 text-muted-foreground">
                <p>
                  JSON contains name, provider, metadata and rows. CSV needs the same metadata
                  separately and these columns: symbol,timestamp,open,high,low,close,volume.
                </p>
                <p>
                  Each row is an underlying or option candle. Use timezone-aware timestamps such as
                  2026-01-05T09:20:00+05:30, with bar-close time. Do not include future bars.
                </p>
                <p>
                  VWAP requires observed underlying volume and an explicit session_open in HH:MM,
                  verified against your source. No opening time is assumed. Every session must start
                  with the underlying close at session_open plus bar_minutes. For a verified 09:15
                  opening and five-minute bars, that first close is 09:20. Missing opening bars make
                  the history unsuitable for session VWAP. Trend tests may omit session_open.
                </p>
                <p>
                  Metadata must provide the underlying, source reference, Asia/Kolkata timezone, bar
                  interval, session close and point-in-time contracts: symbol, underlying, exchange,
                  CE/PE, strike, expiry, lot size, multiplier and index/mcx segment. Verify these
                  values against the source; the template contains placeholders and no prices.
                </p>
                <a
                  className="text-primary underline"
                  download="research-dataset-template.json"
                  href={`data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(datasetTemplate, null, 2))}`}
                >
                  Download empty JSON template
                </a>
                <pre className="overflow-x-auto rounded bg-muted p-3 text-xs">
                  {JSON.stringify(datasetTemplate.metadata, null, 2)}
                </pre>
              </div>
            </details>
            <div className="space-y-2">
              <Label htmlFor="research-dataset">Research dataset</Label>
              <select
                id="research-dataset"
                className={selectClass}
                value={datasetId}
                onChange={(event) => setDatasetId(event.target.value)}
              >
                <option value="">Select imported history</option>
                {overview.data?.datasets.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} ({item.session_count} sessions)
                  </option>
                ))}
              </select>
            </div>
            {selectedDataset ? (
              <div className="rounded-lg bg-muted/40 p-3 text-xs space-y-2">
                <p>
                  {selectedDataset.provider} · {number(selectedDataset.row_count)} bars ·{' '}
                  {selectedDataset.start} to {selectedDataset.end}
                </p>
                <p className="break-all font-mono">Fingerprint: {selectedDataset.content_hash}</p>
                <p>
                  Candle screening only. Quotes, spreads and actual fills are not established by
                  candles.
                </p>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                No dataset selected. No market prices are supplied with this workspace.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>2. Define a reproducible experiment</CardTitle>
            <CardDescription>
              Signals use closed underlying bars. Option executions occur on a subsequent bar, with
              whole-lot sizing and the configured risk budget.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="research-candidate">Candidate rules</Label>
              <select
                id="research-candidate"
                value={candidateId}
                onChange={(event) => {
                  setCandidateId(event.target.value as ResearchCandidateId)
                  setParameters({})
                }}
                className={selectClass}
              >
                {overview.data?.candidates.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              <p className="text-sm text-muted-foreground">{candidate?.description}</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {Object.entries(candidate?.defaults ?? {}).map(([key, fallback]) => (
                <div className="space-y-2" key={key}>
                  <Label htmlFor={`parameter-${key}`}>{parameterLabels[key] ?? key}</Label>
                  <Input
                    id={`parameter-${key}`}
                    type="number"
                    step="any"
                    value={parameters[key] ?? String(fallback)}
                    onChange={(event) =>
                      setParameters((previous) => ({ ...previous, [key]: event.target.value }))
                    }
                  />
                </div>
              ))}
              <div className="space-y-2">
                <Label htmlFor="research-seed">Reproducibility seed</Label>
                <Input
                  id="research-seed"
                  type="number"
                  min="0"
                  step="1"
                  value={seed}
                  onChange={(event) => setSeed(event.target.value)}
                />
              </div>
            </div>
            <div className="border-t pt-4 space-y-3">
              <h3 className="font-medium">Costs and execution assumptions</h3>
              {risk.data?.enabled && !risk.data.costs && (
                <p className="text-sm text-destructive">
                  Entry risk is blocked until a complete, dated cost schedule is saved.
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                Enter the applicable fee schedule and dates from your broker or exchange. Rates are
                decimal fractions (0.18 means 18%); one basis point is 0.01%. No missing fee is
                assumed to be zero.
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                {costFields.map(([key, label, type]) => (
                  <div className="space-y-2" key={key}>
                    <Label htmlFor={`cost-${key}`}>{label}</Label>
                    <Input
                      id={`cost-${key}`}
                      type={type}
                      min={type === 'number' ? '0' : undefined}
                      step={type === 'number' ? 'any' : undefined}
                      value={costValue(key)}
                      onChange={(event) => {
                        setCostEdits((previous) => ({ ...previous, [key]: event.target.value }))
                        savedCosts.reset()
                      }}
                    />
                  </div>
                ))}
              </div>
              <p id="capital-profile-effect" className="text-sm text-muted-foreground">
                {risk.data?.enabled
                  ? 'Updating costs keeps this capital profile enabled.'
                  : `Saving costs enables the shared ${money(risk.data?.policy.capital)} long-options capital profile.`}{' '}
                It applies to your managed Strategy Module entries, restricts them to supported
                long-option trades, and requires release qualification for new managed live entries.
                Running a research test alone does not enable the profile.
              </p>
              <Button
                variant="outline"
                disabled={savedCosts.isPending || !risk.data || Boolean(risk.error)}
                aria-describedby="capital-profile-effect"
                onClick={() => {
                  setFormError(null)
                  try {
                    savedCosts.mutate(readCosts())
                  } catch (error) {
                    setFormError((error as Error).message)
                  }
                }}
              >
                {savedCosts.isPending
                  ? 'Saving profile…'
                  : risk.data?.enabled
                    ? 'Update enabled profile costs'
                    : 'Save costs and enable capital profile'}
              </Button>
              {savedCosts.isSuccess && (
                <output className="block text-sm">
                  The cost schedule was saved and the capital profile is enabled.
                </output>
              )}
              {savedCosts.error && (
                <p role="alert" className="text-sm text-destructive">
                  {savedCosts.error.message}
                </p>
              )}
            </div>
            <div className="border-t pt-4 space-y-3">
              <p className="text-xs text-muted-foreground">
                Development tests cannot view the final 60 sessions. Freeze a completed version
                before consuming that holdout once. Historical returns do not establish future
                profitability.
              </p>
              {!workerOnline && !overview.isPending && (
                <p className="text-sm text-muted-foreground">
                  The research worker is offline. Start it on the server before running experiments.
                </p>
              )}
              <Button
                disabled={!workerOnline || !datasetId || !candidate || created.isPending}
                onClick={submitRun}
              >
                {created.isPending ? 'Queuing…' : 'Run development test'}
              </Button>
              {(formError || created.error) && (
                <p role="alert" className="text-sm text-destructive">
                  {formError ?? created.error?.message}
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>3. Review evidence</CardTitle>
          <CardDescription>
            Results bind the dataset, candidate parameters, fees and seed to one version.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {overview.data?.runs.length ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Run</TableHead>
                    <TableHead>Candidate</TableHead>
                    <TableHead>Evaluation</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Version</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {overview.data.runs.map((run) => (
                    <TableRow key={run.id}>
                      <TableCell>#{run.id}</TableCell>
                      <TableCell>
                        {overview.data.candidates.find((item) => item.id === run.candidate)?.name ??
                          run.candidate}
                      </TableCell>
                      <TableCell>
                        {run.kind === 'final' ? 'Final holdout' : 'Development'}
                      </TableCell>
                      <TableCell>
                        <Badge variant={run.status === 'failed' ? 'destructive' : 'outline'}>
                          {run.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {run.configuration_hash.slice(0, 12)}
                        {run.frozen_at && ' · Frozen'}
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`View run ${run.id}`}
                          onClick={() => setSelectedRun(run.id)}
                        >
                          View
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No experiments yet. Import market history and run a development test to build the
              first report.
            </p>
          )}
          {detail.isFetching && !currentRun && (
            <p className="text-sm text-muted-foreground">Loading run…</p>
          )}
          {detail.error && (
            <p role="alert" className="text-sm text-destructive">
              {detail.error.message}
            </p>
          )}
          {currentRun && (
            <section aria-label="Run report" className="space-y-5 rounded-lg border p-4 md:p-6">
              <div className="flex flex-wrap justify-between gap-3">
                <div>
                  <h3 className="font-semibold">
                    Run #{currentRun.id} ·{' '}
                    {currentRun.kind === 'final' ? 'Final holdout' : 'Development'}
                  </h3>
                  <p className="mt-1 text-xs font-mono break-all text-muted-foreground">
                    {currentRun.configuration_hash}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {activeRun(currentRun) && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={action.isPending}
                      onClick={() => action.mutate({ id: currentRun.id, verb: 'cancel' })}
                    >
                      Cancel run
                    </Button>
                  )}
                  {currentRun.kind === 'development' &&
                    currentRun.status === 'completed' &&
                    !currentRun.frozen_at && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={action.isPending}
                        onClick={() => action.mutate({ id: currentRun.id, verb: 'freeze' })}
                      >
                        Freeze this version
                      </Button>
                    )}
                  {currentRun.kind === 'development' && currentRun.frozen_at && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={
                        !workerOnline ||
                        action.isPending ||
                        overview.data?.runs.some(
                          (run) => run.parent_run_id === currentRun.id && run.kind === 'final'
                        )
                      }
                      onClick={() => {
                        setFinalConfirmed(false)
                        setFinalOpen(true)
                      }}
                    >
                      Run final holdout once
                    </Button>
                  )}
                </div>
              </div>
              {currentRun.error && (
                <p role="alert" className="text-sm text-destructive">
                  {currentRun.error}
                </p>
              )}
              {action.error && (
                <p role="alert" className="text-sm text-destructive">
                  {action.error.message}
                </p>
              )}
              {report ? (
                <>
                  <h4 className="font-medium">
                    {currentRun.kind === 'final'
                      ? 'Final holdout evidence'
                      : 'Development training evidence'}
                  </h4>
                  <Metrics metrics={report.metrics} />
                  <div className="rounded-lg border bg-muted/30 p-4 space-y-2">
                    <h4 className="font-medium">Qualification: research only</h4>
                    <ul className="list-disc pl-5 text-sm text-muted-foreground">
                      {report.qualification.reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  </div>
                  {report.oos && (
                    <div className="space-y-3 border-t pt-4">
                      <h4 className="font-medium">Development out-of-sample evidence</h4>
                      <Metrics metrics={report.oos.metrics} />
                      <ul className="list-disc pl-5 text-sm text-muted-foreground">
                        {report.oos.qualification.reasons.map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {report.stress && (
                    <div className="space-y-3 border-t pt-4">
                      <h4 className="font-medium">Execution stress</h4>
                      <Metrics metrics={report.stress.metrics} />
                      <p className="text-xs text-muted-foreground">
                        Stress applies doubled slippage plus 10 basis points and 1.5 times
                        brokerage.
                      </p>
                      <ul className="list-disc pl-5 text-sm text-muted-foreground">
                        {report.stress.qualification.reasons.map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {Object.keys(report.rejections).length > 0 && (
                    <div className="space-y-2">
                      <h4 className="font-medium">Rejected opportunities</h4>
                      <ul className="text-sm text-muted-foreground">
                        {Object.entries(report.rejections).map(([reason, count]) => (
                          <li key={reason}>
                            {reason.replaceAll('_', ' ')}: {count}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {report.split && (
                    <div className="space-y-3">
                      <h4 className="font-medium">Evaluation split</h4>
                      <dl className="grid grid-cols-2 gap-4 md:grid-cols-4">
                        {currentRun.kind === 'development' ? (
                          <>
                            <Metric
                              label="Training sessions"
                              value={number(report.split.training_sessions)}
                            />
                            <Metric
                              label="Out-of-sample sessions"
                              value={number(report.split.oos_sessions)}
                            />
                          </>
                        ) : (
                          <Metric
                            label="Evaluated sessions"
                            value={number(report.split.evaluated_sessions)}
                          />
                        )}
                        <Metric
                          label={
                            currentRun.kind === 'final'
                              ? 'Consumed holdout sessions'
                              : 'Sealed holdout sessions'
                          }
                          value={number(report.split.holdout_sessions)}
                        />
                      </dl>
                    </div>
                  )}
                  {report.bootstrap && (
                    <div className="rounded-lg bg-muted/30 p-4 space-y-3">
                      <h4 className="font-medium">Exploratory uncertainty</h4>
                      <p className="text-xs text-muted-foreground">{report.bootstrap.method}</p>
                      <dl className="grid grid-cols-2 gap-4">
                        <Metric
                          label="Net P&L, 5th percentile"
                          value={money(report.bootstrap.net_pnl_p05)}
                        />
                        <Metric
                          label="Net P&L, 95th percentile"
                          value={money(report.bootstrap.net_pnl_p95)}
                        />
                      </dl>
                      <p className="text-xs text-muted-foreground">{report.bootstrap.warning}</p>
                    </div>
                  )}
                  {currentRun.configuration && (
                    <details className="text-sm">
                      <summary className="cursor-pointer font-medium">
                        Recorded experiment inputs
                      </summary>
                      <section
                        aria-label="Recorded experiment inputs"
                        className="mt-3 rounded-lg border p-4 space-y-4"
                      >
                        <p className="text-xs text-muted-foreground">
                          These are the exact inputs saved for this run. Editing the experiment form
                          does not change this evidence. Fee rates below are decimal fractions.
                        </p>
                        <dl className="grid grid-cols-2 gap-4">
                          <Metric label="Seed" value={String(currentRun.configuration.seed)} />
                          {Object.entries(currentRun.configuration.parameters).map(
                            ([key, value]) => (
                              <Metric
                                key={key}
                                label={parameterLabels[key] ?? key}
                                value={String(value)}
                              />
                            )
                          )}
                          {costFields.map(([key, label]) => (
                            <div className="space-y-1 min-w-0" key={key}>
                              <dt className="text-xs text-muted-foreground">{label}</dt>
                              <dd className="break-words">
                                {String(currentRun.configuration!.costs[key])}
                              </dd>
                            </div>
                          ))}
                        </dl>
                        <p className="text-xs break-all">
                          Dataset fingerprint: {currentRun.configuration.dataset_hash}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Engine {currentRun.configuration.engine_version} · Risk policy{' '}
                          {currentRun.configuration.risk_policy_version}
                        </p>
                      </section>
                    </details>
                  )}
                  <details className="text-sm">
                    <summary className="cursor-pointer font-medium">
                      Trade evidence ({report.trades.length})
                    </summary>
                    <div className="overflow-x-auto pt-3">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Contract</TableHead>
                            <TableHead>Signal</TableHead>
                            <TableHead>Entry bar</TableHead>
                            <TableHead>Quantity</TableHead>
                            <TableHead>Gross P&L</TableHead>
                            <TableHead>Costs</TableHead>
                            <TableHead>Net P&L</TableHead>
                            <TableHead>Exit</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {report.trades.map((trade, index) => (
                            <TableRow key={`${trade.symbol}-${trade.signal_at}-${index}`}>
                              <TableCell>{trade.symbol}</TableCell>
                              <TableCell>{trade.signal_at}</TableCell>
                              <TableCell>{trade.entry_bar_at}</TableCell>
                              <TableCell>{trade.quantity}</TableCell>
                              <TableCell>{money(trade.gross_pnl)}</TableCell>
                              <TableCell>{money(trade.costs)}</TableCell>
                              <TableCell>{money(trade.net_pnl)}</TableCell>
                              <TableCell>{trade.exit_reason.replaceAll('_', ' ')}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </details>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {activeRun(currentRun)
                    ? 'The experiment is in progress. Results will appear after it completes.'
                    : 'No completed report is available for this run.'}
                </p>
              )}
            </section>
          )}
        </CardContent>
      </Card>

      <QualificationPanel runs={overview.data?.runs ?? []} />

      <Dialog open={finalOpen} onOpenChange={setFinalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Evaluate the frozen version once</DialogTitle>
            <DialogDescription>
              The final 60 sessions are reserved for this decision. Starting the final test consumes
              this holdout for the imported contents, even if the run fails or is cancelled.
              Changing parameters afterward cannot restore an untouched final test.
            </DialogDescription>
          </DialogHeader>
          <label className="flex items-start gap-3 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={finalConfirmed}
              onChange={(event) => setFinalConfirmed(event.target.checked)}
            />
            I have finished selecting the candidate and understand that this consumes the final
            holdout.
          </label>
          {action.error && (
            <p role="alert" className="text-sm text-destructive">
              {action.error.message}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setFinalOpen(false)}>
              Keep sealed
            </Button>
            <Button
              disabled={!finalConfirmed || !workerOnline || action.isPending || !currentRun}
              onClick={() => {
                if (currentRun) action.mutate({ id: currentRun.id, verb: 'final-test' })
              }}
            >
              {action.isPending ? 'Queuing…' : 'Consume holdout and run'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
