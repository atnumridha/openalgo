import type { DeltaBackendAutomation, DeltaChartState } from '@/api/deltaChart'
import { playAlertSound } from '@/lib/trading/alertDelivery'
export interface TradeAlert {
  id: string
  account: string
  symbol: string
  title: string
  message: string
  at: number
}
type StoredAlert = TradeAlert & { dismissed?: boolean }
export const TRADE_ALERT_EVENT = 'delta-trade-alerts'
const key = (a: string, s: string) =>
  `delta-chart:alerts:v1:${encodeURIComponent(a)}:${encodeURIComponent(s)}`
const failedWrites = new Set<string>()
const fallback = new Map<string, StoredAlert[]>()
function read(account: string, symbol: string): StoredAlert[] {
  const k = key(account, symbol)
  if (failedWrites.has(k)) return fallback.get(k) ?? []
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(k) ?? '[]')
    if (!Array.isArray(raw)) return []
    return raw.filter(
      (v): v is StoredAlert =>
        v &&
        typeof v.id === 'string' &&
        v.account === account &&
        v.symbol === symbol &&
        typeof v.title === 'string' &&
        typeof v.message === 'string' &&
        Number.isFinite(v.at)
    )
  } catch {
    return fallback.get(k) ?? []
  }
}
function write(account: string, symbol: string, values: StoredAlert[]) {
  fallback.set(key(account, symbol), values)
  try {
    localStorage.setItem(key(account, symbol), JSON.stringify(values))
    failedWrites.delete(key(account, symbol))
  } catch {
    failedWrites.add(key(account, symbol))
    /* Preserve this session's notices even if persistence fails. */
  }
  window.dispatchEvent(new Event(TRADE_ALERT_EVENT))
}
export function readTradeAlerts(account: string, symbol: string): TradeAlert[] {
  return read(account, symbol)
    .filter((v) => !v.dismissed)
    .map(({ dismissed: _, ...v }) => v)
}
export function publishTradeAlert(event: TradeAlert): boolean {
  const values = read(event.account, event.symbol)
  if (values.some((v) => v.id === event.id)) return false
  write(event.account, event.symbol, [...values, event])
  playAlertSound({ volume: 0.2, repeats: 1 })
  return true
}
export function dismissTradeAlert(account: string, symbol: string, id: string) {
  write(
    account,
    symbol,
    read(account, symbol).map((v) => (v.id === id ? { ...v, dismissed: true } : v))
  )
}
/** Poll snapshots must agree with new fill evidence; an ACK alone is never an exit. */
export function tradeFillAlerts(
  previous: DeltaChartState | null,
  current: DeltaChartState
): TradeAlert[] {
  if (!previous || previous.account !== current.account || previous.symbol !== current.symbol)
    return []
  const old = previous.position?.size ?? 0,
    next = current.position?.size ?? 0
  if (old === next || (old && next && Math.sign(old) !== Math.sign(next))) return []
  const ids = new Set(previous.fills.map((f) => f.id))
  const fills = current.fills.filter((f) => !ids.has(f.id))
  const reducing = Math.abs(next) < Math.abs(old)
  const side = reducing ? (old > 0 ? 'sell' : 'buy') : next > 0 ? 'buy' : 'sell'
  if (
    !fills.length ||
    fills.some((f) => f.side !== side || !Number.isSafeInteger(f.size) || f.size <= 0) ||
    fills.reduce((n, f) => n + f.size, 0) !== Math.abs(Math.abs(next) - Math.abs(old))
  )
    return []
  const title = reducing ? (next === 0 ? 'Position exited' : 'Position reduced') : 'Entry filled'
  return [
    {
      id: `fills:${fills
        .map((f) => f.id)
        .sort()
        .join(',')}`,
      account: current.account,
      symbol: current.symbol,
      title,
      message: `${current.symbol} · ${fills.reduce((n, f) => n + f.size, 0)} lots ${side === 'buy' ? 'bought' : 'sold'}. Confirmed by Delta fills and position.`,
      at: current.asof,
    },
  ]
}

/** Delta can return a fresh position before its cached fill history catches up. */
export function nextTradeAlertSnapshot(
  previous: DeltaChartState | null,
  current: DeltaChartState
): DeltaChartState {
  if (
    previous &&
    previous.account === current.account &&
    previous.symbol === current.symbol &&
    (previous.position?.size ?? 0) !== (current.position?.size ?? 0) &&
    current.asof - previous.asof <= 60 &&
    tradeFillAlerts(previous, current).length === 0
  )
    return previous
  return current
}

/** Durable backend event identity deduplicates polling without clearing recovery notices. */
export function backendProtectionAlerts(
  automation: DeltaBackendAutomation | null | undefined,
  account: string,
  symbol: string
): TradeAlert[] {
  if (
    !automation ||
    automation.owner !== 'backend' ||
    !account ||
    automation.account !== account ||
    !Array.isArray(automation.events)
  )
    return []
  return automation.events.flatMap((event) => {
    if (
      event.kind !== 'protection_blocked' ||
      !Number.isSafeInteger(event.id) ||
      event.id <= 0 ||
      !Number.isFinite(event.at) ||
      event.at <= 0
    )
      return []
    const { plan_id, message, plan_status } = event.details ?? {}
    if (typeof plan_id !== 'string' || !plan_id || typeof message !== 'string' || !message.trim())
      return []
    return [
      {
        id: `backend-protection:${plan_id}:${event.id}`,
        account,
        symbol,
        title: 'Protection blocked',
        message: `${automation.symbol} · Plan ${plan_id}${typeof plan_status === 'string' ? ` (${plan_status})` : ''}: ${message}`,
        at: event.at,
      },
    ]
  })
}
