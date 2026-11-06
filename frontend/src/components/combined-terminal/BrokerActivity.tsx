import { brokerName, rupees, type CombinedSnapshot } from '@/api/combinedTerminal'
const terminal = new Set(['complete', 'completed', 'cancelled', 'canceled', 'rejected'])
function stamp(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? new Date(value * 1000).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' IST' : 'Time unavailable'
}
export function BrokerActivity({ snapshot }: { snapshot: CombinedSnapshot }) {
  const fills = [...snapshot.fills].sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0)).slice(0, 100)
  const orders = (snapshot.orders || []).filter(o => !terminal.has(String(o.order_status).toLowerCase()))
  return <section aria-label="Latest broker fills" className="space-y-3 rounded-lg border p-4">
    <h2 className="text-lg font-semibold">Latest broker fills</h2>
    <p className="text-sm text-muted-foreground">Both broker accounts, including trades made outside this terminal. Partial fills are individual executions; daily entry counts group them by order.</p>
    {!snapshot.summary.complete && <p role="status" className="text-sm text-amber-700 dark:text-amber-400">Some account data is unavailable. These are observed fills; missing trades are not assumed to be zero.</p>}
    <div className="max-h-80 overflow-auto"><table className="w-full text-left text-sm">
      <caption className="sr-only">Latest observed executions from Kotak Neo and Flattrade</caption>
      <thead><tr className="border-b">{['Broker / time', 'Symbol', 'Side', 'Quantity', 'Fill price'].map(h => <th key={h} scope="col" className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
      <tbody>{fills.map((f, i) => <tr className="border-b last:border-0" key={String(f.fill_id || `${f.connection_id}:${f.tradeid}:${i}`)}>
        <td className="px-2 py-2"><strong>{brokerName(String(f.broker))}</strong><p className="text-xs text-muted-foreground">{stamp(f.timestamp)}</p></td>
        <td className="px-2 py-2">{String(f.symbol || '—')}</td><td className="px-2 py-2">{String(f.action || '—')}</td>
        <td className="px-2 py-2 tabular-nums">{String(f.quantity ?? '—')}</td><td className="px-2 py-2 tabular-nums">{rupees(typeof f.average_price === 'number' ? f.average_price : Number(f.average_price))}</td>
      </tr>)}</tbody>
    </table>{!fills.length && <p className="py-3 text-sm text-muted-foreground">No broker fills observed yet.</p>}</div>
    <details className="rounded-md border p-3"><summary className="cursor-pointer font-medium">Working broker orders · {orders.length}</summary><div className="mt-3 space-y-2">{orders.map((o, i) => <p className="text-sm" key={String(o.order_key || i)}>{brokerName(String(o.broker))} · {String(o.symbol || '—')} · {String(o.action || '—')} · {String(o.filled_quantity ?? 0)} / {String(o.quantity ?? '—')} filled · {String(o.order_status || 'unknown')}{o.data_fresh === false ? ' · last known' : ''}</p>)}{!orders.length && <p className="text-sm text-muted-foreground">No working orders observed.</p>}</div></details>
  </section>
}
