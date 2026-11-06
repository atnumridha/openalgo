import { brokerChartOrders } from './brokerChartOrders'
import { combinedBrokerGuide } from '../neo-desk/tradeGuidanceAdapters'
import type { GuideBrokerContext } from '../neo-desk/tradeGuidance'
import { DailyDiscipline } from '@/components/kotak-assistant/DailyDiscipline'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { combinedTerminalApi, brokerName, rupees, terminalError } from '@/api/combinedTerminal'
import type { DeskMode } from '@/api/kotakAssistant'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { Button } from '@/components/ui/button'
import { BrokerTicket } from './BrokerTicket'
import { CombinedPositions } from './CombinedPositions'
import { synchronizedSnapshot } from './snapshotSync'

export type CombinedChartLevels = {
  symbol: string
  exchange: string
  levels: Array<{ price: number; title: string; color: string }>
}
type Props = {
  symbol: string
  exchange: string
  onLevels?: (value: CombinedChartLevels | null) => void
  onGuidance?: (value: GuideBrokerContext | null) => void
}

export function combinedChartContext(symbol: string, exchange: string) {
  if (
    ['NSE_INDEX', 'BSE_INDEX'].includes(exchange) &&
    ['NIFTY', 'BANKNIFTY', 'SENSEX'].includes(symbol)
  )
    return { underlying: symbol, expiry: '', option: false }
  const option = /^(NIFTY|BANKNIFTY|SENSEX)(\d{2}[A-Z]{3}\d{2})\d+(?:CE|PE)$/.exec(symbol)
  if (!option || exchange !== (option[1] === 'SENSEX' ? 'BFO' : 'NFO')) return null
  return { underlying: option[1], expiry: option[2], option: true }
}

export function CombinedChartPanel(props: Props) {
  if (props.exchange === 'DELTA') return null
  const context = combinedChartContext(props.symbol, props.exchange) ?? { underlying: props.symbol, expiry: '', option: false, readOnly: true }
  return <Panel key={`${props.exchange}:${props.symbol}`} {...props} context={context} />
}

