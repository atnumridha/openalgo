import { describe, expect, it } from 'vitest'
import type { DeltaChartState } from '@/api/deltaChart'
import { decodeDeltaMark, revalueDeltaDisplay } from './deltaLiveValuation'
const now = 1793525400000
const base = {
  connected: true,
  environment: 'india_prod',
  symbol: 'BTCUSD',
  account: 'a',
  asof: now / 1000 - 1,
  product: { symbol: 'BTCUSD', contract_value: 0.001 },
  ticker: { mark: 78000 },
  position: { size: 4, entry: 77976.5, mark: 78000, pnl: 0.094, version: 'owned' },
  sizing: { currency: 'USD', maker_fee_rate: 0.0002, taker_fee_rate: 0.0002, fee_tax_rate: 0.18 },
  accounting: {
    currency: 'USD',
    fee_status: 'verified',
    estimated_exit_fee: 0.1,
    exit_fee_basis: 'taker',
    position_entry_fees: 0.07360982,
    balance: 7,
    available_balance: 1,
  },
} as DeltaChartState
const tick = { symbol: 'BTCUSD', price: 78010, published: now / 1000, receivedAt: now }
describe('live display valuation', () => {
  it('updates long/short P&L and exit estimate, leaves actual fees, balances, versions and source snapshot unchanged', () => {
    const next = revalueDeltaDisplay(base, tick, now)
    expect(next.position!.pnl).toBeCloseTo(0.134, 10)
    expect(next.accounting!.estimated_maker_exit_fee).toBeCloseTo(
      4 * 0.001 * 78010 * 0.0002 * 1.18,
      12
    )
    expect(next.accounting!.position_net_after_fees).toBeCloseTo(
      0.134 - 0.07360982 - 4 * 0.001 * 78010 * 0.0002 * 1.18,
      12
    )
    expect(next.accounting!.position_entry_fees).toBe(base.accounting!.position_entry_fees)
    expect(next.accounting!.balance).toBe(7)
    expect(next.asof).toBe(base.asof)
    expect(next.position!.version).toBe('owned')
    expect(base.position!.mark).toBe(78000)
    expect(
      revalueDeltaDisplay({ ...base, position: { ...base.position!, size: -4 } }, tick, now)
        .position!.pnl
    ).toBeCloseTo(-0.134, 10)
  })
  it('never revalues stale, future, mismatched, disconnected, flat or unverified fee evidence', () => {
    for (const bad of [
      { ...tick, symbol: 'ETHUSD' },
      { ...tick, published: now / 1000 - 6 },
      { ...tick, published: now / 1000 + 6 },
      { ...tick, receivedAt: now - 6000 },
      { ...tick, price: NaN },
    ])
      expect(revalueDeltaDisplay(base, bad, now)).toBe(base)
    for (const bad of [
      { ...base, asof: now / 1000 - 11 },
      { ...base, connected: false },
      { ...base, position: null },
      { ...base, sizing: null },
    ])
      expect(revalueDeltaDisplay(bad, tick, now)).toBe(bad)
    const incomplete = {
      ...base,
      accounting: {
        ...base.accounting!,
        fee_status: 'incomplete' as const,
        position_entry_fees: null,
      },
    }
    expect(
      revalueDeltaDisplay(incomplete, tick, now).accounting!.position_net_after_fees
    ).toBeNull()
  })
  it('rejects old marks relative to the broker snapshot and marks received before current position snapshot', () => {
    expect(revalueDeltaDisplay(base, { ...tick, published: base.asof - 1 }, now)).toBe(base)
    expect(revalueDeltaDisplay(base, { ...tick, receivedAt: (base.asof - 1) * 1000 }, now)).toBe(
      base
    )
  })
  it('decodes exact-symbol compact mark messages with exchange microsecond timestamps only', () => {
    expect(
      decodeDeltaMark(
        { type: 'mark_price', sy: 'MARK:BTCUSD', p: '78010', ts: now * 1000 },
        'BTCUSD',
        now
      )
    ).toEqual(tick)
    for (const m of [
      { type: 'ticker', sy: 'MARK:BTCUSD', p: 78010, ts: now * 1000 },
      { type: 'mark_price', sy: 'MARK:ETHUSD', p: 78010, ts: now * 1000 },
      { type: 'mark_price', sy: 'MARK:BTCUSD', p: -1, ts: now * 1000 },
      { type: 'mark_price', sy: 'MARK:BTCUSD', p: 78010, ts: now },
    ])
      expect(decodeDeltaMark(m, 'BTCUSD', now)).toBeNull()
  })
})

