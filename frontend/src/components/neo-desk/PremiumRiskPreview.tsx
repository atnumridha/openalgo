import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { OptionData } from '@/types/option-chain'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { optionRiskApi, type OptionRiskRequest } from './optionRiskApi'
import { previewLevels } from './optionQuality'
import { ChartToolPanel } from './ChartToolDock'

export interface PremiumPlan {
  entry: number
  stop: number
  target: number
}
const currency = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
})
const cash = (value: string | number) => currency.format(Number(value))
type Stop = { price: number | null | undefined; source: string }
function InlineRisk({children}:{children:ReactNode;floating?:boolean;label:string;title:ReactNode}){return <>{children}</>}

/** A planning calculator: levels freeze once seeded, until the user edits or resets. */
export function PremiumRiskPreview({
  symbol,
  exchange,
  contract,
  price,
  stops,
  ready,
  onLevels,
  docked = false,
  lockedPlan,
  embedded = false,
  entryLabel,
}: {
  symbol: string
  exchange: string
  contract?: OptionData
  price: number
  stops: Stop[]
  ready: boolean
  onLevels: (plan: PremiumPlan | null) => void
  docked?: boolean
  lockedPlan?: PremiumPlan
  embedded?: boolean
  entryLabel?: string
}) {
  const username = useAuthStore((state) => state.user?.username)
  const mode = useThemeStore((state) => state.appMode)
  const feeDay = new Date(Date.now() + 19800000).toISOString().slice(0, 10)
  const tick = contract?.tick_size ?? 0
  const exact = !!contract && contract.symbol === symbol && contract.lotsize > 0 && tick > 0
  const defaults = lockedPlan ? {...lockedPlan,source:'Confirmed structure + ATR 14'} : previewLevels(
    contract?.ask && contract.ask > 0 ? contract.ask : price,
    tick,
    stops
  )
  const [entry, setEntry] = useState(''),
    [stop, setStop] = useState(''),
    [lots, setLots] = useState('1')
  const [slippage, setSlippage] = useState(''),
    [source, setSource] = useState(''),
    [show, setShow] = useState(true)
  const [entrySource, setEntrySource] = useState('')
  const initialized = useRef(false),
    touched = useRef(false)
  useEffect(() => {
    if (!ready || !exact || initialized.current || touched.current) return
    if (defaults.entry) {
      setEntry(defaults.entry.toFixed(2))
      setEntrySource(
        lockedPlan ? entryLabel ?? 'User provided entry' : contract?.ask && contract.ask > 0 ? 'Chain ask snapshot' : 'Last confirmed close'
      )
    }
    if (defaults.stop) {
      setStop(defaults.stop.toFixed(2))
      setSource(defaults.source ?? '')
      initialized.current = true
    }
    setSlippage(tick.toFixed(2))
  }, [ready, exact, defaults.entry, defaults.stop, defaults.source, tick, contract?.ask])
  const valid =
    ready &&
    exact &&
    Number(entry) > 0 &&
    Number(stop) > 0 &&
    Number(stop) < Number(entry) &&
    Number.isInteger(Number(lots)) &&
    Number(lots) >= 1 &&
    Number(lots) <= 10000 &&
    slippage !== '' &&
    Number(slippage) >= 0 &&
    Number(slippage) < Number(stop)
  const currentKey = JSON.stringify([
    username,
    mode,
    feeDay,
    symbol,
    exchange,
    entry,
    stop,
    lots,
    slippage,
  ])
  const [request, setRequest] = useState<{ key: string; body: OptionRiskRequest } | null>(null)
  const firstRequest = useRef(true)
  useEffect(() => {
    if (!valid) {
      setRequest(null)
      return
    }
    const update = () =>
      setRequest({
        key: currentKey,
        body: { symbol, exchange, entry, stop, lots: Number(lots), slippage },
      })
    if (firstRequest.current) {
      firstRequest.current = false
      update()
      return
    }
    const timer = setTimeout(update, 80)
    return () => clearTimeout(timer)
  }, [currentKey, valid, symbol, exchange, entry, stop, lots, slippage])
  const estimate = useQuery({
    queryKey: ['option-risk-preview', request?.key],
    enabled: valid && request?.key === currentKey,
    queryFn: ({ signal }) => optionRiskApi.preview(request!.body, signal),
    staleTime: 60000,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const result =
    valid &&
    request?.key === currentKey &&
    !estimate.isError &&
    estimate.data?.symbol === symbol &&
    estimate.data.exchange === exchange
      ? estimate.data
      : null
  useEffect(() => {
    onLevels(
      show && result
        ? { entry: Number(result.entry), stop: Number(result.stop), target: Number(result.target) }
        : null
    )
  }, [show, result, onLevels])
  useEffect(() => () => onLevels(null), [onLevels])
  const error = (estimate.error as { response?: { data?: { message?: string } } })?.response?.data
    ?.message
  const unavailable = !ready
    ? 'Waiting for verified chart prices.'
    : !exact
      ? 'Contract lot / tick size unavailable.'
      : !stop
        ? 'Set an SL below entry to calculate the target and net cash risk.'
        : !valid
          ? 'Enter valid prices and whole lots; SL must be below entry.'
          : estimate.isError
            ? error || 'Fee estimate unavailable. Edit a level to retry.'
            : null
  const Panel=embedded?InlineRisk:ChartToolPanel
  return (
    <Panel
      floating={docked}
      label="Premium risk preview"
      title={
        <>
          <span className="font-medium">Entry · SL · Target 1:2</span>
          {docked ? (
            result ? (
              <span className="ml-3 inline-flex gap-3 tabular-nums">
                <span
                  className={
                    Number(result.net_profit) > 0
                      ? 'text-emerald-700 dark:text-emerald-400'
                      : 'text-red-700 dark:text-red-400'
                  }
                >
                  Net {Number(result.net_profit) >= 0 ? '+' : ''}
                  {cash(result.net_profit)}
                </span>
                <span className="text-red-700 dark:text-red-400">/ −{cash(result.net_loss)}</span>
              </span>
            ) : null
          ) : result ? (
            <span className="ml-3 inline-flex flex-wrap gap-x-4 gap-y-1 tabular-nums">
              <span className="font-semibold text-blue-700 dark:text-blue-400">
                Entry {cash(result.entry)}
              </span>
              <span className="font-semibold text-red-700 dark:text-red-400">
                SL {cash(result.stop)}
              </span>
              <span
                aria-label="2R target"
                className="font-semibold text-emerald-700 dark:text-emerald-400"
              >
                Target {cash(result.target)}
              </span>
              <span
                aria-label="Estimated net profit"
                className={
                  Number(result.net_profit) > 0
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-red-600 dark:text-red-400'
                }
              >
                {Number(result.net_profit) >= 0 ? 'Net profit' : 'Net at target'}{' '}
                {cash(result.net_profit)}
              </span>
              <span aria-label="Estimated net loss" className="text-red-600 dark:text-red-400">
                Net loss −{cash(result.net_loss)}
              </span>
            </span>
          ) : (
            <span className="ml-2 text-muted-foreground">{unavailable ?? 'Calculating…'}</span>
          )}
        </>
      }
    >
      <div className="space-y-3 p-3 text-xs">
        <p className="text-muted-foreground">
          {symbol} · Buy premium ·{' '}
          {exact ? `${contract.lotsize} units / lot` : 'Lot size unavailable'} · Estimated cash
          outcomes after fees.
        </p>
        {(docked || embedded) && result ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-md border bg-background p-3 tabular-nums sm:grid-cols-5">
            <div>
              <dt className="text-muted-foreground">Entry</dt>
              <dd className="mt-1 font-semibold text-blue-700 dark:text-blue-400">
                {cash(result.entry)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">SL</dt>
              <dd className="mt-1 font-semibold text-red-700 dark:text-red-400">
                {cash(result.stop)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Target 1:2</dt>
              <dd
                aria-label="2R target"
                className="mt-1 font-semibold text-emerald-700 dark:text-emerald-400"
              >
                {cash(result.target)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">
                {Number(result.net_profit) >= 0 ? 'Net profit' : 'Net at target'}
              </dt>
              <dd
                aria-label="Estimated net profit"
                className={`mt-1 font-semibold ${Number(result.net_profit) > 0 ? 'text-emerald-700 dark:text-emerald-400' : 'text-red-700 dark:text-red-400'}`}
              >
                {cash(result.net_profit)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Net loss</dt>
              <dd
                aria-label="Estimated net loss"
                className="mt-1 font-semibold text-red-700 dark:text-red-400"
              >
                −{cash(result.net_loss)}
              </dd>
            </div>
          </dl>
        ) : null}
        <div className="flex flex-wrap items-end gap-3">
          {(
            [
              ['Entry ₹', 'Preview entry', entry, setEntry],
              ['SL ₹', 'Preview SL', stop, setStop],
              ['Lots', 'Preview lots', lots, setLots],
              ['Exit slippage ₹ / unit', 'Preview exit slippage', slippage, setSlippage],
            ] as const
          ).map(([label, name, value, setter]) => (
            <label key={name} className="space-y-1">
              <span className="block">{label}</span>
              <Input
                aria-label={name}
                type="number"
                min={name === 'Preview exit slippage' ? 0 : name === 'Preview lots' ? 1 : tick}
                step={name === 'Preview lots' ? 1 : tick || 'any'}
                value={value}
                disabled={!ready || !exact}
                readOnly={!!lockedPlan && (name==='Preview entry'||name==='Preview SL')}
                className="h-8 w-28 bg-background px-2 text-xs tabular-nums md:text-xs"
                onChange={(e) => {
                  touched.current = true
                  setter(e.target.value)
                  if (name === 'Preview SL') setSource('Manual SL')
                  if (name === 'Preview entry') setEntrySource('Manual entry')
                }}
              />
            </label>
          ))}
          {!lockedPlan?<Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!ready || !exact}
            className="text-xs"
            onClick={() => {
              touched.current = false
              initialized.current = !!defaults.stop
              setEntry(defaults.entry?.toFixed(2) ?? '')
              setStop(defaults.stop?.toFixed(2) ?? '')
              setSource(defaults.source ?? '')
              setSlippage(tick.toFixed(2))
              setEntrySource(
                contract?.ask && contract.ask > 0 ? 'Chain ask snapshot' : 'Last confirmed close'
              )
            }}
          >
            Use chart levels
          </Button>:null}
          {!embedded?<label className="flex min-h-8 items-center gap-2">
            <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
            Show levels on chart
          </label>:null}
        </div>
        <p className="text-muted-foreground">
          {entrySource ? `Entry source: ${entrySource}. ` : ''}
          {source ? `SL source: ${source}. ` : ''}Target = entry + 2 × (entry − SL). Both CE and PE
          are long-premium plans.
        </p>
        {unavailable ? <p role="status">{unavailable}</p> : null}
        {estimate.isError && valid && request?.key === currentKey ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="text-xs"
            onClick={() => void estimate.refetch()}
          >
            Retry estimate
          </Button>
        ) : null}
        {result ? (
          <>
            {lockedPlan && Number(result.net_reward_risk)<1.5?<p role="note" className="text-amber-600 dark:text-amber-400">Below the proposed 1.5:1 net reward/risk filter after costs. These are planning levels, not a trade approval.</p>:null}
            <p className="tabular-nums">
              {result.lots} lot{result.lots === 1 ? '' : 's'} × {result.lot_size} ={' '}
              {result.quantity} units · Net reward / risk {result.net_reward_risk}:1 after fees and
              exit slippage.
            </p>
            <p className="text-muted-foreground">
              1:2 applies to price distance. Entry assumes your entered fill price; exits assume{' '}
              {cash(result.slippage)} / unit adverse slippage. A stop fill can differ if price gaps.
            </p>
            <details>
              <summary className="cursor-pointer">
                Fees · target {cash(result.profit_fees)} / SL {cash(result.loss_fees)}
              </summary>
              <div className="mt-2 max-w-lg overflow-auto">
                <table className="w-full text-left tabular-nums">
                  <thead>
                    <tr>
                      <th className="py-1">Round trip</th>
                      <th>At target</th>
                      <th>At SL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.keys(result.profit_fee_breakdown).map((key) => (
                      <tr key={key}>
                        <th className="py-1 font-normal uppercase">{key}</th>
                        <td>{cash(result.profit_fee_breakdown[key])}</td>
                        <td>{cash(result.loss_fee_breakdown[key])}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-muted-foreground">
                Account brokerage {cash(result.brokerage_per_order)} per executed order; one buy and
                one sell. Schedule {result.fee_date}. {result.fee_source}.
              </p>
            </details>
          </>
        ) : null}
      </div>
    </Panel>
  )
}
