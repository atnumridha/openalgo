import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { readTradeAlerts, dismissTradeAlert, TRADE_ALERT_EVENT } from './deltaTradeAlerts'
import { readySound, playAlertSound } from '@/lib/trading/alertDelivery'
export function DeltaTradeAlerts({ account, symbol }: { account: string; symbol: string }) {
  const [alerts, setAlerts] = useState(() => readTradeAlerts(account, symbol))
  const shown = useRef(new Set<string>())
  useEffect(() => {
    const refresh = () => setAlerts(readTradeAlerts(account, symbol))
    refresh()
    window.addEventListener(TRADE_ALERT_EVENT, refresh)
    window.addEventListener('storage', refresh)
    return () => {
      window.removeEventListener(TRADE_ALERT_EVENT, refresh)
      window.removeEventListener('storage', refresh)
    }
  }, [account, symbol])
  useEffect(() => {
    for (const event of alerts) {
      const id = `delta-trade:${account}:${symbol}:${event.id}`
      if (shown.current.has(id)) continue
      shown.current.add(id)
      toast.success(event.title, {
        id,
        description: event.message,
        duration: Infinity,
        closeButton: true,
        onDismiss: () => dismissTradeAlert(account, symbol, event.id),
      })
    }
  }, [alerts, account, symbol])
  return (
    <div className="space-y-1">
      <button
        type="button"
        className="rounded border border-border px-2 py-1 text-xs"
        onClick={() => {
          readySound()
          playAlertSound()
        }}
      >
        Test / enable sound
      </button>
      <p className="text-muted-foreground">
        Alerts stay until you dismiss them. After reload, click once to enable sound.
      </p>
      {alerts.length > 0 && (
        <details open className="rounded border border-border p-2">
          <summary className="cursor-pointer">Trade alerts ({alerts.length})</summary>
          <div className="max-h-36 space-y-2 overflow-y-auto" aria-label="Trade alerts">
            {alerts.map((event) => (
              <div key={event.id} role="status" className="border-t border-border pt-1">
                <div className="flex items-start justify-between gap-2">
                  <strong>{event.title}</strong>
                  <button
                    type="button"
                    aria-label={`Dismiss ${event.title}`}
                    onClick={() => {
                      dismissTradeAlert(account, symbol, event.id)
                      toast.dismiss(`delta-trade:${account}:${symbol}:${event.id}`)
                    }}
                  >
                    ×
                  </button>
                </div>
                <p>{event.message}</p>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}