import { act, renderHook } from '@testing-library/react'
import { vi } from 'vitest'
import { useDeltaMark } from './deltaLiveValuation'
it('subscribes publicly, ignores out-of-order/wrong symbols, clears disconnected ticks and stops on unmount', () => {
  vi.useFakeTimers()
  vi.setSystemTime(now)
  class Socket {
    static instances: Socket[] = []
    readyState = 1
    send = vi.fn()
    close = vi.fn()
    onopen?: () => void
    onmessage?: (event: { data: string }) => void
    onclose?: () => void
    constructor(public url: string) {
      Socket.instances.push(this)
    }
  }
  vi.stubGlobal('WebSocket', Socket)
  try {
    const { result, unmount } = renderHook(() => useDeltaMark('BTCUSD', true))
    const ws = Socket.instances[0]
    act(() => ws.onopen?.())
    expect(ws.url).toBe('wss://public-socket.india.delta.exchange')
    expect(JSON.parse(ws.send.mock.calls[0][0])).toEqual({
      type: 'subscribe',
      payload: { channels: [{ name: 'mark_price', symbols: ['MARK:BTCUSD'] }] },
    })
    const message = (p: number, ts: number, sy = 'MARK:BTCUSD') =>
      act(() => ws.onmessage?.({ data: JSON.stringify({ type: 'mark_price', sy, p, ts }) }))
    message(78010, now * 1000)
    expect(result.current?.price).toBe(78010)
    message(1, (now - 1000) * 1000)
    message(2, now * 1000, 'MARK:ETHUSD')
    expect(result.current?.price).toBe(78010)
    act(() => ws.onclose?.())
    expect(result.current).toBeNull()
    unmount()
    act(() => vi.advanceTimersByTime(30000))
    expect(Socket.instances).toHaveLength(1)
    expect(ws.close).toHaveBeenCalled()
  } finally {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  }
})
it('revalues market-exit net using taker fees and preserves genuine maker estimate for targets', () => {
  const market = {
    ...base,
    sizing: { ...base.sizing!, taker_fee_rate: 0.0005 },
    accounting: { ...base.accounting!, estimated_exit_fee: 0.1, exit_fee_basis: 'taker' as const },
  }
  const next = revalueDeltaDisplay(market, tick, now)
  const fee = 4 * 0.001 * 78010 * 0.0005 * 1.18
  expect(next.accounting!.estimated_exit_fee).toBeCloseTo(fee, 12)
  expect(next.accounting!.estimated_maker_exit_fee).toBeCloseTo(
    4 * 0.001 * 78010 * 0.0002 * 1.18,
    12
  )
  expect(next.accounting!.position_net_after_fees).toBeCloseTo(0.134 - 0.07360982 - fee, 12)
  const unknown = {
    ...market,
    sizing: { ...market.sizing, taker_fee_rate: undefined },
    accounting: { ...market.accounting, estimated_exit_fee: null },
  }
  const missing = revalueDeltaDisplay(unknown, tick, now)
  expect(missing.accounting!.estimated_exit_fee).toBeNull()
  expect(missing.accounting!.position_net_after_fees).toBeNull()
})

it('does not substitute maker fees when market fee basis is absent', () => {
  const legacy = {
    ...base,
    accounting: { ...base.accounting!, estimated_exit_fee: undefined, exit_fee_basis: undefined },
  }
  const next = revalueDeltaDisplay(legacy, tick, now)
  expect(next.accounting!.estimated_exit_fee).toBeNull()
  expect(next.accounting!.position_net_after_fees).toBeNull()
})
