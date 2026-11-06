import { rupees, type CombinedSnapshot } from '@/api/combinedTerminal'
import { Card, CardContent } from '@/components/ui/card'
export function CombinedSummary({ snapshot }: { snapshot: CombinedSnapshot }) {
  const s = snapshot.summary
  return <div><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[
    ['Realized net · estimated charges', s.realized_net], ['Estimated open net', s.estimated_open_net],
    ['Combined estimated net', s.estimated_total_net], ['Filled entries / maximum', `${snapshot.day.entries} / 3${snapshot.day.reserved_entries ? ` · ${snapshot.day.reserved_entries} pending` : ''}`],
  ].map(([label, value]) => <Card className="py-0" key={String(label)}><CardContent className="p-4"><p className="text-sm text-muted-foreground">{label}</p><p className="mt-2 text-xl font-semibold tabular-nums">{typeof value === 'string' ? value : rupees(value as number | null)}</p></CardContent></Card>)}</div>
    {!s.complete && <p role="status" className="mt-2 text-sm text-amber-700 dark:text-amber-400">{s.reason || 'Combined P&L unavailable until both accounts reconcile.'}</p>}
    <p className="mt-2 text-xs text-muted-foreground">Brokerage settings and statutory charges are included in estimates. Final charges reconcile against broker fills and contract notes.</p>
  </div>
}
