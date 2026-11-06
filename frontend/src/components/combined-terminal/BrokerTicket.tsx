import { useEffect, useRef, useState } from 'react'
import { brokerName, combinedTerminalApi, rupees, terminalError, type ConnectionState, type EntryPreview, type MarketSnapshot } from '@/api/combinedTerminal'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
export function BrokerTicket({ connection, market, contextId, lots, setLots, allowed, blockedReason, now, onNotice, onValuesChange, adoptVersion = 0 }: {
  connection: ConnectionState; market?: MarketSnapshot; contextId: string; lots: number; setLots: (value: number) => void; allowed: boolean; blockedReason?: string | null; now: number; onNotice: (value: string) => void; onValuesChange?: (values: { entry: number; sl: number; target: number }) => void; adoptVersion?: number
}) {
  const name = brokerName(connection.connection.broker)
  const [form, setForm] = useState({ entry: '', sl: '', target: '', edited: false })
  const [preview, setPreview] = useState<EntryPreview | null>(null)
  const [phase, setPhase] = useState<'idle' | 'reviewing' | 'sending' | 'submitted'>('idle')
  const [message, setMessage] = useState('')
  const operation = useRef('')
  const seq = useRef(0)
  const latest = useRef('')
  const formKey = JSON.stringify([connection.connection.id, market?.symbol, lots, form.entry, form.sl, form.target])
  latest.current = formKey
  useEffect(() => () => { seq.current++ }, [])
  useEffect(() => {
    if (!market?.symbol) return
    setForm(prev => prev.edited ? prev : { entry: String(market.template?.entry ?? market.quote?.ask ?? ''), sl: String(market.template?.sl ?? ''), target: String(market.template?.target ?? ''), edited: false })
  }, [market])
  useEffect(() => { onValuesChange?.({ entry: Number(form.entry), sl: Number(form.sl), target: Number(form.target) }) }, [form.entry, form.sl, form.target, onValuesChange])
  useEffect(() => {
    if (adoptVersion && market?.template?.entry) {
      seq.current++; setPreview(null); setPhase('idle'); setForm({ entry: String(market.template.entry), sl: String(market.template.sl ?? ''), target: String(market.template.target ?? ''), edited: true })
    }
  // Adoption is an explicit user action, not a quote-refresh effect.
  // biome-ignore lint/correctness/useExhaustiveDependencies: only re-adopt on the explicit counter
  }, [adoptVersion])
  const edit = (key: 'entry' | 'sl' | 'target', value: string) => { seq.current++; setPreview(null); setPhase('idle'); setForm(p => ({ ...p, [key]: value, edited: true })) }
  const q = market?.quote
  const fresh = q != null && q.time > 0 && now - q.time >= -1 && now - q.time <= 5 && (q.ask ?? 0) > 0
  const valid = !!market?.metadata && !!market.symbol && Number(form.sl) > 0 && Number(form.sl) < Number(form.entry) && Number(form.target) > Number(form.entry)
  const eligible = allowed && connection.entry_ready && fresh && valid && phase !== 'submitted'
  const review = async () => {
    if (!eligible || !market?.metadata) return
    const ownSeq = ++seq.current, key = latest.current
    setForm(p => ({ ...p, edited: true })); setPhase('reviewing'); setPreview(null); setMessage('')
    try {
      const result = await combinedTerminalApi.preview(connection.connection.id, { context_id: contextId, symbol: market.symbol, exchange: market.exchange, product: 'MIS', quantity: lots * market.metadata.lot,
        entry: Number(form.entry), sl: Number(form.sl), target: Number(form.target), manual_entry: true, auto_target: true, auto_risk: true })
      if (ownSeq !== seq.current || key !== latest.current || result.connection.id !== connection.connection.id) return
      operation.current = crypto.randomUUID(); setPreview(result)
    } catch (error) { if (ownSeq === seq.current) setMessage(terminalError(error)) }
    finally { if (ownSeq === seq.current) setPhase('idle') }
  }
  const buy = async () => {
    if (!eligible || !preview || preview.expires <= now || !operation.current) return
    setPhase('sending')
    try {
      const result = await combinedTerminalApi.enter(preview.preview_id, operation.current, connection.connection.id)
      setPhase(result.state === 'unknown' ? 'submitted' : 'idle'); setPreview(null)
      const text = result.state === 'unknown' ? `${name} entry outcome unknown; monitoring the original intent. Do not submit a replacement.` : `${name} entry ${result.state}; watch fills and accepted protection below.`
      setMessage(''); onNotice(text)
     } catch (error) {
      const response = error as { response?: { data?: { submission?: string } } }
      const notSubmitted = response.response?.data?.submission === 'not_submitted'
      setPhase(notSubmitted ? 'idle' : 'submitted'); setPreview(null)
      setMessage(notSubmitted ? `${terminalError(error)} · no order submitted; review again.` : `${terminalError(error)} · outcome needs reconciliation; no automatic retry.`)
    }
  }
  return <Card className="py-0"><CardContent className="space-y-4 p-4"><div><h2 className="text-lg font-semibold">Order ticket · {name}</h2><p className="text-sm text-muted-foreground">{market?.symbol || 'Select an available contract'} · {connection.connection.mode === 'live' ? 'LIVE' : 'PAPER'}</p></div>
    <label className="block text-sm">Lots<input aria-label="Lots" type="number" min="1" max={market?.metadata ? Math.floor(market.metadata.freeze / market.metadata.lot) : 1} value={lots} onChange={e => { seq.current++; setPreview(null); setPhase('idle'); setLots(Math.max(1, Number(e.target.value) || 1)) }} className="mt-1 h-11 w-full rounded-md border bg-background px-3" /></label>
    {(['entry', 'sl', 'target'] as const).map((field, i) => <label key={field} className="block text-sm">{['Entry price ₹', 'Stop loss trigger ₹', 'Profit target ₹'][i]}<input aria-label={['Entry price ₹', 'Stop loss trigger ₹', 'Profit target ₹'][i]} type="number" min="0" step={market?.metadata?.tick || .05} value={form[field]} onChange={e => edit(field, e.target.value)} className="mt-1 h-11 w-full rounded-md border bg-background px-3 tabular-nums" /></label>)}
    <Button variant="outline" className="w-full" disabled={!market?.template?.entry} onClick={() => { seq.current++; setPreview(null); setPhase('idle'); setForm({ entry: String(market?.template?.entry ?? ''), sl: String(market?.template?.sl ?? ''), target: String(market?.template?.target ?? ''), edited: true }) }}>Use current premium plan</Button>
    <p className="text-sm text-muted-foreground">{lots * (market?.metadata?.lot || 0)} units · current ask {rupees(q?.ask)} · {q?.source || 'Quote unavailable'}</p>
    {preview && <div className="rounded-md border p-3 text-sm"><p>Estimated risk {rupees(preview.plan.risk)} · reward {rupees(preview.plan.reward)}</p><p>Estimated charges {rupees(preview.plan.costs)} · net R:R 1:{preview.plan.net_rr ?? '—'}</p><p>{preview.expires > now ? `Preview expires in ${Math.ceil(preview.expires - now)}s` : 'Preview expired · review again'}</p></div>}
    <Button className="min-h-11 w-full" disabled={!eligible || phase === 'reviewing' || phase === 'sending'} onClick={() => void review()}>{phase === 'reviewing' ? 'Checking selected broker…' : `Review ${name} order`}</Button>
    {preview && preview.connection.id === connection.connection.id && <Button className="min-h-11 w-full" disabled={!eligible || preview.expires <= now || phase === 'sending'} onClick={() => void buy()}>Buy {lots} {lots === 1 ? 'lot' : 'lots'} on {name}</Button>}
    {(!allowed || !connection.entry_ready || !fresh) && <p role="status" className="text-sm text-amber-700 dark:text-amber-400">{blockedReason || connection.error || 'Fresh selected-broker quote required'}</p>}
    {message && <p role="status" className="text-sm">{message}</p>}
    <p className="text-xs text-muted-foreground">Signals are advisory. Review and Buy are manual actions. Planned risk includes estimated costs; execution gaps can exceed it.</p>
  </CardContent></Card>
}
