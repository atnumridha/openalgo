import { useMemo } from 'react'
import { PayoffChart } from '@/components/strategy-builder/PayoffChart'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { strategyPayoffPreview } from '@/lib/strategyPayoffPreview'
import type { Strategy } from '@/types/strategy_module'

function formatInr(value: number): string {
  if (!Number.isFinite(value)) return value > 0 ? 'Unlimited' : 'Unlimited loss'
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(value)
}

export function StrategyPayoffChart({ strategy }: { strategy: Strategy }) {
  const preview = useMemo(() => strategyPayoffPreview(strategy), [strategy])
  if (!preview) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle>Expiry payoff</CardTitle>
        <CardDescription>
          Plotted from the saved legs at current ATM offsets. Premium is synthetic, not a live quote.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <PayoffChart
          title={`${strategy.name} expiry payoff`}
          chartIdentity={`strategy-${strategy.id}-payoff`}
          scenario={preview.scenario}
          remainingYears={preview.remainingYears}
          payoff={preview.payoff}
          showTplus0={false}
          height={360}
          formatCurrency={formatInr}
        />
      </CardContent>
    </Card>
  )
}
