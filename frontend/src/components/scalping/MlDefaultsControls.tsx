import type { MLPlan } from '@/api/scalping'
import { Input } from '@/components/ui/input'
import { mlDefaultsTicket, mlManualEntryBlock, type MLTicketContext } from '@/lib/scalpingMlDefaults'
import type { ScalpingAction } from '@/types/scalping'

export function MlDefaultsControls({data, action, context, mode, onAction}: {
  data?: MLPlan; action: ScalpingAction; context: MLTicketContext; mode: string
  onAction: (action: ScalpingAction) => void
}) {
  const ticket = mlDefaultsTicket(data, action, context)
  const blocked = mlManualEntryBlock(data, action, context)
  return <div className="w-full space-y-2 rounded-md border bg-muted/30 p-3" aria-label="ML auto-filled order ticket">
    <div className="flex flex-wrap items-end gap-3">
      <label className="space-y-1 text-xs">Preview side
        <select className="ml-2 rounded-md border bg-background p-2 text-sm" aria-label="ML preview side"
          value={action} onChange={e => onAction(e.target.value as ScalpingAction)}>
          <option value="BUY">LONG</option><option value="SELL">SHORT</option>
        </select>
      </label>
      <label className="space-y-1 text-xs">Maker entry
        <Input readOnly aria-label="ML maker entry price" className="w-32 font-mono" value={ticket?.entry.toFixed(2) ?? ''} placeholder="Waiting…" />
      </label>
      <label className="space-y-1 text-xs">SL price
        <Input readOnly aria-label="ML stop-loss price" className="w-32 font-mono" value={ticket?.stop.toFixed(2) ?? ''} placeholder="Waiting…" />
      </label>
      <label className="space-y-1 text-xs">Target after fees
        <Input readOnly aria-label="ML target price after fees" className="w-32 font-mono" value={ticket?.target.toFixed(2) ?? ''} placeholder="Waiting…" />
      </label>
    </div>
    <p className="text-xs">{blocked ?? `Manual entry ready (${mode === 'live' ? 'live' : 'paper'}). Buy uses LONG defaults; Sell uses SHORT defaults.`}</p>
    <p className="text-xs text-muted-foreground">ML guidance: {data?.action ?? 'unavailable'} — {data?.reason ?? 'Waiting for data.'} This guidance does not block your manual click.</p>
    <p className="text-xs text-muted-foreground">Auto-fill does not submit orders or edit existing positions. Fresh prices and risk checks still apply. Automated ML trading remains subject to qualification.</p>
  </div>
}
