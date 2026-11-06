import { brokerName, rupees, type ConnectionState } from '@/api/combinedTerminal'
import { Card, CardContent } from '@/components/ui/card'

export function BrokerConnections({ connections }: { connections: ConnectionState[] }) {
  return <div className="grid gap-3 md:grid-cols-2">{connections.map(c => {
    const total = c.estimated_total_net
    return <Card key={c.connection.id} className="py-0" role="region" aria-label={`${brokerName(c.connection.broker)} account summary`}>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold">{brokerName(c.connection.broker)}</h3>
          <span className={c.entry_ready ? 'text-sm text-emerald-700 dark:text-emerald-400' : 'text-sm text-muted-foreground'}>{c.entry_ready ? 'Fresh account data' : 'Account needs attention'}</span>
        </div>
        <div className="flex flex-wrap justify-between gap-3 rounded-md bg-muted/40 p-3">
          <div><p className="text-sm text-muted-foreground">Available funds</p><strong className="text-lg tabular-nums">{rupees(c.funds?.availablecash)}</strong></div>
          <div><p className="text-sm text-muted-foreground">Estimated total net</p><strong className={`text-lg tabular-nums ${total != null && total < 0 ? 'text-red-700 dark:text-red-400' : total != null && total > 0 ? 'text-emerald-700 dark:text-emerald-400' : ''}`}>{rupees(total)}</strong></div>
        </div>
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
          {([['Realized net', rupees(c.realized_net)], ['Estimated open net', rupees(c.estimated_open_net)],
            ['Charges incurred · estimated', rupees(c.charges)], ['Estimated exit charges', rupees(c.estimated_exit_charges)], ['Today’s entries', c.filled_entries ?? '—'], ['Open positions', c.open_positions ?? '—'], ['Pending orders', c.pending_orders ?? '—']] as const).map(([label, value]) =>
            <div key={label}><dt className="text-muted-foreground">{label}</dt><dd className="font-medium tabular-nums">{value}</dd></div>)}
        </dl>
        <p className="text-xs text-muted-foreground">Charges include brokerage and statutory taxes; exit charges are estimates · {c.connection.mode === 'analyze' ? 'PAPER' : 'LIVE'}</p>
        <p className="text-xs text-muted-foreground">Account observed {new Date(c.captured_at * 1000).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' })} IST</p>
        {c.error && <p role="status" className="text-sm text-amber-700 dark:text-amber-400">{c.error}</p>}
      </CardContent>
    </Card>
  })}</div>
}
