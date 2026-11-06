import { useEffect, useState } from 'react'
import type { DeltaChartState } from '@/api/deltaChart'
import { isDeltaChartSymbol } from '../chart-toolkit/deltaProducts'
export interface DeltaMarkTick {
  symbol: string
  price: number
  published: number
  receivedAt: number
}
const positive = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n) && n > 0
export function decodeDeltaMark(
  input: unknown,
  symbol: string,
  now = Date.now()
): DeltaMarkTick | null {
  if (!input || typeof input !== 'object') return null
  const m = input as Record<string, unknown>
  if (m.type !== 'mark_price' || m.sy !== `MARK:${symbol}`) return null
  const price = Number(m.p),
    published = Number(m.ts) / 1e6
  if (
    !positive(price) ||
    !positive(published) ||
    now / 1000 - published > 5 ||
    published - now / 1000 > 5
  )
    return null
  return { symbol, price, published, receivedAt: now }
}
/** Display-only: never changes account asof, quantities, versions, balances or paid fees. */
export function revalueDeltaDisplay(
  state: DeltaChartState,
  tick: DeltaMarkTick | null,
  now = Date.now()
): DeltaChartState {
  const position = state.position,
    sizing = state.sizing,
    accounting = state.accounting
  if (
    !tick ||
    !state.connected ||
    state.environment !== 'india_prod' ||
    state.product.symbol !== state.symbol ||
    tick.symbol !== state.symbol ||
    !position ||
    !positive(Math.abs(position.size)) ||
    !positive(position.entry) ||
    !positive(state.product.contract_value) ||
    !positive(tick.price) ||
    !Number.isFinite(state.asof) ||
    now / 1000 - state.asof > 10 ||
    state.asof - now / 1000 > 5 ||
    now / 1000 - tick.published > 5 ||
    tick.published - now / 1000 > 5 ||
    tick.published < state.asof ||
    tick.receivedAt < state.asof * 1000 ||
    now - tick.receivedAt > 5000 ||
    tick.receivedAt - now > 5000 ||
    sizing?.currency !== 'USD' ||
    !Number.isFinite(sizing.maker_fee_rate) ||
    sizing.maker_fee_rate < 0 ||
    sizing.maker_fee_rate > 1 ||
    !Number.isFinite(sizing.fee_tax_rate) ||
    sizing.fee_tax_rate < 0 ||
    sizing.fee_tax_rate > 1 ||
    accounting?.currency !== 'USD'
  )
    return state
  const gross = (tick.price - position.entry) * position.size * state.product.contract_value
  const exit =
    Math.abs(position.size) *
    state.product.contract_value *
    tick.price *
    sizing.maker_fee_rate *
    (1 + sizing.fee_tax_rate)
  const marketBasis = accounting.exit_fee_basis === 'taker'
  const generic = accounting.estimated_exit_fee !== undefined
  const taker = sizing.taker_fee_rate
  const marketExit =
    typeof taker === 'number' && Number.isFinite(taker) && taker >= 0 && taker <= 1
      ? Math.abs(position.size) *
        state.product.contract_value *
        tick.price *
        taker *
        (1 + sizing.fee_tax_rate)
      : null
  const waived = typeof accounting.scalper_fee_valid_until === 'number' && now / 1000 < accounting.scalper_fee_valid_until
  const exitEstimate = generic && marketBasis ? (waived ? 0 : marketExit) : null
  const paid = accounting.position_entry_fees
  const net =
    accounting.fee_status === 'verified' &&
    typeof paid === 'number' &&
    Number.isFinite(paid) &&
    exitEstimate !== null
      ? gross - paid - exitEstimate
      : null
  if (![gross, exit].every(Number.isFinite) || (net !== null && !Number.isFinite(net))) return state
  return {
    ...state,
    ticker: { ...state.ticker, mark: tick.price },
    position: { ...position, mark: tick.price, pnl: gross },
    accounting: {
      ...accounting,
      position_gross_pnl: gross,
      estimated_maker_exit_fee: exit,
      estimated_exit_fee: exitEstimate,
      position_net_after_fees: net,
    },
  }
}
export function useDeltaMark(symbol: string, enabled: boolean) {
  const [tick, setTick] = useState<DeltaMarkTick | null>(null)
  useEffect(() => {
    setTick(null)
    if (!enabled || !isDeltaChartSymbol(symbol)) return
    let stopped = false,
      socket: WebSocket | undefined,
      reconnect: ReturnType<typeof setTimeout> | undefined,
      heartbeat: ReturnType<typeof setInterval> | undefined,
      retry = 1000,
      latest = 0
    const connect = () => {
      if (stopped) return
      try {
        socket = new WebSocket('wss://public-socket.india.delta.exchange')
      } catch {
        reconnect = setTimeout(connect, retry)
        retry = Math.min(30000, retry * 2)
        return
      }
      const ws = socket
      ws.onopen = () => {
        if (stopped) return
        retry = 1000
        ws.send(
          JSON.stringify({
            type: 'subscribe',
            payload: { channels: [{ name: 'mark_price', symbols: [`MARK:${symbol}`] }] },
          })
        )
        heartbeat = setInterval(() => {
          if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'ping' }))
        }, 30000)
      }
      ws.onmessage = (event) => {
        if (stopped) return
        try {
          const next = decodeDeltaMark(JSON.parse(String(event.data)), symbol)
          if (next && next.published > latest) {
            latest = next.published
            setTick(next)
          }
        } catch {
          /* malformed and control messages never become prices */
        }
      }
      ws.onerror = () => ws.close()
      ws.onclose = () => {
        if (heartbeat) clearInterval(heartbeat)
        setTick(null)
        if (!stopped) {
          reconnect = setTimeout(connect, retry)
          retry = Math.min(30000, retry * 2)
        }
      }
    }
    connect()
    return () => {
      stopped = true
      if (reconnect) clearTimeout(reconnect)
      if (heartbeat) clearInterval(heartbeat)
      socket?.close()
    }
  }, [symbol, enabled])
  return tick?.symbol === symbol ? tick : null
}
