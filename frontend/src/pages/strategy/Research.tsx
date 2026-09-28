import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import {
  createResearchRun,
  getResearch,
  getResearchRun,
  getTradingRisk,
  installFrozenMLRun,
  importResearchDataset,
  researchKeys,
  researchRunAction,
  resumeTradingRisk,
  reviewRiskAllocation,
  saveRiskCosts,
} from '@/api/trading-research'
import DailyOptionsHistory from '@/components/strategy/DailyOptionsHistory'
import QualificationPanel from '@/components/strategy/QualificationPanel'
import {
  ResearchMLResults,
  ResearchSearchResults,
} from '@/components/strategy/ResearchExperimentResults'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import type {
  CostSchedule,
  MLSettings,
  ResearchCandidateId,
  ResearchMetrics,
  ResearchRun,
  ResearchRunKind,
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
  ['exchange_rate', 'Exchange fee (%)', 'number'],
  ['sebi_rate', 'SEBI fee (%)', 'number'],
  ['gst_rate', 'GST (%)', 'number'],
  ['stamp_buy_rate', 'Stamp duty on buy (%)', 'number'],
  ['stt_sell_rate', 'STT on sell (%)', 'number'],
  ['slippage_bps', 'Slippage (basis points)', 'number'],
] as const

const percentCosts = new Set([
  'exchange_rate',
  'sebi_rate',
  'gst_rate',
  'stamp_buy_rate',
  'stt_sell_rate',
])
const percentParameters = new Set(['stop_pct', 'target_pct', 'pullback_tolerance'])
const commonCostFields = new Set(['effective_from', 'effective_to', 'slippage_bps'])
// Published rates checked on this date; not a historical rate table.
const kotakVerifiedOn = '2026-09-26'
const kotakNseDraft = {
  schedule_id: 'Kotak Neo API - NSE options',
  source:
    'Verified 2026-09-26: https://www.kotakneo.com/support/what-is-the-brokerage-for-using-neo-trade-api/ ; https://www.kotakneo.com/calculator/brokerage-calculator/ . Trade Free API plan, NSE options; exchange includes IPFT. Slippage is an estimate.',
  broker: 'kotak',
  exchange: 'NFO',
  brokerage_per_order: '0',
  exchange_rate: '0.03553',
  sebi_rate: '0.0001',
  gst_rate: '18',
  stamp_buy_rate: '0.003',
  stt_sell_rate: '0.15',
  slippage_bps: '10',
}

const marketLabels = { NFO: 'NSE options', BFO: 'BSE SENSEX / BANKEX options', MCX: 'MCX options' }
const kotakDrafts = {
  NFO: { ...kotakNseDraft, effective_from: kotakVerifiedOn },
  BFO: {
    ...kotakNseDraft, exchange: 'BFO', schedule_id: 'Kotak Neo API - BSE SENSEX / BANKEX options',
    effective_from: '2026-09-28', exchange_rate: '0.0325',
    source: 'Checked 2026-09-28: https://www.kotakneo.com/support/what-is-the-brokerage-for-using-neo-trade-api/ ; https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/exchange-transaction-charges ; https://groww.in/pricing/futures-and-options . Indicative SENSEX/BANKEX rates; 0 API brokerage assumes Trade Free plan. Slippage is estimated.',
  },
  MCX: {
    ...kotakNseDraft, exchange: 'MCX', schedule_id: 'Kotak Neo API - MCX options',
    effective_from: '2026-09-28', exchange_rate: '0.0418', stt_sell_rate: '0.05',
    source: 'Checked 2026-09-28: https://www.kotakneo.com/support/what-is-the-brokerage-for-using-neo-trade-api/ ; https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/exchange-transaction-charges ; https://groww.in/pricing/futures-and-options . Indicative MCX option rates; sell tax is CTT. 0 API brokerage assumes Trade Free plan. Slippage is estimated.',
  },
}

const kindLabels: Record<ResearchRunKind, string> = {
  development: 'Development',
  optimization: 'Parameter search',
  ml: 'RandomForest research',
  final: 'Final holdout',
}

