import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { installScalpingPack, strategyQueryKeys } from '@/api/strategy_module'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { strategyResearch } from '@/lib/strategyResearch'
import type { StrategySummary } from '@/types/strategy_module'

const profiles = [
  {
    id: 'regime50200',
    title: 'EMA 50/200 + regime',
    description: '5-minute crossover filtered by prior-day trend and volatility.',
    exits: 'ATM option · technical stop · equity-based risk · rising profit stop · aim ₹900–₹1,500+',
  },
  {
    id: 'ema915',
    title: 'EMA 9/15',
    description: 'Nifty pullback with Bank Nifty trend confirmation.',
    exits: 'ITM option · technical stop · equity-based risk · rising profit stop · aim ₹900–₹1,500+',
  },
  {
    id: 'box15',
    title: 'Opening-box breakout',
    description: 'First 1-minute breakout of the completed 09:15–09:30 Nifty range.',
    exits: 'ATM option · technical stop · equity-based risk · rising profit stop · aim ₹900–₹1,500+',
  },
] as const

export function ScalpingStrategies({
  rows,
  onStart,
  onStop,
  onMode,
  busy,
}: {
  rows: StrategySummary[]
  onStart: (row: StrategySummary) => void
  onStop: (row: StrategySummary) => void
  onMode: (row: StrategySummary) => void
  busy: boolean
}) {
  const client = useQueryClient()
  const install = useMutation({
    mutationFn: installScalpingPack,
    onSuccess: () => client.invalidateQueries({ queryKey: strategyQueryKeys.strategies() }),
  })
  const complete = profiles.every((profile) => rows.some((row) => row.scalp_profile === profile.id))
  return (
    <section
      aria-label="Scalping strategies"
      className="space-y-3 rounded-xl border bg-muted/20 p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Top three research candidates</h2>
          <p className="text-sm text-muted-foreground">
            Experimental shortlist, ordered by historical net win %. The 27 September 2026 research
            used earlier exit and risk rules, 15-minute holds and modeled base costs. These are
            not results for the current profit-trailing recipe or live trading.
          </p>
        </div>
        {!complete && (
          <Button onClick={() => install.mutate()} disabled={install.isPending || busy}>
            {install.isPending ? 'Adding…' : 'Add all 3 strategies'}
          </Button>
        )}
      </div>
      {install.error && (
        <p role="alert" className="text-sm text-destructive">
          {install.error.message}
        </p>
      )}
      <div className="grid gap-3 md:grid-cols-3">
        {[...profiles].sort((a, b) =>
          (strategyResearch(b.id)?.winPercent ?? -1) - (strategyResearch(a.id)?.winPercent ?? -1)
        ).map((profile) => {
          const research = strategyResearch(profile.id)
          const row = rows.find((item) => item.scalp_profile === profile.id)
          const armed = row && row.automation_state !== 'disabled'
          return (
            <Card key={profile.id}>
              <CardHeader className="space-y-2 pb-2">
                <CardTitle className="text-base">{profile.title}</CardTitle>
                {research && <p className="text-xs text-muted-foreground">
                  Earlier-rule wins: {research.winPercent.toFixed(2)}% · {research.wins}/{research.trades} trades
                </p>}
                <p className="text-sm text-muted-foreground">{profile.description}</p>
                <p className="text-xs text-muted-foreground">{profile.exits} · 15-minute limit</p>
              </CardHeader>
              <CardContent className="space-y-3">
                <Badge variant={row?.live_enabled ? 'destructive' : 'secondary'}>
                  {row
                    ? `${row.live_enabled ? 'Live' : 'Sandbox'} · ${armed ? (row.status === 'running' ? 'In a trade' : row.automation_state === 'armed' ? 'Waiting for signal' : 'Closing / review needed') : 'Stopped'}`
                    : 'Not added'}
                </Badge>
                {row && (
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      disabled={busy}
                      variant={armed ? 'outline' : 'default'}
                      onClick={() => (armed ? onStop(row) : onStart(row))}
                    >
                      {armed ? 'Stop automation' : `Start ${row.live_enabled ? 'live' : 'sandbox'}`}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy || Boolean(armed) || row.status !== 'stopped'}
                      onClick={() => onMode(row)}
                    >
                      {row.live_enabled ? 'Use sandbox' : 'Enable live'}
                    </Button>
                    <Button size="sm" variant="ghost" asChild>
                      <Link to={`/strategy/${row.id}`}>Results & logs</Link>
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}
      </div>
      <p className="text-xs text-muted-foreground">
        Current entries use one Nifty option lot with its technical stop, and are skipped if planned
        loss including costs exceeds 1% of equity or ₹300. At ₹300 gross profit, protect ₹100;
        at ₹600, protect ₹300; at ₹900, protect ₹600. Then keep raising the stop with a maximum
        ₹300 giveback from peak executable profit. At ₹1,500, protect ₹1,200. These profit levels
        are before charges; there is no hard profit cap.
        Stops only rise; the holding deadline still applies. Kotak stop advances require broker verification.
        Charges and slippage can reduce realized profit. ₹20,000
        premium ceiling based on the ₹25,000 research assumption; your saved account budget may be
        lower. Enable the shared capital profile and costs in{' '}
        <Link className="underline" to="/strategy/research">
          Research
        </Link>
        . Live also requires session authorization, verified protection and an approved release.
        Profitability is unproven.
      </p>
      {rows.some((row) => row.scalp_profile === 'macd200' || row.scalp_profile === 'ema5') && (
        <p className="text-sm text-muted-foreground">
          Yesterday’s MACD and 5 EMA setups remain in Saved strategies below for comparison testing.
        </p>
      )}
    </section>
  )
}