function Panel({
  symbol,
  exchange,
  onLevels,
  onGuidance,
  context,
}: Props & { context: NonNullable<ReturnType<typeof combinedChartContext>> & { readOnly?: boolean } }) {
  const username = useAuthStore((s) => s.user?.username)
  const appMode = useThemeStore((s) => s.appMode)
  const mode: DeskMode = appMode === 'live' ? 'live' : 'analyze'
  const qc = useQueryClient()
  const [now, setNow] = useState(() => Date.now() / 1000)
  const [expanded, setExpanded] = useState(true)
  const [selected, setSelected] = useState('')
  const [lots, setLots] = useState(1)
  const [guideValues, setGuideValues] = useState<{ scope: string; values: { entry: number; sl: number; target: number } } | null>(null)
  const [notice, setNotice] = useState('')
  const [contextId] = useState(() => crypto.randomUUID())
  const config = useQuery({
    queryKey: ['combined-config', username],
    queryFn: combinedTerminalApi.config,
    enabled: !!username,
    retry: false,
    staleTime: 10000,
  })
  const accounts = useQuery({
    queryKey: ['combined-accounts', username, mode],
    queryFn: () => combinedTerminalApi.snapshot(mode),
    enabled: !!username && config.data?.enabled === true,
    refetchInterval: 1000,
    refetchIntervalInBackground: true,
    retry: false,
  })
  const snapshot = useMemo(() => accounts.data
    ? synchronizedSnapshot(accounts.data, now, accounts.isError)
    : undefined, [accounts.data, now, accounts.isError])
  const connection = snapshot?.connections.find((c) => c.connection.id === selected)
  const scope = connection
    ? `${username}:${mode}:${connection.connection.id}:${connection.connection.account}`
    : ''
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => {
    if (snapshot?.connections.some((c) => c.connection.id === selected)) return
    let saved = ''
    try {
      saved = localStorage.getItem(`combined-broker:${username}:${mode}`) || ''
    } catch {
      /* memory-only selection */
    }
    const next =
      snapshot?.connections.find((c) => c.connection.id === saved) ||
      snapshot?.connections.find((c) => c.connection.broker === 'kotak') ||
      snapshot?.connections[0]
    if (next) setSelected(next.connection.id)
  }, [snapshot?.connections, selected, username, mode])
  const marketQuery = useQuery({
    queryKey: ['combined-chart-market', scope, symbol, exchange, lots],
    queryFn: () =>
      combinedTerminalApi.market(selected, {
        underlying: context.underlying,
        expiry: context.expiry,
        symbol,
        lots,
        ratio: 2,
        strategy: 'trend',
        signal_mode: 'confirmed',
      }),
    enabled: config.data?.enabled === true && !!connection?.books_complete && context.option,
    refetchInterval: 1000,
    retry: false,
  })
  const market =
    !marketQuery.isError &&
    marketQuery.data?.symbol === symbol &&
    marketQuery.data.exchange === exchange
      ? marketQuery.data
      : undefined
  const onGuideValues = useCallback((values: { entry: number; sl: number; target: number }) => {
    const scope = `${selected}:${symbol}:${exchange}`
    setGuideValues(old => old?.scope === scope && JSON.stringify(old.values) === JSON.stringify(values) ? old : { scope, values })
  }, [selected, symbol, exchange])
  const guide = useMemo(() => combinedBrokerGuide(snapshot, selected, symbol, exchange, market, lots,
    guideValues?.scope === `${selected}:${symbol}:${exchange}` ? guideValues.values : null),
    [snapshot, selected, symbol, exchange, market, lots, guideValues])
  useEffect(() => { onGuidance?.(guide) }, [onGuidance, guide])
  useEffect(() => { setGuideValues(null); return () => onGuidance?.(null) }, [selected, symbol, exchange, onGuidance])
  const positions =
    snapshot?.positions.filter((p) => p.symbol === symbol && p.exchange === exchange) || []
  const observation = useMemo(() => brokerChartOrders(snapshot, symbol, exchange, now), [snapshot, symbol, exchange, now])
  const levels = observation.levels
  useEffect(() => {
    onLevels?.({ symbol, exchange, levels })
    return () => onLevels?.(null)
  }, [onLevels, symbol, exchange, levels])
  const onNotice = useCallback(
    (value: string) => {
      setNotice(value)
      void qc.invalidateQueries({ queryKey: ['combined-accounts', username, mode] })
    },
    [qc, username, mode]
  )
  const changeBroker = (id: string) => {
    setSelected(id)
    setNotice('')
    try {
      localStorage.setItem(`combined-broker:${username}:${mode}`, id)
    } catch {
      /* memory-only */
    }
    void combinedTerminalApi.select(contextId, id).catch((error) => setNotice(terminalError(error)))
  }
  if (!username || config.isPending || config.data?.enabled === false) return null
  return (
    <aside
      aria-label="Combined broker orders"
      className={`${expanded ? 'w-[320px] max-w-[85vw]' : 'w-10'} shrink-0 border-l border-border bg-card text-card-foreground`}
    >
      <div className="flex h-10 items-center justify-between border-b px-2">
        {expanded && (
          <strong className="text-xs">
            Kotak + Flattrade · {mode === 'live' ? 'LIVE' : 'PAPER'}
          </strong>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="size-8 p-0"
          aria-label={expanded ? 'Collapse combined orders' : 'Expand combined orders'}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? (
            <ChevronRight aria-hidden="true" className="size-4" />
          ) : (
            <ChevronLeft aria-hidden="true" className="size-4" />
          )}
        </Button>
      </div>
      {snapshot && (
        <div className="[&>section]:hidden">
          <DailyDiscipline
            brokerLabel="Kotak Neo + Flattrade"
            scope={`combined:${username}:${mode}`}
            discipline={snapshot.day}
            now={now}
            bookTime={snapshot.updated_at}
            error={
              snapshot.day.loss_reached || snapshot.day.profit_reached || snapshot.day.entries >= 3
                ? null
                : snapshot.summary.reason
            }
            repeatInterval={snapshot.settings.reminder_seconds}
            onIntervalChange={(seconds) => {
              void combinedTerminalApi
                .configure(mode, seconds)
                .then(() => accounts.refetch())
                .catch((error) => setNotice(terminalError(error)))
            }}
          />
        </div>
      )}
      <div
        hidden={!expanded}
        className="max-h-[75vh] space-y-3 overflow-y-auto p-3 text-xs [&_.text-lg]:text-sm [&_input]:h-9 [&_button]:min-h-9 [&_.space-y-4]:space-y-2 [&_.p-4]:p-3"
      >
        {config.isError && (
          <p role="alert">
            Broker configuration unavailable.{' '}
            <button className="underline" onClick={() => void config.refetch()}>
              Retry
            </button>
          </p>
        )}
        {accounts.isPending && <p role="status">Checking broker accounts…</p>}
        {accounts.isError && (
          <p role="alert">{terminalError(accounts.error)} · last-known positions retained.</p>
        )}
        {snapshot?.setup_required && (
          <p role="status">
            Combined mode is enabled. Broker connections need setup or sign-in before orders can be
            placed.
          </p>
        )}
        {snapshot && <section aria-label="Live broker order detection" className="space-y-1 rounded border p-2">
          <p className="font-medium">{observation.checkedAt == null ? 'Broker orders not verified' : `${observation.orders.length} open broker ${observation.orders.length === 1 ? 'order' : 'orders'} on this chart`}</p>
          <p className="text-muted-foreground">{observation.checkedAt ? `Book checked ${new Date(observation.checkedAt * 1000).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' })} IST · refresh ~1s` : 'Waiting for a verified broker orderbook.'}</p>
          {!observation.complete && <p className="text-amber-600 dark:text-amber-400">Some broker data is unavailable. The count covers verified accounts only.</p>}
          {observation.orders.map(order => <p key={order.key} className="break-words">{order.name} · {order.side} {order.remaining ?? 'quantity unconfirmed'} · {order.kind}{order.price == null ? '' : ` ₹${order.price}`} · {order.status}</p>)}
          <p className="text-muted-foreground">Includes orders placed in the broker app. Lines match this symbol and exchange; no order is placed or adopted by detection.</p>
        </section>}
        {connection && (
          <>
            <label className="block">
              Order broker
              <select
                aria-label="Order broker"
                value={selected}
                onChange={(e) => changeBroker(e.target.value)}
                className="mt-1 h-9 w-full rounded border border-border bg-background px-2"
              >
                {snapshot?.connections.map((c) => (
                  <option key={c.connection.id} value={c.connection.id}>
                    {brokerName(c.connection.broker)}
                  </option>
                ))}
              </select>
            </label>
            <dl className="grid grid-cols-2 gap-2 rounded border p-2">
              <div>
                <dt className="text-muted-foreground">Available funds</dt>
                <dd className="font-semibold tabular-nums">
                  {rupees(connection.funds?.availablecash)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Est. total net</dt>
                <dd className="font-semibold tabular-nums">
                  {rupees(connection.estimated_total_net)}
                </dd>
              </div>
            </dl>
            <p
              role="status"
              className={
                connection.error ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'
              }
            >
              {connection.error || `${brokerName(connection.connection.broker)} account verified`}
            </p>
            <p className="text-muted-foreground">
              {snapshot?.day.count_verified === false
                ? 'Daily entry count pending · maximum 3 entries.'
                : `${snapshot?.day.entries ?? '—'} / ${snapshot?.day.max_entries ?? 3} daily entries across both accounts.`}{' '}
              SL and exits remain available when entries are paused.
            </p>
            <p className="text-muted-foreground">
              Daily policy · +₹2,000 profit reminder · −₹1,000 loss limit.
            </p>
            {!context.option ? (
              <p>
                {context.readOnly ? 'Read-only broker order view. This instrument has no option order ticket here.' : 'Choose a CE or PE contract in chart Options to place an order. Option levels appear only on that option chart.'}
              </p>
            ) : (
              <>
                <p className="break-all font-medium">
                  {symbol} · {exchange}
                </p>
                {marketQuery.isError && (
                  <p role="status" className="text-amber-600 dark:text-amber-400">
                    {terminalError(marketQuery.error)}
                  </p>
                )}
                <BrokerTicket
                  key={`${scope}:${symbol}`}
                  connection={connection}
                  market={market}
                  contextId={contextId}
                  lots={lots}
                  setLots={setLots}
                  now={now}
                  allowed={
                    snapshot?.day.entry_allowed === true &&
                    !accounts.isError &&
                    !marketQuery.isError
                  }
                  blockedReason={snapshot?.day.blocked_reason}
                  onNotice={onNotice}
                  onValuesChange={onGuideValues}
                />
                <p className="text-muted-foreground">
                  {brokerName(connection.connection.broker)} quotes are checked for this order. SL
                  is a broker stop-limit; the target is monitored by the server. An exit stays
                  pending until filled.
                </p>
              </>
            )}
          </>
        )}
        {notice && (
          <div role="status" aria-live="polite" className="relative rounded border p-3 pr-8">
            {notice}
            <button
              aria-label="Dismiss broker alert"
              className="absolute right-1 top-1 rounded p-1 focus-visible:outline"
              onClick={() => setNotice('')}
            >
              <X aria-hidden="true" className="size-3" />
            </button>
          </div>
        )}
        {!context.readOnly && !!positions.length && <CombinedPositions positions={positions} onNotice={onNotice} />}
        {snapshot && (
          <details>
            <summary className="cursor-pointer py-2 font-medium">
              Orders and fills for this chart
            </summary>
            <div className="space-y-2">
              {(snapshot.orders || [])
                .filter(
                  (row) =>
                    row.connection_id === selected &&
                    row.symbol === symbol &&
                    row.exchange === exchange
                )
                .slice(0, 12)
                .map((row, i) => (
                  <p key={String(row.order_key || i)}>
                    {String(row.action || '')} · {String(row.filled_quantity ?? 0)}/
                    {String(row.quantity ?? '—')} · {String(row.order_status || 'unknown')}
                  </p>
                ))}
              {snapshot.fills
                .filter(
                  (row) =>
                    row.connection_id === selected &&
                    row.symbol === symbol &&
                    row.exchange === exchange
                )
                .slice(-8)
                .reverse()
                .map((row, i) => (
                  <p key={String(row.fill_id || i)}>
                    {String(row.action || '')} {String(row.quantity ?? '')} @{' '}
                    {rupees(Number(row.average_price))}
                  </p>
                ))}
              <p className="text-muted-foreground">
                Refreshes every second. Manual order controls; no automatic entries.
              </p>
            </div>
          </details>
        )}
      </div>
    </aside>
  )
}
