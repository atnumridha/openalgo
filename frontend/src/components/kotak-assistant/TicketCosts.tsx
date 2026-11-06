import { money } from './model'
import { FEE_VERIFIED, BROKERAGE_EFFECTIVE, accountBrokerage, type ticketCosts } from './feeEstimates'

export function TicketCosts({
  estimate,
  brokerage = accountBrokerage(),
}: {
  estimate: ReturnType<typeof ticketCosts>
  brokerage?: number
}) {
  return (
    <div
      className="space-y-2 rounded-md border bg-background/40 p-2 text-xs tabular-nums"
      aria-label="Estimated trade costs"
    >
      <div className="flex flex-wrap justify-between gap-1">
        <strong>Estimated P&L after charges</strong>
        <span className="text-muted-foreground">
          Premium {estimate ? money(estimate.premium) : '—'}
        </span>
      </div>
      <p className="text-muted-foreground">
        Brokerage {money(brokerage)}/executed order · taxes included
      </p>
      <p className="text-muted-foreground">
        Account notice from {BROKERAGE_EFFECTIVE}: self-directed F&amp;O ₹10/order; dealer-assisted
        ₹49/order. Brokerage is charged per executed order, with 18% GST added.
      </p>
      <table className="w-full table-fixed text-right">
        <caption className="sr-only">
          Estimated gross P&L, round-trip charges and net P&L at SL and target
        </caption>
        <thead className="text-muted-foreground">
          <tr>
            <th className="w-10 text-left font-normal">Exit</th>
            <th className="font-normal">Gross</th>
            <th className="font-normal">Charges</th>
            <th className="font-normal">Net P&L</th>
          </tr>
        </thead>
        <tbody>
          {[
            ['SL', estimate?.grossSL, estimate?.chargesSL, estimate?.netSL],
            ['Target', estimate?.grossTarget, estimate?.chargesTarget, estimate?.netTarget],
          ].map(([label, gross, charges, net]) => (
            <tr key={String(label)}>
              <th className="py-1 text-left font-medium">{label}</th>
              <td aria-label={`Gross P&L at ${label}`} className="break-words py-1">
                {gross == null ? '—' : money(Number(gross))}
              </td>
              <td aria-label={`Estimated charges at ${label}`} className="break-words py-1">
                {charges == null ? '—' : money(Number(charges))}
              </td>
              <td
                aria-label={`Net P&L at ${label}`}
                className={`break-words py-1 font-semibold ${net == null ? '' : Number(net) < 0 ? 'text-red-600 dark:text-red-400' : 'text-emerald-700 dark:text-emerald-400'}`}
              >
                {net == null ? '—' : money(Number(net))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {estimate ? (
        <>
          <p className="text-muted-foreground">
            Net R:R 1:{estimate.netRR} ·{' '}
            {estimate.slippage
              ? `exit slippage ${money(estimate.slippage)}/unit included`
              : 'at planned fills'}
          </p>
          <details className="text-muted-foreground">
            <summary className="cursor-pointer">Charges breakdown · entry + exit</summary>
            <table className="mt-2 w-full text-right">
              <thead>
                <tr>
                  <th className="text-left">Charge</th>
                  <th>At SL</th>
                  <th>At target</th>
                </tr>
              </thead>
              <tbody>
                {(
                  ['brokerage', 'stt', 'exchange', 'gst', 'stamp', 'sebi', 'ipft', 'total'] as const
                ).map((key) => (
                  <tr key={key}>
                    <th className="text-left font-normal">
                      {
                        {
                          brokerage: 'Brokerage',
                          stt: 'STT',
                          exchange: 'Exchange',
                          gst: 'GST',
                          stamp: 'Stamp duty',
                          sebi: 'SEBI',
                          ipft: 'IPFT',
                          total: 'Total',
                        }[key]
                      }
                    </th>
                    <td>{money(estimate.slFees[key])}</td>
                    <td>{money(estimate.targetFees[key])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2">
              Account notice effective {BROKERAGE_EFFECTIVE}: self-directed futures/options ₹10 per
              executed order; dealer-assisted ₹49 per order. Not per lot or partial fill. Current
              estimate uses the configured rate above; GST is 18% on brokerage and taxable charges.
              STT, exchange/IPFT, SEBI and stamp duty remain additional. The notice’s 1-paisa
              exception applies only if a zero-brokerage plan is separately confirmed.
            </p>
            <p className="mt-1">
              Estimated entry + exit charges · verified {FEE_VERIFIED}. Final contract-note rounding
              can differ.
            </p>
          </details>
        </>
      ) : (
        <p className="text-muted-foreground">
          Charges unavailable · check prices, lots and fee schedule.
        </p>
      )}
    </div>
  )
}