const parameterLabels: Record<string, string> = {
  lookback: 'Lookback bars',
  stop_pct: 'Stop-loss distance (%)',
  target_pct: 'Target distance (%)',
  volume_ratio: 'Volume ratio',
  pullback_tolerance: 'VWAP pullback tolerance (%)',
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
  const [allocationReason, setAllocationReason] = useState('')
  const mode = name === 'Sandbox' ? 'sandbox' : 'live'
  const resumed = useMutation({
    mutationFn: resumeTradingRisk,
    onSuccess: () => {
      setReason('')
      setReconciled(false)
      void queryClient.invalidateQueries({ queryKey: researchKeys.risk })
    },
  })
  const allocation = useMutation({
    mutationFn: reviewRiskAllocation,
    onSuccess: () => {
      setAllocationReason('')
      void queryClient.invalidateQueries({ queryKey: researchKeys.risk })
    },
  })
  return (
    <section aria-label={`${name} risk budget`} className="rounded-lg border p-4 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-medium">{name}</h3>
        <Badge variant={enabled && (account?.paused || account?.daily_stopped) ? 'destructive' : 'outline'}>
          {!enabled
            ? 'Profile inactive'
            : account
              ? account.daily_stopped
                ? 'Day blocked'
                : account.paused
                  ? 'Entries paused'
                  : 'Budget monitored'
              : 'Unavailable'}
        </Badge>
      </div>
      <dl className="grid grid-cols-2 gap-4">
        <Metric label="Reviewed capital allocation" value={money(account?.capital)} />
        {account?.policy_version === 'two-bucket-v1' ? <>
          <Metric label="Legacy first filled trade remaining" value={money(account.first_remaining)} />
          <Metric label="Legacy later trades remaining" value={money(account.later_remaining)} />
        </> : <>
          <Metric label={account?.policy_version === "equity-1pct-v2" ? "Maximum planned loss incl. costs" : "Per-trade price-stop limit"} value={money(account?.per_trade_limit)} />
          <Metric label="Consecutive completed losses" value={number(account?.consecutive_losses)} />
        </>}
        <Metric label="Daily remaining" value={money(account?.daily_remaining)} />
        {account?.daily_limit !== undefined && <Metric label="Session loss allowance" value={money(account.daily_limit)} />}
        <Metric label="Drawdown headroom" value={money(account?.drawdown_headroom)} />
        <Metric label="Equity" value={money(account?.equity)} />
        <Metric label="Reserved risk" value={money(account?.reserved_risk)} />
      </dl>
      {account?.daily_stop_reason && <p className="text-sm text-destructive">
        {account.daily_stop_reason === 'three_consecutive_losses'
          ? 'Three consecutive completed net losses: new entries are blocked for this trading day. Protective exits remain active.'
          : account.daily_stop_reason}
      </p>}
      {account?.policy_transition_blocked && <p className="text-sm text-destructive">{account.policy_transition_blocked}</p>}
      {account?.risk_reduced && <p className="text-sm text-destructive">Risk per trade is halved because drawdown has reached 5% of peak equity.</p>}
      {account?.pause_reason && <p className="text-sm text-destructive">{account.pause_reason}</p>}
      <p className="text-xs text-muted-foreground">
        {account
          ? `Session ${account.session_day} · Peak equity ${money(account.peak_equity)}`
          : 'No risk ledger evidence is available for this mode yet.'}
      </p>
      {enabled && account && (account.capital !== 25000 || mode === 'sandbox') && (
        <div className="space-y-3 border-t pt-4">
          <p className="text-sm">Change this mode’s capital only while its positions are closed. Loss history and daily stops are preserved. Fixed loss limits do not increase with capital.</p>
          <p className="text-xs text-muted-foreground">Frozen ML deployment and qualification currently require ₹25,000. A ₹50,000 sandbox allocation is available for the rule-based strategies; it does not qualify those ML models for trading.</p>
          <Label htmlFor={`allocation-reason-${mode}`}>Allocation review reason</Label>
          <Textarea id={`allocation-reason-${mode}`} value={allocationReason}
            onChange={(event) => setAllocationReason(event.target.value)} />
          <Button variant="outline" size="sm"
            disabled={account.capital === 25000 || allocationReason.trim().length < 3 || allocation.isPending}
            onClick={() => allocation.mutate({ mode, capital: 25000, reason: allocationReason.trim() })}>
            {allocation.isPending ? 'Recording allocation…' : 'Review ₹25,000 allocation'}
          </Button>
          {mode === 'sandbox' && (
            <Button type="button" variant="outline" size="sm"
              disabled={account.capital === 50000 || allocationReason.trim().length < 3 || allocation.isPending}
              onClick={() => allocation.mutate({ mode, capital: 50000, reason: allocationReason.trim() })}>
              {allocation.isPending ? 'Recording allocation…' : 'Set sandbox capital to ₹50,000'}
            </Button>
          )}
          {allocation.error && <p role="alert" className="text-sm text-destructive">{allocation.error.message}</p>}
        </div>
      )}
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
    <div className="space-y-3">
      {metrics.execution_bar_minutes !== undefined && (
        <p className="text-sm text-muted-foreground">
          {metrics.signal_bar_minutes}-minute signals · {metrics.execution_bar_minutes}-minute
          execution
        </p>
      )}
      {!!metrics.ambiguous_exit_count && (
        <p className="text-sm text-amber-600 dark:text-amber-400">
          {metrics.ambiguous_exit_count} exits have unknown within-candle order. Protective exits
          are assumed first; these results do not establish the actual sequence.
        </p>
      )}
      <dl className="grid grid-cols-2 gap-5 md:grid-cols-4">
        <Metric label="Research capital" value={money(metrics.initial_capital ?? 10000)} />
        <Metric label="Net P&L" value={money(metrics.net_pnl)} />
        <Metric label="Net expectancy / trade" value={money(metrics.expectancy)} />
        <Metric
          label="Profit factor"
          value={
            metrics.profit_factor_unbounded ? 'No losing trades' : number(metrics.profit_factor)
          }
        />
        <Metric label="Maximum drawdown" value={number(metrics.max_drawdown_pct, '%')} />
        <Metric label="Trades" value={number(metrics.trade_count)} />
        <Metric label="Win rate" value={number(metrics.win_rate, '%')} />
        <Metric label="Longest losing streak (across days)" value={number(metrics.max_losing_streak)} />
        <Metric label="Ending equity" value={money(metrics.ending_equity)} />
        <Metric label="Bars with exposure" value={number(metrics.exposure_bars)} />
        <Metric
          label="Observed open drawdown"
          value={number(metrics.max_observed_open_drawdown_pct, '%')}
        />
      </dl>
    </div>
  )
}

