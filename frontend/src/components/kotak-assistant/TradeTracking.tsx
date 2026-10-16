import type { DeskMode, Trade } from '@/api/kotakAssistant'
import { memo } from 'react'

function stamp(epoch: number) {
  return Number.isFinite(epoch)
    ? new Date(epoch * 1000).toLocaleString('en-IN', {
        timeZone: 'Asia/Kolkata',
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      })
    : 'Time unavailable'
}

export const TradeTracking = memo(function TradeTracking({
  trades,
  mode,
}: {
  trades: Trade[]
  mode: DeskMode
}) {
  const saved = trades.filter((t) => t.mode === mode).sort((a, b) => b.created - a.created)
  return (
    <details className="rounded-lg border bg-card p-4" aria-label="Saved terminal trade tracking">
      <summary className="cursor-pointer font-medium">
        Terminal trade history · {saved.length} saved · {mode === 'live' ? 'LIVE' : 'PAPER'}
      </summary>
      <p className="my-3 text-xs text-muted-foreground">
        Orders, fills, protection and exits are saved on the server. Active trades reconcile after
        the server restarts and the broker reconnects.
      </p>
      {!saved.length && (
        <p className="text-sm text-muted-foreground">
          No terminal trades recorded in this account and mode.
        </p>
      )}
      <div className="space-y-3">
        {saved.map((trade) => (
          <details key={trade.id} className="rounded-md border p-3">
            <summary className="cursor-pointer text-sm">
              <strong>{trade.symbol}</strong> · {trade.status.replaceAll('_', ' ')} ·{' '}
              {trade.entry_quantity} filled / {trade.remaining} remaining
            </summary>
            <p className="mt-2 text-xs text-muted-foreground">
              {stamp(trade.created)} IST · Tracking ID {trade.id}
            </p>
            <p className="mt-1 text-sm">{trade.reason}</p>
            <p className="mt-1 break-words text-xs">
              Broker orders:{' '}
              {trade.ops
                .map(
                  (op) =>
                    `${op.role}: ${op.orderid || (op.state === 'rejected' ? 'No broker ID returned' : 'awaiting ID')} (${op.broker_status || op.state})`
                )
                .join(' · ') || 'Awaiting submission'}
            </p>
            <ol className="mt-3 space-y-2 border-l pl-3 text-xs">
              {trade.lifecycle?.map((event, i) => (
                <li key={`${event.at}:${i}`}>
                  <span className="tabular-nums text-muted-foreground">{stamp(event.at)} IST</span>{' '}
                  <strong>{event.status.replaceAll('_', ' ')}</strong> · {event.reason}
                  <span className="block text-muted-foreground">
                    {event.filled} filled / {event.remaining} remaining
                    {event.sl ? ` · SL ${event.sl}` : ''}
                  </span>
                </li>
              ))}
            </ol>
          </details>
        ))}
      </div>
    </details>
  )
})
