import { useBrokerCurrencyFormatter, useBrokerPriceFormatter } from '@/hooks/useBrokerCurrencyFormatter'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { scalpingApi, type MLPlan } from '@/api/scalping'
import { Badge } from '@/components/ui/badge'
import type { SelectedLeg } from '@/types/scalping'

export function MlEntryPlan({ leg, quantity, leverage, onPlan }: { leg: SelectedLeg | null; quantity: number; leverage: number; onPlan?: (plan: MLPlan | undefined) => void }) {
  const display = useBrokerCurrencyFormatter('deltaexchange')
  const amount = (v?: number) => v == null ? '—' : display(v)
  const quote = useBrokerPriceFormatter('deltaexchange')
  const price = (v?: number) => v == null ? '—' : quote(v)
  const [now, setNow] = useState(Date.now() / 1000)
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(id)
  }, [])
  const query = useQuery({
    queryKey: ['scalping-ml-plan', leg?.symbol, quantity, leverage],
    enabled: leg?.exchange === 'CRYPTO',
    queryFn: async () => {
      const reply = await scalpingApi.getMLPlan(leg!.symbol, quantity, leverage)
      if (reply.status !== 'success') throw new Error('ML plan unavailable')
      return reply.data
    },
    // React Query keeps one request in flight, including when a refresh is slow.
    refetchInterval: 1000, refetchIntervalInBackground: true,
    retry: false, refetchOnWindowFocus: false,
  })
  const data = query.data
  const stale = !!data?.updated_at && (now - data.updated_at > 15 || now - (data.signal_time ?? 0) > 90)
  const unavailable = query.isError || stale
  useEffect(() => {
    onPlan?.(unavailable || leg?.exchange !== 'CRYPTO' ? undefined : data)
  }, [onPlan, data, unavailable, leg?.exchange])
  if (leg?.exchange !== 'CRYPTO') return null
  const action = unavailable ? 'HOLD' : data?.action ?? 'HOLD'
  return (
    <section className="space-y-3 rounded-lg border bg-card p-3" aria-label="Fee-aware ML plan">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium">ML entry & exit plan · {leg.symbol}</h3>
        <Badge variant={action === 'HOLD' ? 'secondary' : 'default'}>{action}</Badge>
        <span className="text-xs text-muted-foreground">Research only · {data?.research_qualified ? 'historical checks passed' : 'not qualified for trading'}</span>
      </div>
      <p className="text-sm">{unavailable ? 'HOLD — ML plan unavailable or stale.' : data?.reason ?? 'Waiting for the ML worker…'}</p>
      <p className="text-xs text-muted-foreground" aria-live="off">
        Recalculates every second · entry, SL, target, fees and entry checks.
        {data?.server_time && !query.isError ? ` Plan checked ${new Date(data.server_time * 1000).toLocaleTimeString()}.` : ''}
        {' '}Probabilities use completed one-minute candles.
      </p>
      {!unavailable && !!data?.plans.length && (
        <div className="grid gap-3 md:grid-cols-2">
          {data.plans.map((p) => (
            <div className="space-y-2 rounded-md border p-3" key={p.side}>
              <div className="flex items-center justify-between text-sm font-semibold">
                <span className={p.side === 'LONG' ? 'text-emerald-600' : 'text-red-600'}>{p.side}</span>
                <span>{(p.probability * 100).toFixed(1)}%</span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs">
                <span>Maker entry<br /><b className="font-mono">{price(p.entry)}</b></span>
                <span>Stop loss<br /><b className="font-mono">{price(p.stop)}</b></span>
                <span>Net-profit target<br /><b className="font-mono">{price(p.target)}</b></span>
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                <dt>Planned risk</dt><dd className="text-right font-mono">{amount(p.net_risk)}</dd>
                <dt>Net reward</dt><dd className="text-right font-mono">{amount(p.net_target)}</dd>
                <dt>Fees at target, incl. GST</dt><dd className="text-right font-mono">{amount(p.target_fees)}</dd>
                <dt>Fees at SL, incl. GST</dt><dd className="text-right font-mono">{amount(p.stop_fees)}</dd>
                <dt>Estimated expectancy</dt><dd className="text-right font-mono">{amount(p.expected_net_usd)}</dd>
              </dl>
              <p className="text-xs text-muted-foreground">{p.reason}</p>
            </div>
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Target: at least 3× planned net risk and $1 net. Full maker entry/target fees, taker SL fees,
        18% GST and $0.10 slippage reserve are budgeted. Limits: $1 risk · $5 margin · $1,000 notional.
        Tested profile: 1 BTC contract at 25×. INR at ₹85/USD.
      </p>
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">Model evidence & exit rules</summary>
        <div className="mt-2 space-y-2">
          <p>Each percentage estimates a profitable trade after costs, conditional on a maker fill and the tested exit plan.
            LONG and SHORT probabilities are independent. Candle replay approximates fills; queue position and 15-second execution remain unverified.</p>
          <p>Exit policy: take profit at the calculated target, market SL, or close at 28 minutes.
            Gaps and actual slippage can exceed planned risk. These are proposed levels; the panel does not attach orders or manage your existing positions.</p>
          <p>Holdout trades: {data?.test?.trades ?? '—'} · Win rate: {data?.test?.trades ? `${(data.test.win_rate * 100).toFixed(1)}%` : '—'}
            {' · '}Net result: {data?.test?.trades ? amount(data.test.net_usd) : 'No qualifying trades'}
            {' · '}Required probability: {data?.threshold ? `${(data.threshold * 100).toFixed(0)}%` : '—'}</p>
          <p>Model: {data?.model_version ?? '—'} · Worker evaluation: {data?.inference_ms?.toFixed(1) ?? '—'} ms (may be cached).
            {' '}Plans and quotes refresh every second; predictions use completed one-minute candles.
            {data?.signal_time ? ` Candle closed ${new Date(data.signal_time * 1000).toLocaleTimeString()}.` : ''}</p>
        </div>
      </details>
    </section>
  )
}
