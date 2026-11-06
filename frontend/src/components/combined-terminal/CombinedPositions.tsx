import { useEffect, useState } from 'react'
import {
  brokerName,
  combinedTerminalApi,
  rupees,
  terminalError,
  type ManagedPosition,
} from '@/api/combinedTerminal'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
function Position({ row, onNotice }: { row: ManagedPosition; onNotice: (value: string) => void }) {
  const [sl, setSl] = useState(String(row.current_sl ?? row.sl ?? ''))
  const [busy, setBusy] = useState(false)
  const cancelEntry = row.quantity === 0
  const [pending, setPending] = useState<'exit' | 'stop' | null>(null)
  useEffect(() => {
    if (pending === 'stop') setPending(null)
  }, [row.current_sl])
  useEffect(() => {
    if (row.data_fresh && ['exit_rejected', 'cancel_rejected'].includes(row.status))
      setPending(null)
  }, [row.status, row.data_fresh])
  const mutate = async (action: 'exit' | 'stop') => {
    if (!row.trade_id || busy || pending === 'exit' || (action === 'stop' && pending === 'stop'))
      return
    setBusy(true)
    try {
      const result = await combinedTerminalApi.mutateTrade(row.trade_id, action, {
        request_id: crypto.randomUUID(),
        ...(action === 'stop' ? { sl: Number(sl) } : {}),
      })
      setPending(
        result.state === 'rejected'
          ? null
          : result.state === 'accepted' && action === 'stop'
            ? null
            : action
      )
      onNotice(
        result.state === 'rejected'
          ? `${action === 'exit' ? 'Exit' : 'Stop change'} rejected on ${brokerName(row.broker)}: ${result.error || 'Broker rejected the request'}`
          : result.state === 'unknown'
            ? `${brokerName(row.broker)} outcome unknown; watch reconciliation before retrying.`
            : `${action === 'exit' ? 'Exit' : 'Stop change'} requested on ${brokerName(row.broker)}; awaiting broker confirmation.`
      )
    } catch (error) {
      setPending(action)
      onNotice(`${terminalError(error)} · outcome needs reconciliation before retrying.`)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card className="py-0">
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap justify-between gap-2">
          <strong>{row.symbol}</strong>
          <span className="text-sm">
            {brokerName(row.broker)} · {row.status || 'broker position'}
          </span>
        </div>
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-6">
          {[
            ['Quantity', row.quantity],
            ['Entry', rupees(row.average_entry ?? row.entry)],
            ['Current premium', rupees(row.ltp)],
            ['SL', rupees(row.current_sl ?? row.sl)],
            ['Target', rupees(row.target)],
            ['Estimated open net', rupees(row.net_open)],
          ].map(([label, value]) => (
            <div key={String(label)}>
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="font-medium tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
        {!row.data_fresh && (
          <p className="text-sm text-amber-700 dark:text-amber-400">
            Last-known position · live prices unavailable. Broker exits remain available.
          </p>
        )}
        {row.managed && row.trade_id ? (
          <div className="flex flex-wrap items-end gap-3">
            <Button
              variant="destructive"
              disabled={busy || pending === 'exit'}
              onClick={() => void mutate('exit')}
              aria-label={`${cancelEntry ? 'Cancel entry' : 'Exit'} ${row.symbol} on ${brokerName(row.broker)}`}
            >
              {pending === 'exit'
                ? 'Request pending reconciliation'
                : `${cancelEntry ? 'Cancel entry' : 'Exit'} on ${brokerName(row.broker)}`}
            </Button>
            <label className="text-sm">
              Tighten SL ₹
              <input
                aria-label={`Tighten SL for ${row.symbol} on ${brokerName(row.broker)}`}
                type="number"
                min="0"
                step="0.05"
                value={sl}
                onChange={(e) => setSl(e.target.value)}
                className="ml-2 h-11 w-28 rounded-md border bg-background px-2"
              />
            </label>
            <Button
              variant="outline"
              disabled={busy || !!pending || !Number.isFinite(Number(sl)) || Number(sl) <= 0}
              onClick={() => void mutate('stop')}
            >
              Update SL on {brokerName(row.broker)}
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            External broker position · monitoring only. Use the owning broker’s controls until
            explicitly adopted for protection.
          </p>
        )}
        {row.reason && <p className="text-sm text-muted-foreground">{row.reason}</p>}
      </CardContent>
    </Card>
  )
}
export function CombinedPositions({
  positions,
  onNotice,
}: {
  positions: ManagedPosition[]
  onNotice: (value: string) => void
}) {
  return (
    <section
      id="kotak-open-trades"
      aria-label="Combined open trades"
      className="space-y-3 scroll-mt-4"
    >
      <h2 className="text-lg font-semibold">Open trades & live monitoring</h2>
      {positions.length ? (
        positions.map((p) => (
          <Position
            key={p.trade_id || `${p.connection_id}:${p.exchange}:${p.symbol}:${p.product}`}
            row={p}
            onNotice={onNotice}
          />
        ))
      ) : (
        <p className="text-sm text-muted-foreground">
          No open positions observed. Unavailable accounts remain listed above.
        </p>
      )}
    </section>
  )
}
