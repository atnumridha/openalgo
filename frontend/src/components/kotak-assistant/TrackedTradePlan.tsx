import type { TrackingTrade } from './trackingStore'
import { trackingPlan } from './trackingPlan'
import { money } from './model'
import { LEVEL_COLORS } from './PriceLevels'
import { ticketCosts } from './feeEstimates'

export function TrackedTradePlan({ row, brokerage }: { row: TrackingTrade; brokerage: number }) {
  const plan = trackingPlan(row)
  const quantity = row.lot * row.lots
  const costs = ticketCosts(
    plan.sl && plan.target
      ? { entry: row.entry, sl: plan.sl, target: plan.target, quantity }
      : null,
    row.exchange,
    brokerage
  )
  return (
    <div className="space-y-3">
      <dl
        className="grid gap-3 rounded-lg border p-4 sm:grid-cols-3"
        aria-label="Tracked entry and exit levels"
      >
        {[
          {
            label: 'Filled entry',
            aria: 'Tracked filled entry',
            value: row.entry,
            color: LEVEL_COLORS.entry,
          },
          {
            label: 'Stop loss (SL)',
            aria: 'Tracked SL level',
            value: plan.sl,
            color: LEVEL_COLORS.stop,
          },
          {
            label: 'Profit target',
            aria: 'Tracked profit target',
            value: plan.target,
            color: LEVEL_COLORS.target,
          },
        ].map((level) => (
          <div
            key={level.aria}
            className="min-w-0 border-l-4 pl-3"
            style={{ borderColor: level.color }}
          >
            <dt className="text-sm text-muted-foreground">{level.label}</dt>
            <dd className="mt-1 text-2xl font-semibold tabular-nums">
              <output aria-label={level.aria}>{money(level.value)}</output>
            </dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-wrap justify-between gap-2 text-sm">
        <p>
          Risk{' '}
          <output aria-label="Planned gross risk" className="font-semibold tabular-nums">
            {money(plan.sl ? (row.entry - plan.sl) * quantity : null)}
          </output>
        </p>
        <p>
          Potential profit{' '}
          <output aria-label="Planned gross profit" className="font-semibold tabular-nums">
            {money(plan.target ? (plan.target - row.entry) * quantity : null)}
          </output>
        </p>
        <p>
          R:R <strong>1:{Number(plan.ratio.toFixed(2))}</strong> · before charges
        </p>
      </div>
      {plan.restoredDefault && (
        <p className="text-xs text-muted-foreground">
          Automatic plan · 10% SL buffer where missing · 1:{Number(plan.ratio.toFixed(2))}. Earlier
          record had incomplete levels.
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border p-3">
        <table className="w-full text-right text-sm tabular-nums">
          <caption className="mb-2 text-left font-medium">
            Estimated P&L after charges · {quantity} units
          </caption>
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="pb-2 text-left">
                Exit level
              </th>
              <th scope="col" className="pb-2">
                Gross P&L
              </th>
              <th scope="col" className="pb-2">
                Charges
              </th>
              <th scope="col" className="pb-2">
                Net P&L
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row" className="py-1 text-left font-medium">
                SL
              </th>
              <td>{money(costs?.grossSL)}</td>
              <td>{money(costs?.chargesSL)}</td>
              <td aria-label="Estimated net loss at SL" className="font-semibold text-destructive">
                {money(costs?.netSL)}
              </td>
            </tr>
            <tr>
              <th scope="row" className="py-1 text-left font-medium">
                Target
              </th>
              <td>{money(costs?.grossTarget)}</td>
              <td>{money(costs?.chargesTarget)}</td>
              <td aria-label="Estimated net profit at target" className="font-semibold">
                {money(costs?.netTarget)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Brokerage estimate {money(brokerage)}/order · entry + exit taxes included · before slippage
      </p>
      <p className="text-xs text-muted-foreground">
        SL and target are monitored levels. Record the actual closing price after exiting in Kotak
        Neo.
      </p>
    </div>
  )
}