export default function Research() {
  const queryClient = useQueryClient()
  const [step, setStep] = useState('costs')
  const [file, setFile] = useState<File | null>(null)
  const [csvMetadata, setCsvMetadata] = useState('')
  const [csvName, setCsvName] = useState('')
  const [csvProvider, setCsvProvider] = useState('')
  const [datasetId, setDatasetId] = useState('')
  const [candidateId, setCandidateId] = useState<ResearchCandidateId>('trend_breakout')
  const [runKind, setRunKind] = useState<'development' | 'optimization' | 'ml'>('development')
  const [gridValues, setGridValues] = useState<Record<string, string>>({})
  const [mlSettings, setMlSettings] = useState<MLSettings>({
    folds: 3,
    min_train_sessions: 10,
    estimators: 200,
    threshold: 0.5,
    max_hold_minutes: 15,
  })
  const [parameters, setParameters] = useState<Record<string, string>>({})
  const [costEdits, setCostEdits] = useState<Record<string, string>>({})
  const [seed, setSeed] = useState('42')
  const [capital, setCapital] = useState('25000')
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
  const legacyModes = Object.entries(risk.data?.accounts ?? {})
    .filter(([, account]) => account?.policy_transition_blocked || (account && account.policy_version !== risk.data?.policy.version))
    .map(([mode]) => mode === 'sandbox' ? 'Sandbox' : 'Live')
  const transitionPending = legacyModes.length > 0
  const candidate = overview.data?.candidates.find((item) => item.id === candidateId)
  const selectedDataset = overview.data?.datasets.find((item) => item.id === Number(datasetId))
  const currentRun = detail.data
  const rawReport = currentRun?.report
  const searchReport = rawReport && 'best_report' in rawReport ? rawReport : undefined
  const report = rawReport && 'best_report' in rawReport ? rawReport.best_report : rawReport
  const gridCount = Object.values(gridValues)
    .filter((value) => value.trim())
    .reduce((count, value) => count * value.split(',').length, 1)
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

  const selectedCostExchange = (costEdits.exchange ?? risk.data?.costs?.exchange ?? '') as keyof typeof marketLabels | ''
  const savedMarketCosts = selectedCostExchange
    ? risk.data?.costs_by_exchange?.[selectedCostExchange]
      ?? (risk.data?.costs?.exchange === selectedCostExchange ? risk.data.costs : undefined)
    : risk.data?.costs
  const selectCostMarket = (exchange: string) => {
    setCostEdits({ exchange })
    setFormError(null)
    savedCosts.reset()
  }
  const draftMarket = selectedCostExchange || 'NFO'
  const costValue = (key: keyof CostSchedule) => {
    if (costEdits[key] !== undefined) return costEdits[key]
    const value = savedMarketCosts?.[key]
    if (value === undefined || value === null) return ''
    return String(percentCosts.has(key) ? Number((Number(value) * 100).toPrecision(12)) : value)
  }
  const readCosts = (): CostSchedule => {
    const result: Record<string, string | number> = {}
    for (const [key, label, type] of costFields) {
      const value = costValue(key).trim()
      if (!value)
        throw new Error(
          `Enter ${label.toLowerCase()}.${type === 'number' ? ' Missing costs cannot be treated as zero.' : ''}`
        )
      if (type === 'number') {
        const parsed = Number(value)
        if (!Number.isFinite(parsed) || parsed < 0)
          throw new Error(`${label} must be a non-negative number.`)
        if (percentCosts.has(key) && parsed > 100) throw new Error(`${label} cannot exceed 100%.`)
        result[key] = percentCosts.has(key) ? Number((parsed / 100).toPrecision(12)) : parsed
      } else {
        result[key] = value
      }
    }
    for (const key of ['exchange', 'broker'] as const) {
      const scope = costValue(key)
      if (scope) result[key] = scope
    }
    return result as unknown as CostSchedule
  }
  const costInput = ([key, label, type]: (typeof costFields)[number]) => (
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
  )

  const created = useMutation({
    mutationFn: createResearchRun,
    onSuccess: (run) => {
      setSelectedRun(run.id)
      setStep('results')
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
    mutationFn: ({
      id,
      verb,
    }: {
      id: number
      verb: 'freeze' | 'cancel' | 'final-test' | 'promote'
    }) => researchRunAction(id, verb),
    onSuccess: (run) => {
      setSelectedRun(run.id)
      setFinalOpen(false)
      setFinalConfirmed(false)
      void queryClient.invalidateQueries({ queryKey: researchKeys.run(run.id) })
      refresh()
    },
  })
  const installML = useMutation({
    mutationFn: installFrozenMLRun,
    onSuccess: () => {
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
        const value =
          parameters[key] ?? String(percentParameters.has(key) ? fallback * 100 : fallback)
        if (!value.trim() || !Number.isFinite(Number(value)))
          throw new Error(`Enter a valid ${parameterLabels[key] ?? key}.`)
        parsedParameters[key] = percentParameters.has(key) ? Number(value) / 100 : Number(value)
      }
      if (!seed.trim() || !Number.isSafeInteger(Number(seed)) || Number(seed) < 0)
        throw new Error('The reproducibility seed must be a non-negative whole number.')
      if (
        !capital.trim() ||
        !Number.isSafeInteger(Number(capital)) ||
        Number(capital) < 1 ||
        Number(capital) > 1000000000
      )
        throw new Error(
          'Enter research capital as a whole rupee amount between 1 and 1,000,000,000.'
        )
      const parameterGrid: Record<string, number[]> = {}
      if (runKind === 'optimization') {
        for (const [key, text] of Object.entries(gridValues)) {
          if (!text.trim()) continue
          const values = text.split(',').map((value) => {
            if (!value.trim() || !Number.isFinite(Number(value)))
              throw new Error('Enter comma-separated numbers for comparison.')
            return percentParameters.has(key) ? Number(value) / 100 : Number(value)
          })
          if (new Set(values).size !== values.length)
            throw new Error('Comparison values must be unique.')
          parameterGrid[key] = values
        }
        if (!Object.keys(parameterGrid).length || gridCount > 256)
          throw new Error('Choose between 1 and 256 parameter combinations.')
      }
      created.mutate({
        ...(runKind === 'optimization' ? { run_kind: runKind, parameter_grid: parameterGrid } : {}),
        ...(runKind === 'ml' ? { run_kind: runKind, ml_settings: mlSettings } : {}),
        dataset_id: Number(datasetId),
        candidate: candidateId,
        parameters: parsedParameters,
        costs: readCosts(),
        seed: Number(seed),
        capital: Number(capital),
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
          <h1 className="mt-1 text-2xl font-bold tracking-tight">Prepare your strategy</h1>
          <p className="text-sm text-muted-foreground max-w-2xl">
            Set your costs, test the rules, then review the results before using real money.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={workerOnline ? 'secondary' : 'outline'}>
            {overview.isPending
              ? 'Checking test service'
              : workerOnline
                ? 'Test service ready'
                : 'Test service offline'}
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
      <section className="rounded-xl border bg-card p-5 sm:p-6 space-y-4" aria-label="Setup status">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Your next step
            </p>
            <h2 className="mt-1 text-xl font-semibold">
              {risk.error
                ? 'Check your connection'
                : risk.isPending
                  ? 'Loading your setup…'
                  : !risk.data?.enabled
                    ? 'Set up your trading costs'
                    : transitionPending
                      ? 'Reconcile earlier risk policy'
                      : !overview.data?.datasets.length
                      ? 'Add history for your first test'
                      : 'Test and review your strategy'}
            </h2>
          </div>
          <Badge variant="outline">
            {risk.error
              ? 'Status unavailable'
              : risk.isPending
                ? 'Loading'
                : risk.data?.enabled
                  ? transitionPending ? 'Policy transition needed' : 'Shared limits enabled'
                  : 'Shared limits off'}
          </Badge>
        </div>
        <p className="max-w-3xl text-sm text-muted-foreground">
          {risk.data?.enabled
            ? transitionPending
              ? `Legacy policy still active: ${legacyModes.join(', ')}. Reconcile its recorded exposure and completion evidence before transition. Current fixed limits apply only to upgraded modes. Live trading still requires qualification and session authorization.`
              : 'Your managed strategy entries share these limits. Live trading still needs a qualified strategy, review and session authorization.'
            : 'Your existing flows keep their current rules. Complete step 1 to apply these shared limits to managed Strategy Module entries. Saving this setup does not start trading.'}
        </p>
        {risk.error && (
          <p role="alert" className="text-sm text-destructive">
            Risk evidence is unavailable. {risk.error.message}
          </p>
        )}
        {risk.data && (
          <dl className="grid grid-cols-2 gap-4 border-t pt-4 lg:grid-cols-5">
            <Metric label="Sandbox allocation" value={money(risk.data.accounts.sandbox?.capital)} />
            <Metric label="Live allocation" value={money(risk.data.accounts.live?.capital)} />
            <Metric
              label={risk.data.policy.version === 'fixed-300-v3'
                ? 'Planned price-stop limit before charges'
                : 'Planned per-trade limit incl. costs'}
              value={money(risk.data.policy.per_trade_limit)}
            />
            <Metric
              label="Profit objective"
              value="₹900–₹1,500+ gross"
            />
            <Metric label="Daily entry loss limit incl. costs" value={money(risk.data.policy.daily_limit)} />
          </dl>
        )}
        <p className="text-xs text-muted-foreground">
          Fixed ₹300 planned price-stop loss per trade, with charges and slippage accounted for
          separately. The ₹2,000 daily loss limit includes costs and does not depend on capital.
          One open position across managed strategies. Profits do not refill the allowance.
          Three consecutive net losses stop entries for the day; the 8% portfolio drawdown pause remains.
          New entries keep the technical stop or are skipped.
          Kotak stop advances are verified against broker evidence. Market gaps can exceed a planned stop.
        </p>
        {risk.data && (risk.data.accounts.sandbox?.paused || risk.data.accounts.live?.paused) && (
          <p role="alert" className="text-sm text-destructive">
            A trading budget is paused. Open Costs &amp; limits to review it before resuming.
          </p>
        )}
      </section>

      <Tabs
        value={step}
        onValueChange={(value) => {
          setStep(value)
          setFormError(null)
        }}
        className="gap-5"
      >
        <TabsList
          aria-label="Strategy preparation steps"
          className="grid h-auto w-full grid-cols-2 gap-1 p-1 sm:grid-cols-4"
        >
          <TabsTrigger value="costs" className="py-3">
            1. Costs &amp; limits
          </TabsTrigger>
          <TabsTrigger value="history" className="py-3">
            2. Historical test
          </TabsTrigger>
          <TabsTrigger value="results" className="py-3">
            3. Results
          </TabsTrigger>
          <TabsTrigger value="qualification" className="py-3">
            4. Sandbox &amp; live
          </TabsTrigger>
        </TabsList>
        <TabsContent value="costs" className="space-y-5">
          <Card>
            <CardContent className="pt-6">
              {' '}
              <div className="space-y-4">
                <h3 className="font-semibold text-lg">Broker fees and execution costs</h3>
                {risk.data?.enabled && !risk.data.costs && (
                  <p className="text-sm text-destructive">
                    Entry risk is blocked until a complete, dated cost schedule is saved.
                  </p>
                )}
                <div className="space-y-2">
                  <Label htmlFor="saved-market-schedule">Saved market schedule</Label>
                  <select id="saved-market-schedule" className={selectClass}
                    value={selectedCostExchange} onChange={(event) => selectCostMarket(event.target.value)}>
                    <option value="">Custom / unscoped</option>
                    {Object.entries(marketLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                  <p className="text-xs text-muted-foreground">
                    Each market saves separately. Saving BSE or MCX fees keeps your NSE schedule unchanged.
                    {selectedCostExchange && !savedMarketCosts && ' No saved schedule for this market. Load its rates or enter verified fees below.'}
                  </p>
                </div>
                <div className="rounded-lg border bg-muted/30 p-4 space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-medium">Kotak Neo API · {marketLabels[draftMarket]}</p>
                      <p className="text-sm text-muted-foreground">
                        ₹0 API brokerage on Trade Free plans. Taxes and exchange fees still apply.
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      onClick={() => {
                        setCostEdits({
                          ...kotakDrafts[draftMarket],
                          effective_to:
                            costValue('effective_to') >= kotakDrafts[draftMarket].effective_from
                              ? costValue('effective_to')
                              : '',
                        })
                        setFormError(null)
                        savedCosts.reset()
                      }}
                    >
                      Use Kotak Neo rates
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    API brokerage from Kotak’s{' '}
                    <a
                      className="underline"
                      href="https://www.kotakneo.com/support/what-is-the-brokerage-for-using-neo-trade-api/"
                      target="_blank"
                      rel="noreferrer"
                    >
                      API pricing
                    </a>{' '}
                    and{' '}
                    <a
                      className="underline"
                      href="https://www.kotakneo.com/calculator/brokerage-calculator/"
                      target="_blank"
                      rel="noreferrer"
                    >
                      charge calculator
                    </a>
                    . BSE/MCX exchange rates are cross-checked against{' '}
                    <a className="underline" href="https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/exchange-transaction-charges" target="_blank" rel="noreferrer">published exchange charges</a>{' '}
                    and <a className="underline" href="https://groww.in/pricing/futures-and-options" target="_blank" rel="noreferrer">statutory rates</a>.
                    These are editable planning assumptions, not reconciled broker charges. BSE rates cover SENSEX/BANKEX. MCX sell tax is CTT.
                  </p>
                </div>
                <p className="text-sm">
                  {costValue('schedule_id')
                    ? `Selected: ${costValue('schedule_id')}`
                    : 'Choose Kotak rates above, or enter a custom schedule below.'}
                  {costValue('exchange') &&
                    ` · ${costValue('exchange')} · ${costValue('broker') || 'Custom broker'}`}
                </p>
                <div className="grid gap-3 sm:grid-cols-3">
                  {costFields.filter(([key]) => commonCostFields.has(key)).map(costInput)}
                </div>
                <p className="text-xs text-muted-foreground">
                  Dates must cover every trading or historical-test session. The preset does not
                  verify older rates or future changes. Slippage is a planning estimate: 10 basis
                  points means a 0.10% worse fill on each side.
                </p>
                <details className="rounded-lg border p-4">
                  <summary className="cursor-pointer font-medium">Edit fee details</summary>
                  <div className="grid gap-3 pt-4 sm:grid-cols-2">
                    <p className="text-xs text-muted-foreground sm:col-span-2">
                      Enter percentages as you read them: 18 means 18%. Custom rates must match the
                      selected market and broker.
                    </p>
                    {(['exchange', 'broker'] as const).map((key) => (
                      <div className="space-y-2" key={key}>
                        <Label htmlFor={`cost-${key}`}>
                          {key === 'exchange' ? 'Market scope' : 'Broker scope'}
                        </Label>
                        <select
                          id={`cost-${key}`}
                          className={selectClass}
                          value={costValue(key)}
                          onChange={(event) => {
                            if (key === 'exchange') selectCostMarket(event.target.value)
                            else setCostEdits((previous) => ({ ...previous, [key]: event.target.value }))
                            savedCosts.reset()
                          }}
                        >
                          <option value="">Custom / unscoped</option>
                          {key === 'exchange' ? (
                            <>
                              <option value="NFO">NSE options</option>
                              <option value="BFO">BSE options</option>
                              <option value="MCX">MCX options</option>
                            </>
                          ) : (
                            <option value="kotak">Kotak Neo API</option>
                          )}
                        </select>
                      </div>
                    ))}
                    {costFields.filter(([key]) => !commonCostFields.has(key)).map(costInput)}
                  </div>
                </details>
                {formError && (
                  <p role="alert" className="text-sm text-destructive">
                    {formError}
                  </p>
                )}
                <p id="capital-profile-effect" className="text-sm text-muted-foreground">
                  {risk.data?.enabled
                    ? 'Updating costs keeps this capital profile enabled.'
                    : `Saving costs enables the shared long-options capital profile. Each mode starts at ${money(risk.data?.policy.capital)} until its allocation is reviewed.`}{' '}
                  It applies to your managed Strategy Module entries, restricts them to supported
                  long-option trades, and requires release qualification for new managed live
                  entries. Running a research test alone does not enable the profile.
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
            </CardContent>
          </Card>
          {risk.data && (
            <details
              className="rounded-xl border p-5"
              open={
                risk.data.accounts.sandbox?.paused || risk.data.accounts.live?.paused || undefined
              }
            >
              <summary className="cursor-pointer font-medium">
                View budget details and pause rules
              </summary>
              <p className="py-4 text-sm text-muted-foreground">
                A {number(risk.data.policy.drawdown_pct * 100, '%')} fall from peak allocated equity
                pauses new entries across days. A{' '}
                {number(risk.data.policy.cash_buffer_pct * 100, '%')} cash buffer stays uncommitted.
                The fixed price-stop loss limit is ₹300 per trade, independent of capital.
                Charges and slippage are reserved separately and count toward the fixed ₹2,000
                daily loss limit; wins do not refill it.
                Three consecutive completed net losses block entries for the rest of the trading day.
                Protective exits continue. These limits cover managed Strategy Module entries only.
              </p>
              <div className="grid gap-4 lg:grid-cols-2">
                <Budget
                  name="Sandbox"
                  account={risk.data.accounts.sandbox}
                  enabled={risk.data.enabled}
                />
                <Budget name="Live" account={risk.data.accounts.live} enabled={risk.data.enabled} />
              </div>
            </details>
          )}
          <div className="flex justify-end">
            <Button variant="outline" onClick={() => setStep('history')}>
              Next: historical test
            </Button>
          </div>
        </TabsContent>
        <TabsContent value="history" className="space-y-5">
          <DailyOptionsHistory />
          <p className="text-sm text-muted-foreground">
            {overview.data?.datasets.length
              ? 'Choose imported history and a rule set. This test uses historical prices and sends no broker orders.'
              : 'Add market history to run your first test.'}{' '}
            Your broker connection does not automatically supply historical option data here.
          </p>
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
            <Card>
              <CardHeader>
                <CardTitle>Add intraday market history</CardTitle>
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
                    JSON bundle or CSV, up to 20 MB including metadata. At least 80 sessions are
                    needed: 60 remain sealed for final evaluation.
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
                      Each row is an underlying or option candle. Use timezone-aware timestamps such
                      as 2026-01-05T09:20:00+05:30, with bar-close time. Do not include future bars.
                    </p>
                    <p>
                      VWAP requires observed underlying volume and an explicit session_open in
                      HH:MM, verified against your source. No opening time is assumed. Every session
                      must start with the underlying close at session_open plus bar_minutes. For a
                      verified 09:15 opening and five-minute bars, that first close is 09:20.
                      Missing opening bars make the history unsuitable for session VWAP. Trend tests
                      may omit session_open.
                    </p>
                    <p>
                      Metadata must provide the underlying, source reference, Asia/Kolkata timezone,
                      bar interval, session close and point-in-time contracts: symbol, underlying,
                      exchange, CE/PE, strike, expiry, lot size, multiplier and index/mcx segment.
                      Verify these values against the source; the template contains placeholders and
                      no prices.
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
                    <p className="break-all font-mono">
                      Fingerprint: {selectedDataset.content_hash}
                    </p>
                    <p>
                      Candle screening only. Quotes, spreads and actual fills are not established by
                      candles.
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Choose an intraday dataset to run a strategy test. Daily NSE history above is
                    for market context.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Choose the trading rules</CardTitle>
                <CardDescription>
                  Signals use closed underlying bars. Option executions occur on a subsequent bar,
                  with whole-lot sizing and the configured risk budget.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="space-y-2">
                  <Label htmlFor="research-capital">Research capital (₹)</Label>
                  <Input
                    id="research-capital"
                    type="number"
                    min="1"
                    max="1000000000"
                    step="1"
                    value={capital}
                    onChange={(event) => setCapital(event.target.value)}
                  />
                  <p className="text-sm text-muted-foreground">
                    New experiments start at ₹25,000. This amount sets whole-lot affordability and
                    an 8% portfolio drawdown pause. One option lot must fit a ₹300 price-stop loss.
                    Charges and slippage are separate and count toward the fixed ₹2,000 daily loss
                    limit, with a 20% cash buffer. Profit has no fixed ceiling. Planned risk is not
                    a guarantee of realized loss.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="research-kind">Test type</Label>
                  <select
                    id="research-kind"
                    className={selectClass}
                    value={runKind}
                    onChange={(event) => {
                      const kind = event.target.value as typeof runKind
                      setRunKind(kind)
                      setGridValues({})
                      if (kind === 'ml') {
                        setCandidateId('trend_breakout_filtered')
                        setParameters({})
                      }
                    }}
                  >
                    <option value="development">Test one rule set</option>
                    <option value="optimization">Compare parameter values</option>
                    <option value="ml">Train a RandomForest model</option>
                  </select>
                  {runKind === 'optimization' && (
                    <p className="text-sm text-muted-foreground">
                      Enter values to compare below; leave a comparison blank to keep its fixed
                      value. Ranking uses development net profit after costs, then drawdown. The
                      final 60 sessions stay sealed.
                    </p>
                  )}
                  {runKind === 'ml' && (
                    <div className="space-y-3 rounded-lg border p-3">
                      <p className="text-sm">
                        Research only: predicts whether an eligible option trade will be profitable
                        after costs. Uses chronological training folds, then a later evaluation
                        period. This does not enable ML trading.
                      </p>
                      {!overview.data?.capabilities?.ml.available && (
                        <p role="alert" className="text-sm">
                          {overview.data?.capabilities?.ml.reason ??
                            'ML availability is not confirmed. Refresh after installing the research dependencies on the server.'}
                        </p>
                      )}
                      <div className="grid gap-3 sm:grid-cols-2">
                        {(
                          [
                            ['folds', 'Chronological folds', 2, 10, 1],
                            ['min_train_sessions', 'Minimum training sessions', 10, 10000, 1],
                            ['estimators', 'Trees', 50, 500, 1],
                            ['threshold', 'Minimum predicted probability', 0, 1, 0.05],
                            ['max_hold_minutes', 'Maximum holding time (minutes)', 5, 15, 5],
                          ] as const
                        ).map(([key, label, min, max, step]) => (
                          <div key={key}>
                            <Label htmlFor={`ml-${key}`}>{label}</Label>
                            <Input
                              id={`ml-${key}`}
                              type="number"
                              min={min}
                              max={max}
                              step={step}
                              value={mlSettings[key]}
                              onChange={(event) =>
                                setMlSettings((previous) => ({
                                  ...previous,
                                  [key]: Number(event.target.value),
                                }))
                              }
                            />
                          </div>
                        ))}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Requires one-minute option history with tick sizes. Uses the filtered
                        execution rules and one whole lot with its technical stop. Trades exceeding the equity-based
                        all-in risk budget are skipped. The rising profit stop has no hard profit cap. Labels and
                        replay exits share the selected 5, 10 or 15-minute limit. Training balances
                        sessions and reduces the weight of overlapping trades.
                      </p>
                    </div>
                  )}
                  <Label htmlFor="research-candidate">Candidate rules</Label>
                  <select
                    id="research-candidate"
                    disabled={runKind === 'ml'}
                    value={candidateId}
                    onChange={(event) => {
                      setCandidateId(event.target.value as ResearchCandidateId)
                      setParameters({})
                      setGridValues({})
                    }}
                    className={selectClass}
                  >
                    {overview.data?.candidates.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                  {runKind !== 'ml' && (
                    <p className="text-sm text-muted-foreground">{candidate?.description}</p>
                  )}
                  {runKind !== 'ml' && candidateId === 'trend_breakout_filtered' && (
                    <p className="text-sm text-muted-foreground">
                      Uses 8/21-bar prior trend, 1–7 days to expiry, observed liquidity and
                      whole-lot affordability. One lot per entry, a 5-minute post-exit cooldown and a
                      15-minute maximum holding time. Three consecutive net losses stop new entries for the day.
                      Requires one-minute option bars and contract tick sizes. Technical stops are rounded away
                      from entry; entries that exceed the all-in risk budget are skipped. Profit protection starts
                      at ₹300 gross by protecting ₹100. At ₹600, protect ₹300; at ₹900, protect ₹600.
                      The stop rises continuously with at most ₹300 giveback from peak executable profit.
                      At ₹1,500, protect ₹1,200. Profit can keep growing without a fixed cap, before charges,
                      within the holding deadline. Stop fills can slip past these levels.
                    </p>
                  )}
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {Object.entries(candidate?.defaults ?? {})
                    .filter(([key]) => runKind !== 'ml' && key !== 'target_pct')
                    .filter(
                      ([key]) =>
                        candidateId === 'vwap_pullback' ||
                        !['volume_ratio', 'pullback_tolerance'].includes(key)
                    )
                    .map(([key, fallback]) => (
                      <div className="space-y-2" key={key}>
                        <Label htmlFor={`parameter-${key}`}>{parameterLabels[key] ?? key}</Label>
                        <Input
                          id={`parameter-${key}`}
                          disabled={runKind === 'ml' || key === 'target_pct'}
                          type="number"
                          step="any"
                          value={
                            parameters[key] ??
                            String(percentParameters.has(key) ? fallback * 100 : fallback)
                          }
                          onChange={(event) =>
                            setParameters((previous) => ({
                              ...previous,
                              [key]: event.target.value,
                              ...(key === 'stop_pct' ? { target_pct: String(Number((Number(event.target.value) * 3).toFixed(10))) } : {}),
                            }))
                          }
                        />
                        {runKind === 'optimization' && !['stop_pct', 'target_pct'].includes(key) && (
                          <>
                            <Label htmlFor={`grid-${key}`}>
                              {parameterLabels[key] ?? key} — values to compare
                            </Label>
                            <Input
                              id={`grid-${key}`}
                              placeholder="e.g. 10, 15, 20"
                              value={gridValues[key] ?? ''}
                              onChange={(event) =>
                                setGridValues((previous) => ({
                                  ...previous,
                                  [key]: event.target.value,
                                }))
                              }
                            />
                          </>
                        )}
                      </div>
                    ))}
                  <details className="space-y-2">
                    <summary className="cursor-pointer text-sm">Advanced test settings</summary>
                    <Label htmlFor="research-seed">Reproducibility seed</Label>
                    <Input
                      id="research-seed"
                      type="number"
                      min="0"
                      step="1"
                      value={seed}
                      onChange={(event) => setSeed(event.target.value)}
                    />
                  </details>
                </div>
                {runKind === 'optimization' && (
                  <p className="text-sm">{gridCount} combinations · maximum 256</p>
                )}
                <p className="text-sm text-muted-foreground">
                  This test uses the costs from step 1.{' '}
                  <button
                    type="button"
                    className="underline underline-offset-4"
                    onClick={() => setStep('costs')}
                  >
                    Review costs
                  </button>
                </p>
                <div className="border-t pt-4 space-y-3">
                  <p className="text-xs text-muted-foreground">
                    {runKind === 'ml'
                      ? 'The final 60 sessions stay sealed. Freeze the fitted JSON model, then score the final sessions once without refitting. Installation and forward trading require separate reviews.'
                      : 'Development tests cannot view the final 60 sessions. Freeze a completed version before consuming that holdout once.'}{' '}
                    Historical returns do not establish future profitability.
                  </p>
                  {!workerOnline && !overview.isPending && (
                    <p className="text-sm text-muted-foreground">
                      The research worker is offline. Start it on the server before running
                      experiments.
                    </p>
                  )}
                  <Button
                    disabled={
                      !workerOnline ||
                      !datasetId ||
                      !candidate ||
                      created.isPending ||
                      (runKind === 'optimization' && gridCount > 256) ||
                      (runKind === 'ml' && !overview.data?.capabilities?.ml.available)
                    }
                    onClick={submitRun}
                  >
                    {created.isPending
                      ? 'Queuing…'
                      : runKind === 'optimization'
                        ? 'Compare parameters'
                        : runKind === 'ml'
                          ? 'Train and evaluate ML'
                          : 'Run development test'}
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
        </TabsContent>
        <TabsContent value="results">
          <Card>
            <CardHeader>
              <CardTitle>Review your test results</CardTitle>
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
                            {overview.data.candidates.find((item) => item.id === run.candidate)
                              ?.name ?? run.candidate}
                          </TableCell>
                          <TableCell>{kindLabels[run.kind]}</TableCell>
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
                        Run #{currentRun.id} · {kindLabels[currentRun.kind]}
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
                      {currentRun.kind === 'optimization' && currentRun.status === 'completed' && (
                        <Button
                          size="sm"
                          disabled={!workerOnline || action.isPending}
                          onClick={() => action.mutate({ id: currentRun.id, verb: 'promote' })}
                        >
                          Test selected parameters
                        </Button>
                      )}
                      {(currentRun.kind === 'development' || currentRun.kind === 'ml') &&
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
                      {(currentRun.kind === 'development' || currentRun.kind === 'ml') && currentRun.frozen_at && (
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
                      {currentRun.kind === 'final' && currentRun.status === 'completed' && report?.ml && (
                        <Button size="sm" variant="outline" disabled={installML.isPending}
                          onClick={() => installML.mutate(currentRun.id)}>
                          {installML.isPending ? 'Installing…' : 'Install stopped ML strategy and Flow'}
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
                  {installML.error && <p role="alert" className="text-sm text-destructive">{installML.error.message}</p>}
                  {installML.data && <p role="status" className="text-sm">Strategy #{installML.data.strategy_id} and Flow #{installML.data.workflow_id} are linked. Review their current state before Sandbox enrollment.</p>}
                  {searchReport && <ResearchSearchResults report={searchReport} />}
                  {report?.ml && <ResearchMLResults report={report.ml} />}
                  {report ? (
                    <>
                      <h4 className="font-medium">
                        {currentRun.kind === 'final'
                          ? 'Final holdout evidence'
                          : currentRun.kind === 'ml'
                            ? 'ML evaluation after training'
                            : searchReport
                              ? 'Selected candidate training evidence'
                              : 'Development training evidence'}
                      </h4>
                      <Metrics metrics={report.metrics} />
                      {report.session_analytics && (
                        <details className="space-y-2">
                          <summary className="cursor-pointer text-sm">
                            Session risk and return metrics
                          </summary>
                          <p className="text-xs text-muted-foreground">
                            {report.session_analytics.convention}
                          </p>
                          <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
                            <Metric
                              label="Annualized return"
                              value={number(
                                report.session_analytics.metrics.cagr == null
                                  ? null
                                  : report.session_analytics.metrics.cagr * 100,
                                '%'
                              )}
                            />
                            <Metric
                              label="Annualized volatility"
                              value={number(
                                report.session_analytics.metrics.volatility == null
                                  ? null
                                  : report.session_analytics.metrics.volatility * 100,
                                '%'
                              )}
                            />
                            <Metric
                              label="Sharpe"
                              value={number(report.session_analytics.metrics.sharpe)}
                            />
                            <Metric
                              label="Sortino"
                              value={number(report.session_analytics.metrics.sortino)}
                            />
                          </dl>
                        </details>
                      )}
                      <div className="rounded-lg border bg-muted/30 p-4 space-y-2">
                        <h4 className="font-medium">Qualification: research only</h4>
                        <ul className="list-disc pl-5 text-sm text-muted-foreground">
                          {report.qualification.reasons.map((reason) => (
                            <li key={reason}>{reason}</li>
                          ))}
                        </ul>
                      </div>
                      {report.oos && currentRun.kind !== 'ml' && (
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
                            {currentRun.kind !== 'final' ? (
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
                          <p className="text-xs text-muted-foreground">
                            {report.bootstrap.warning}
                          </p>
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
                              These are the exact inputs saved for this run. Editing the experiment
                              form does not change this evidence. Fee rates below are percentages.
                            </p>
                            <dl className="grid grid-cols-2 gap-4">
                              <Metric label="Seed" value={String(currentRun.configuration.seed)} />
                              <Metric
                                label="Research capital"
                                value={money(currentRun.configuration.capital ?? 10000)}
                              />
                              {currentRun.configuration.ml_settings && (
                                <>
                                  <Metric
                                    label="ML maximum holding time"
                                    value={`${currentRun.configuration.ml_settings.max_hold_minutes ?? 'Legacy session close'} minutes`}
                                  />
                                  <Metric
                                    label="ML trees"
                                    value={String(currentRun.configuration.ml_settings.estimators)}
                                  />
                                  <Metric
                                    label="ML probability threshold"
                                    value={String(currentRun.configuration.ml_settings.threshold)}
                                  />
                                  <Metric
                                    label="ML chronological folds"
                                    value={String(currentRun.configuration.ml_settings.folds)}
                                  />
                                  <Metric
                                    label="ML minimum training sessions"
                                    value={String(
                                      currentRun.configuration.ml_settings.min_train_sessions
                                    )}
                                  />
                                </>
                              )}
                              {Object.entries(currentRun.configuration.parameters).map(
                                ([key, value]) => (
                                  <Metric
                                    key={key}
                                    label={parameterLabels[key] ?? key}
                                    value={String(percentParameters.has(key) ? value * 100 : value)}
                                  />
                                )
                              )}
                              {costFields.map(([key, label]) => (
                                <div className="space-y-1 min-w-0" key={key}>
                                  <dt className="text-xs text-muted-foreground">{label}</dt>
                                  <dd className="break-words">
                                    {String(
                                      percentCosts.has(key)
                                        ? Number(
                                            (
                                              Number(currentRun.configuration!.costs[key]) * 100
                                            ).toPrecision(12)
                                          )
                                        : currentRun.configuration!.costs[key]
                                    )}
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
        </TabsContent>
        <TabsContent value="qualification">
          <div className="mb-5 rounded-lg border p-4 space-y-3">
            <h3 className="font-medium">Where automated trading runs</h3>
            <p className="text-sm text-muted-foreground">
              Manage your saved strategies and their linked Flows from Strategies. An enabled Flow
              watches its rules and sends an entry only when its signal and risk checks pass. The
              engine manages stops, targets and scheduled exits.
            </p>
            <p className="text-sm text-muted-foreground">
              Each Flow has an explicit Sandbox or Live mode. The top navigation’s Live Mode label
              does not change a Sandbox Flow into a live one. Live entries also require a connected
              broker, a qualified release and today’s live authorization.
            </p>
            <Button variant="outline" asChild>
              <Link to="/strategy">Open trading controls</Link>
            </Button>
          </div>
          <p className="mb-5 text-sm text-muted-foreground">
            Use a completed final test to begin a Sandbox trial of your saved strategy. Sandbox uses
            simulated money. Live approval is a separate review after enough evidence has been
            collected.
          </p>
          <QualificationPanel runs={overview.data?.runs ?? []} />
        </TabsContent>
      </Tabs>

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
