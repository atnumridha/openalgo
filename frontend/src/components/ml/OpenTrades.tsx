import { useBrokerCurrencyFormatter, useBrokerPriceFormatter } from '@/hooks/useBrokerCurrencyFormatter'
import { X } from 'lucide-react'
import { type MlClosedTrade, type MlOpenTrade, mlSignalsApi } from '@/api/mlSignals'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

function pnlClass(value: number) {
  return value > 0 ? 'text-green-600' : value < 0 ? 'text-red-600' : ''
}

export function OpenTrades({
  open,
  closed,
  onChanged,
}: {
  open: MlOpenTrade[]
  closed: MlClosedTrade[]
  onChanged: () => void
}) {
  const display = useBrokerCurrencyFormatter('deltaexchange')
  const usd = (value: number | null | undefined) => value == null ? '-' : display(value)
  const quote = useBrokerPriceFormatter('deltaexchange')
  const price = (v: number | null | undefined) => v == null ? '-' : quote(v)
  const close = async (trade: MlOpenTrade) => {
    try {
      const response = await mlSignalsApi.closeTrade(trade.run_id, trade.leg_id)
      showToast.success(response.data.message)
    } catch (error) {
      const message = (error as { response?: { data?: { message?: string } } }).response?.data
        ?.message
      showToast.error(message || 'The trade could not be closed.')
    } finally {
      onChanged()
    }
  }
  const totalNet = open.reduce((sum, trade) => sum + trade.net_pnl, 0)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Open ML trades</span>
          {open.length > 0 && (
            <span className={cn('font-mono text-lg', pnlClass(totalNet))} data-testid="ml-open-net">
              {usd(totalNet)} net
            </span>
          )}
        </CardTitle>
        <CardDescription>
          Net is after the fees paid, the closing fee due now (zero inside the Scalper Offer window)
          and funding. A Diwali Fee Voucher is a credit, shown beside it.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {open.length === 0 ? (
          <p className="text-muted-foreground">No open ML trades.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="p-2">Symbol</th>
                  <th className="p-2">Mode</th>
                  <th className="p-2 text-right">Entry / last</th>
                  <th className="p-2 text-right">Stop / target</th>
                  <th className="p-2 text-right">Gross</th>
                  <th className="p-2 text-right">Fees</th>
                  <th className="p-2 text-right">Net</th>
                  <th className="p-2" />
                </tr>
              </thead>
              <tbody>
                {open.map((trade) => (
                  <tr key={trade.key} className="border-b" data-testid={`ml-trade-${trade.key}`}>
                    <td className="p-2">
                      <span className={trade.side === 'LONG' ? 'text-green-600' : 'text-red-600'}>
                        {trade.side}
                      </span>{' '}
                      {trade.contracts} {trade.symbol}
                      <div className="text-xs text-muted-foreground">
                        {Math.floor(trade.held_minutes)}m held
                        {trade.entry_status !== 'complete' ? ' · filling' : ''}
                        {trade.exit_kind ? ' · closing' : ''}
                      </div>
                    </td>
                    <td className="p-2">
                      <Badge variant={trade.mode === 'live' ? 'destructive' : 'secondary'}>
                        {trade.mode === 'live' ? 'Live' : 'Sandbox'}
                      </Badge>
                    </td>
                    <td className="p-2 text-right font-mono">
                      {price(trade.entry_price)}
                      <div className="text-xs text-muted-foreground">{price(trade.last_price)}</div>
                    </td>
                    <td className="p-2 text-right font-mono">
                      {price(trade.stop_price)}
                      {trade.trail_active ? ' (trailing)' : ''}
                      <div className="text-xs text-muted-foreground">
                        {price(trade.target_price)}
                      </div>
                    </td>
                    <td className={cn('p-2 text-right font-mono', pnlClass(trade.gross_pnl))}>
                      {usd(trade.gross_pnl)}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {usd(trade.fees_paid + trade.exit_fee_now)}
                      <div className="text-xs text-muted-foreground">
                        {trade.exit_fee_now === 0 &&
                        trade.window_remaining_minutes != null &&
                        trade.window_remaining_minutes > 0
                          ? `close free for ${Math.ceil(trade.window_remaining_minutes)}m`
                          : `close ${usd(trade.exit_fee_now)}`}
                      </div>
                      {trade.voucher_now > 0 && (
                        <div className="text-xs text-emerald-600">
                          voucher {usd(trade.voucher_now)}
                        </div>
                      )}
                    </td>
                    <td
                      className={cn(
                        'p-2 text-right font-mono font-semibold',
                        pnlClass(trade.net_pnl)
                      )}
                    >
                      {usd(trade.net_pnl)}
                    </td>
                    <td className="p-2 text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={trade.entry_status !== 'complete' || !!trade.exit_kind}
                        onClick={() => void close(trade)}
                        aria-label={`Close ${trade.symbol}`}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {closed.length > 0 && (
          <div>
            <div className="pb-1 text-sm font-medium">Recently closed</div>
            <div className="space-y-1">
              {closed.slice(0, 8).map((trade, index) => (
                <div
                  key={`${trade.closed_at}-${index}`}
                  className="flex flex-wrap justify-between gap-2 border-b py-1 text-xs"
                >
                  <span>
                    {trade.side} {trade.contracts} {trade.symbol} ·{' '}
                    {trade.mode === 'live' ? 'Live' : 'Sandbox'}
                  </span>
                  <span className="text-muted-foreground">{trade.reason}</span>
                  <span className={cn('font-mono', pnlClass(trade.move_pct))}>
                    {price(trade.entry_price)} to {price(trade.exit_price)} (
                    {trade.move_pct.toFixed(3)}%)
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
