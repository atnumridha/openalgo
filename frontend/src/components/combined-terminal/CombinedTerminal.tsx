import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { brokerName, combinedTerminalApi, rupees, terminalError } from '@/api/combinedTerminal'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import type { DeskMode, SetupMode, SetupStrategy } from '@/api/kotakAssistant'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { KotakAssistantChart } from '@/components/kotak-assistant/KotakAssistantChart'
import { SetupAssistant } from '@/components/kotak-assistant/SetupAssistant'
import { DailyDiscipline } from '@/components/kotak-assistant/DailyDiscipline'
import { LEVEL_COLORS } from '@/components/kotak-assistant/PriceLevels'
import { BrokerConnections } from './BrokerConnections'
import { BrokerTicket } from './BrokerTicket'
import { CombinedPositions } from './CombinedPositions'
import { CombinedSummary } from './CombinedSummary'
import { BrokerActivity } from './BrokerActivity'
import { synchronizedSnapshot } from './snapshotSync'

export function CombinedTerminal({ fallback = null }: { fallback?: ReactNode }) {
  const username = useAuthStore(s => s.user?.username)
  const appMode = useThemeStore(s => s.appMode)
  const mode: DeskMode = appMode === 'live' ? 'live' : 'analyze'
  const qc = useQueryClient()
  const [now, setNow] = useState(Date.now() / 1000)
  const [selected, setSelected] = useState('')
  const [underlying, setUnderlying] = useState('NIFTY')
  const [expiry, setExpiry] = useState('')
  const [symbol, setSymbol] = useState('')
  const [lots, setLots] = useState(1)
  const [ratio, setRatio] = useState(2)
  const [interval, setInterval] = useState('5m')
  const [strategy, setStrategy] = useState<SetupStrategy>('trend')
  const [signalMode, setSignalMode] = useState<SetupMode>('confirmed')
  const [contextId] = useState(() => crypto.randomUUID())
  const [notice, setNotice] = useState('')
  const [adoptVersion, setAdoptVersion] = useState(0)
  const [ticketValues, setTicketValues] = useState<{ scope: string; symbol: string; entry: number; sl: number; target: number } | null>(null)
  const config = useQuery({ queryKey: ['combined-config', username], queryFn: combinedTerminalApi.config, retry: false })
  const accounts = useQuery({ queryKey: ['combined-accounts', username, mode], queryFn: () => combinedTerminalApi.snapshot(mode), enabled: config.data?.enabled === true, refetchInterval: 1000, refetchIntervalInBackground: true, retry: false })
  const snapshot = accounts.data ? synchronizedSnapshot(accounts.data, now, accounts.isError) : undefined
  const connection = snapshot?.connections.find(c => c.connection.id === selected)
  const scope = connection ? `${connection.connection.id}:${connection.connection.account}:${mode}` : ''
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(timer) }, [])
  useEffect(() => {
    if (snapshot?.connections.some(c => c.connection.id === selected)) return
    let saved = ''
    try { saved = localStorage.getItem(`combined-broker:${username}:${mode}`) || '' } catch { /* memory-only selection */ }
    const preferred = snapshot?.connections.find(c => c.connection.id === saved) || snapshot?.connections.find(c => c.connection.broker === 'kotak') || snapshot?.connections[0]
    if (preferred) setSelected(preferred.connection.id)
  }, [snapshot?.connections, selected, username, mode])
  const marketQuery = useQuery({ queryKey: ['combined-market', username, scope, underlying, expiry, symbol, lots, ratio, strategy, signalMode],
    queryFn: () => combinedTerminalApi.market(selected, { underlying, ...(expiry ? { expiry } : {}), ...(symbol ? { symbol } : {}), lots, ratio, strategy, signal_mode: signalMode }),
    enabled: config.data?.enabled === true && !!connection, refetchInterval: 1000, retry: false,
    placeholderData: (previous, previousQuery) => previousQuery?.queryKey[2] === scope && previousQuery.queryKey[3] === underlying && (!expiry || previous?.expiry === expiry) && (!symbol || previous?.symbol === symbol || previous?.ce?.symbol === symbol || previous?.pe?.symbol === symbol) ? previous : undefined,
  })
  const market = marketQuery.data
  const ticketMarket = !marketQuery.isPlaceholderData && (!symbol || market?.symbol === symbol) ? market : undefined
  useEffect(() => { if (market?.expiry && !expiry) setExpiry(market.expiry); if (market?.symbol && !symbol) setSymbol(market.symbol) }, [market, expiry, symbol])
  const source = useMemo(() => ({ id: scope, getHistory: (s: string, e: string, i: string, d?: string) => combinedTerminalApi.chart(selected, s, e, i, d) }), [scope, selected])
  const changeBroker = (id: string) => {
    setSelected(id); setSymbol(''); setExpiry(''); setNotice(''); setTicketValues(null)
    try { localStorage.setItem(`combined-broker:${username}:${mode}`, id) } catch { /* memory-only selection */ }
    void combinedTerminalApi.select(contextId, id).catch(error => setNotice(terminalError(error)))
  }
  const onNotice = useCallback((value: string) => { setNotice(value); void qc.invalidateQueries({ queryKey: ['combined-accounts', username, mode] }) }, [qc, username, mode])
  const onValues = useCallback((values: { entry: number; sl: number; target: number }) => {
    setTicketValues(previous => previous?.scope === scope && previous.symbol === symbol && previous.entry === values.entry && previous.sl === values.sl && previous.target === values.target ? previous : { scope, symbol, ...values })
  }, [scope, symbol])
  if (config.isPending) return <p role="status" className="p-4 text-sm text-muted-foreground">Checking broker terminal configuration…</p>
  if (config.isError) return <div role="alert" className="p-4"><p>Combined terminal configuration unavailable.</p><Button variant="outline" onClick={() => void config.refetch()}>Retry configuration</Button>{fallback}</div>
  if (!config.data?.enabled) return <>{fallback}</>
  return <section aria-label="Kotak and Flattrade terminal" className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="text-2xl font-semibold">Indian options terminal</h1><p className="text-sm text-muted-foreground">Kotak Neo + Flattrade · choose the broker for each entry · {mode === 'live' ? 'LIVE' : 'PAPER'}</p></div><Button variant="outline" onClick={() => void accounts.refetch()}>Refresh accounts</Button></div>
    {accounts.isError && <p role="alert" className="text-sm text-destructive">{terminalError(accounts.error)} · saved positions may be stale.</p>}
    {snapshot && <><BrokerConnections connections={snapshot.connections} /><CombinedSummary snapshot={snapshot} />
      <DailyDiscipline brokerLabel="Kotak Neo + Flattrade" scope={`combined:${username}:${mode}`} discipline={snapshot.day} now={now} bookTime={snapshot.updated_at}
        error={snapshot.day.loss_reached || snapshot.day.profit_reached || snapshot.day.entries >= 3 ? null : snapshot.summary.reason}
        repeatInterval={snapshot.settings.reminder_seconds} onIntervalChange={seconds => { void combinedTerminalApi.configure(mode, seconds).then(() => accounts.refetch()).catch(error => setNotice(terminalError(error))) }} />
    </>}
    {(snapshot?.setup_required || snapshot?.connections.length === 0) && <Card className="py-0"><CardContent className="space-y-2 p-4"><h2 className="font-semibold">Connect the broker workers</h2><p className="text-sm">The combined terminal needs separate authenticated Kotak and Flattrade workers. Flattrade requires its client ID, API key, registered redirect URL and static IP; the secret alone cannot establish a connection.</p><p className="text-sm text-muted-foreground">Existing Kotak positions remain with their original controller.</p></CardContent></Card>}
    {connection && <><div className="flex flex-wrap items-end gap-3 rounded-lg border p-3">
      <label className="text-sm">Execution broker<select aria-label="Execution broker" value={selected} onChange={e => changeBroker(e.target.value)} className="mt-1 block h-11 rounded-md border bg-background px-3">{snapshot?.connections.map(c => <option value={c.connection.id} key={c.connection.id}>{brokerName(c.connection.broker)}</option>)}</select></label>
      <label className="text-sm">Index<select aria-label="Index" value={underlying} onChange={e => { setUnderlying(e.target.value); setExpiry(''); setSymbol('') }} className="mt-1 block h-11 rounded-md border bg-background px-3">{['NIFTY', 'BANKNIFTY', 'SENSEX'].map(u => <option key={u}>{u}</option>)}</select></label>
      <label className="text-sm">Expiry · nearest first<select aria-label="Expiry" value={expiry} onChange={e => { setExpiry(e.target.value); setSymbol('') }} className="mt-1 block h-11 rounded-md border bg-background px-3"><option value="">{marketQuery.isPending ? 'Loading expiries…' : 'Choose expiry'}</option>{market?.expiries.map(e => <option key={e}>{e}</option>)}</select></label>
      <label className="text-sm">Strike<select aria-label="Strike" value={market?.strike ?? ''} onChange={e => { const row = market?.chain?.chain.find(r => String(r.strike) === e.target.value); const leg = symbol.endsWith('PE') ? row?.pe : row?.ce; if (leg) setSymbol(leg.symbol) }} className="mt-1 block h-11 rounded-md border bg-background px-3"><option value="">Select strike</option>{market?.chain?.chain.map(r => <option key={r.strike} value={r.strike}>{r.strike}{r.strike === market.chain?.atm_strike ? ' · near ATM' : ''}</option>)}</select></label>
      <label className="text-sm">Chart timeframe<select aria-label="Chart timeframe" value={interval} onChange={e => setInterval(e.target.value)} className="mt-1 block h-11 rounded-md border bg-background px-3">{['1m', '5m', '15m'].map(i => <option key={i}>{i}</option>)}</select></label>
      <label className="text-sm">Reward multiple<select aria-label="Reward multiple" value={ratio} onChange={e => setRatio(Number(e.target.value))} className="mt-1 block h-11 rounded-md border bg-background px-3">{[1.5, 2, 3, 4, 5, 6].map(r => <option key={r} value={r}>1:{r}</option>)}</select></label>
      <p className="self-center text-sm">{underlying} {rupees(market?.index_quote.ltp)} · {brokerName(connection.connection.broker)} data</p>
    </div>
    {marketQuery.isError && <p role="status" className="text-sm text-amber-700 dark:text-amber-400">{terminalError(marketQuery.error)}</p>}
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]"><div className="min-w-0 space-y-4"><div className="grid gap-3 lg:grid-cols-2">{(['ce', 'pe'] as const).map(side => {
      const leg = market?.[side]
      if (!leg) return <div key={side} className="flex min-h-72 items-center justify-center rounded-lg border text-sm text-muted-foreground">Waiting for {side.toUpperCase()} chart from {brokerName(connection.connection.broker)}</div>
      const selectedLeg = leg.symbol === symbol
      const values = ticketValues?.scope === scope && ticketValues.symbol === leg.symbol ? ticketValues : null
      const owned = snapshot?.positions.find(p => p.connection_id === selected && p.symbol === leg.symbol && p.managed && p.quantity > 0)
      const levels = values && !owned ? [{ price: values.entry, title: 'Ticket entry', color: LEVEL_COLORS.entry }, { price: values.sl, title: 'Ticket SL', color: LEVEL_COLORS.stop }, { price: values.target, title: 'Ticket target', color: LEVEL_COLORS.target }].filter(l => l.price > 0) : []
      const quote = market.quotes[leg.symbol] || (selectedLeg ? market.quote || undefined : undefined)
      return <div key={`${scope}:${leg.symbol}`} className={`min-w-0 rounded-lg border p-2 ${selectedLeg ? 'ring-2 ring-primary' : ''}`} onMouseEnter={() => setSymbol(leg.symbol)}>
        <Button variant={selectedLeg ? 'default' : 'outline'} className="mb-2 min-h-11 w-full" onClick={() => setSymbol(leg.symbol)}>Select {side.toUpperCase()} · {market.strike} · {rupees(quote?.ltp)}</Button>
        <div className="h-[620px] min-w-0"><KotakAssistantChart symbol={leg.symbol} exchange={market.exchange} interval={interval} title={`${side.toUpperCase()} · ${market.strike} · ${brokerName(connection.connection.broker)}`} externalSource={source} externalQuote={quote} levels={levels} position={owned ? {
          status: owned.data_fresh ? 'open' : 'unavailable', currency: 'INR', entry: owned.average_entry ?? owned.entry, quantity: owned.quantity,
          gross: owned.gross_open ?? null, sl: owned.current_sl ?? null, target: owned.target ?? null,
          slGross: owned.current_sl != null && (owned.average_entry ?? owned.entry) != null ? (owned.current_sl - (owned.average_entry ?? owned.entry ?? 0)) * owned.quantity : null,
          targetGross: owned.target != null && (owned.average_entry ?? owned.entry) != null ? (owned.target - (owned.average_entry ?? owned.entry ?? 0)) * owned.quantity : null,
          protectionAvailable: (owned.current_sl ?? 0) > 0,
        } : undefined} /></div>
      </div>
    })}</div>
    <SetupAssistant setup={market?.setup} strategy={strategy} mode={signalMode} onStrategyChange={setStrategy} onModeChange={setSignalMode} now={now} onUseSetup={() => setAdoptVersion(v => v + 1)}
      selectedContract={ticketMarket?.symbol ? { symbol: ticketMarket.symbol, side: ticketMarket.symbol.endsWith('CE') ? 'CE' : 'PE', strike: ticketMarket.strike || 0, expiry: ticketMarket.expiry, source: brokerName(connection.connection.broker), quantity: lots * (ticketMarket.metadata?.lot || 0), entry: ticketMarket.template?.entry, sl: ticketMarket.template?.sl, target: ticketMarket.template?.target } : null}
      executionReadiness={[{ name: 'Selected broker', ready: connection.entry_ready && snapshot?.day.entry_allowed, reason: snapshot?.day.blocked_reason || connection.error || 'Manual entry available after broker preview' }]} />
    </div><BrokerTicket key={`${scope}:${symbol}`} connection={connection} market={ticketMarket} contextId={contextId} lots={lots} setLots={setLots} now={now} allowed={snapshot?.day.entry_allowed === true} blockedReason={snapshot?.day.blocked_reason} onNotice={onNotice} onValuesChange={onValues} adoptVersion={adoptVersion} /></div></>}
    {notice && <p role="status" className="rounded-md border p-3 text-sm">{notice}</p>}
    {snapshot && <><CombinedPositions positions={snapshot.positions} onNotice={onNotice} /><BrokerActivity snapshot={snapshot} /><details className="rounded-lg border p-4"><summary className="cursor-pointer font-medium">Trade history · {snapshot.history.length} saved across both brokers</summary><div className="mt-3 space-y-2">{snapshot.history.map((t, i) => <p key={`${t.trade_id}:${i}`} className="text-sm">{brokerName(t.broker)} · {t.symbol} · {t.status} · {rupees(t.net_open)}</p>)}{!snapshot.history.length && <p className="text-sm text-muted-foreground">No saved terminal trades observed.</p>}</div></details></>}
  </section>
}
