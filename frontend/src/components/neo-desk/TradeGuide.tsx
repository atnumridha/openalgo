import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { optionRiskApi, type OptionRiskRequest } from './optionRiskApi'
import { deltaGuideCash, guideFresh, readTradeGuidance, type GuideBrokerContext, type GuideCash, type GuidePlan, type GuideTrend } from './tradeGuidance'

const cash = (n: number) => n.toLocaleString('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2, minimumFractionDigits: 2 })
const price = (n: number | null) => n == null ? '—' : n.toLocaleString('en-IN', { maximumFractionDigits: 4 })
const time = (n: number | null | undefined) => n ? new Date(n * 1000).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) + ' IST' : 'Unavailable'

export function TradeGuide(props: {
  symbol: string; exchange: string; interval: string; seconds: number; live: boolean
  current: GuideTrend; higher: GuideTrend | null; higherInterval?: string | null
  plan: GuidePlan | null; quote: { price: number; time: number } | null; tick: number; lotSize?: number | null
  context?: GuideBrokerContext | null
}) {
  const user = useAuthStore(s => s.user), mode = useThemeStore(s => s.appMode)
  const [now, setNow] = useState(Date.now() / 1000)
  const [open, setOpen] = useState(() => { try { return localStorage.getItem('neo.chart.tradeGuide') !== 'collapsed' } catch { return true } })
  const [planningLots, setPlanningLots] = useState(1)
  const [feeBroker, setFeeBroker] = useState<'kotak' | 'flattrade'>(() => user?.broker === 'flattrade' ? 'flattrade' : 'kotak')
  useEffect(() => { const timer = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(timer) }, [])
  const supplied = props.context?.symbol === props.symbol && props.context.exchange === props.exchange ? props.context : null
  const context = props.live && supplied && guideFresh(supplied.asOf, now) ? supplied : null
  const staleAccount = !!supplied && !context
  const plan = staleAccount ? supplied!.plan : context ? context.plan : props.plan
  const quote = context?.quote ?? props.quote
  const reading = readTradeGuidance({ ...props, plan, quote, now })
  const option = ['NFO', 'BFO'].includes(props.exchange) && /(?:CE|PE)$/.test(props.symbol)
  const broker = supplied?.broker === 'flattrade' || supplied?.broker === 'kotak' ? supplied.broker : feeBroker
  const lotSize = context?.lotSize ?? props.lotSize
  const quantity = context?.quantity ?? (lotSize && lotSize > 0 ? planningLots * lotSize : null)
  const lots = quantity && lotSize ? quantity / lotSize : null
  const feeDay = new Date(now * 1000 + 19800000).toISOString().slice(0, 10)
  const validChart = props.live && !staleAccount && reading.headline !== 'Check live data'
  const request: OptionRiskRequest | null = option && validChart && plan?.side === 'buy' &&
    plan.stop != null && plan.target != null && (plan.stop < plan.entry || plan.protection === 'broker') && plan.target > plan.entry &&
    lots != null && Number.isSafeInteger(lots) && lots > 0 && props.tick > 0
    ? { symbol: props.symbol, exchange: props.exchange, entry: String(plan.entry), stop: String(plan.stop), target: String(plan.target), lots, slippage: String(props.tick), broker, ...(plan.protection === 'broker' ? { position: true } : {}) }
    : null
  const query = useQuery({
    queryKey: ['chart-trade-guide-fees', user?.username, mode, feeDay, request],
    enabled: request !== null,
    queryFn: ({ signal }) => optionRiskApi.preview(request!, signal),
    staleTime: 60000, retry: false, refetchOnWindowFocus: false,
  })
  const estimate = request && !query.isError && query.data?.symbol === props.symbol &&
    query.data.exchange === props.exchange && query.data.broker === broker && query.data.quantity === quantity
    ? query.data : null
  let money: GuideCash | null = null
  if (estimate) {
    const raw = [estimate.net_loss, estimate.net_profit, estimate.loss_fees, estimate.profit_fees]
    const values = raw.map(n => n !== null && n !== undefined && String(n).trim() !== '' ? Number(n) : NaN)
    if (values.every(Number.isFinite)) money = { atStop: -values[0], atTarget: values[1], feesAtStop: values[2], feesAtTarget: values[3] }
  } else if (validChart && props.exchange === 'DELTA' && context?.deltaFees && plan && quantity != null) {
    money = deltaGuideCash(plan, quantity, context.deltaFees.contractValue, context.deltaFees)
  }
  const balance = context?.balance && Number.isFinite(context.balance.amount) && context.balance.amount > 0
    ? context.balance.amount * (context.balance.currency === 'USD' ? 85 : 1) : null
  const riskPct = money && money.atStop < 0 && balance ? -money.atStop / balance * 100 : null
  const rewardRisk = money && money.atTarget != null && money.atStop < 0 ? money.atTarget / -money.atStop : null
  const toggle = (next: boolean) => { setOpen(next); try { localStorage.setItem('neo.chart.tradeGuide', next ? 'expanded' : 'collapsed') } catch { /* session only */ } }
  return <details open={open} onToggle={e => { if (e.currentTarget.open !== open) toggle(e.currentTarget.open) }} aria-label="Trade guide" className="mb-2 rounded border border-border bg-card text-xs">
    <summary className="cursor-pointer px-2 py-2 focus-visible:outline focus-visible:outline-2">
      <strong>Trade guide</strong>
      <span className={`mt-1 block font-medium ${reading.headline === 'Upward bias' ? 'text-emerald-600 dark:text-emerald-400' : reading.headline === 'Downward bias' ? 'text-red-600 dark:text-red-400' : 'text-amber-700 dark:text-amber-400'}`}>{reading.headline}</span>
      {!open && <span className="mt-1 block text-[11px] text-muted-foreground">{reading.warnings[0] ?? reading.reason}</span>}
    </summary>
    <div className="space-y-2 border-t px-2 py-2">
      <p>{reading.reason}</p>
      <p className="text-muted-foreground">Chart {props.interval}: {props.current.direction}{props.higherInterval ? ` · ${props.higherInterval}: ${props.higher?.direction ?? 'unavailable'}` : ''}</p>
      {option && <p className="text-muted-foreground">Bought {props.symbol.endsWith('PE') ? 'PE' : 'CE'}: this is the option premium direction. A new buy uses SL below premium entry.</p>}
      {context?.execution && <details className="rounded border p-2"><summary className="cursor-pointer"><strong>Auto · separate 1m/5m setup</strong><span className="mt-1 block">{context.execution.summary}</span></summary><p className="mt-1 text-muted-foreground">{context.execution.message}</p><p className="text-muted-foreground">Checked {time(context.execution.checkedAt)}</p></details>}
      {reading.warnings.map(w => <p key={w} role="note" className="text-amber-700 dark:text-amber-400">{w}</p>)}
      {staleAccount && <p role="note" className="text-amber-700 dark:text-amber-400">Broker snapshot is old or unavailable. Account outcomes are not shown.</p>}
      {plan ? <>
        <p className="font-medium">{props.exchange === 'DELTA' ? `${plan.side === 'buy' ? 'Long' : 'Short'} · ` : ''}{plan.label}{plan.protection === 'planned' ? ' · planning only' : ''}</p>
        <dl aria-label="Guide price levels" className="grid grid-cols-2 gap-x-2 gap-y-1 tabular-nums">
          <dt>Entry {props.exchange === 'DELTA' ? '$' : '₹'}</dt><dd className="text-right">{price(plan.entry)}</dd>
          <dt>SL</dt><dd className="text-right">{price(plan.stop)}</dd>
          <dt>Target</dt><dd className="text-right">{plan.target == null ? 'No fixed target confirmed' : price(plan.target)}</dd>
        </dl>
        <p className="text-[11px] text-muted-foreground">Plan {time(plan.asOf)}{plan.protection === 'planned' ? ' · no protective order is placed by this guide.' : ''}</p>
      </> : <p>Plan unavailable. Check the Entry · SL · Target panel for the specific calculation reason.</p>}
      {option && <div className="space-y-2">
        <label className="block">Fee estimate for<select aria-label="Planning fee profile" value={broker} disabled={!!supplied} onChange={e => setFeeBroker(e.target.value as 'kotak' | 'flattrade')} className="mt-1 h-8 w-full rounded border bg-background px-1"><option value="kotak">Kotak Neo</option><option value="flattrade">Flattrade · ₹0 brokerage</option></select></label>
        {!context && <label className="block">Planning lots<input aria-label="Planning lots" type="number" min="1" max="10000" step="1" value={planningLots} onChange={e => setPlanningLots(Number(e.target.value))} className="mt-1 h-8 w-full rounded border bg-background px-2" /></label>}
        <p className="text-muted-foreground">{quantity != null && Number.isFinite(quantity) ? `${quantity} units` : 'Quantity unavailable'} · estimate only; this does not select the order broker.</p>
      </div>}
      {props.exchange === 'DELTA' && context && <p className="text-muted-foreground">{quantity != null && Number.isSafeInteger(quantity) ? `${quantity} contracts · ${context.inPosition ? 'current position size' : 'ticket size for this estimate'}` : 'Quantity unavailable'}</p>}
      {money ? <>
        <dl className="grid grid-cols-2 gap-x-2 gap-y-1 border-t pt-2 tabular-nums">
          <dt>Net at SL, est.</dt><dd aria-label="Guide net at SL" className={`text-right ${money.atStop < 0 ? 'text-red-600 dark:text-red-400' : 'text-emerald-600 dark:text-emerald-400'}`}>{cash(money.atStop)}</dd>
          <dt>Net at target, est.</dt><dd aria-label="Guide net at target" className="text-right">{money.atTarget == null ? 'Trend-managed' : cash(money.atTarget)}</dd>
          <dt>Fees at SL / target</dt><dd className="text-right">{cash(money.feesAtStop)} / {money.feesAtTarget == null ? '—' : cash(money.feesAtTarget)}</dd>
        </dl>
        {rewardRisk != null && <p>Net reward per ₹1 risk: {rewardRisk.toFixed(2)}{rewardRisk < 1 ? ' · planned reward is smaller than planned loss.' : ''}</p>}
        {riskPct != null && <p aria-label="Guide balance risk">Planned loss: {riskPct.toFixed(2)}% of {context?.balance?.label} ({cash(balance!)}).</p>}
      </> : <p className="text-muted-foreground">{query.isError ? 'Fee estimate could not be checked. Recheck the profile and plan.' : request && query.isPending ? 'Checking estimated charges…' : 'Cash outcome unavailable for this plan and verified quantity.'}</p>}
      {!balance && <p className="text-muted-foreground">Account balance unavailable. No account-risk percentage is assumed.</p>}
      <details className="border-t pt-2"><summary className="cursor-pointer">Costs, sources &amp; reminders</summary><div className="mt-2 space-y-2 text-[11px] text-muted-foreground">
        <p>{estimate ? `${estimate.fee_source} · ${estimate.fee_date}. Exit slippage allowance: ₹${props.tick} per unit.` : props.exchange === 'DELTA' ? 'Delta maker entry and standard taker exit fees, including GST. $1 = ₹85. Discounts are not assumed. Paid entry fees are used only when verified.' : 'Uses the named fee profile. Final charges require the broker statement.'}</p>
        <p>{context?.historyVerified ? context.recentExitAt && guideFresh(context.recentExitAt, now, 60) ? `Same-option exit reported ${Math.max(0, Math.floor(now - context.recentExitAt))}s ago. Check for a fresh trigger before re-entering.` : 'Selected broker tradebook verified. Another entry still needs a fresh trigger.' : 'Recent trade history unavailable. Re-entry and loss-streak counts are not assumed.'}</p>
        <p>Journal reminder: check rupee risk before entry. After consecutive losses, pause and review the setup. These are reminders, not order restrictions.</p>
        <p>Closed candle {time(props.current.time)} · quote {time(quote?.time)} · broker {time(context?.asOf)}.</p>
        <p>Advisory only. Estimated SL outcomes can differ from actual fills.</p>
      </div></details>
    </div>
  </details>
}
