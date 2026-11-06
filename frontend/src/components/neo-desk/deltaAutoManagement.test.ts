import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { deltaChartApi, type DeltaChartState } from '@/api/deltaChart'
import {
  buildDeltaAdoption,
  chooseDeltaManagement,
  useDeltaAutoManagement,
} from './deltaAutoManagement'
import type { DeltaRiskContext } from './deltaRisk'
vi.mock('@/api/deltaChart', () => ({ deltaChartApi: { manage: vi.fn() } }))
const context = (direction: DeltaRiskContext['direction'] = 'up'): DeltaRiskContext => ({
  symbol: 'BTCUSD',
  intervalSeconds: 60,
  sourceTime: 1940,
  observedAt: 2000,
  direction,
  bars: Array.from({ length: 15 }, (_, i) => ({
    time: 1100 + i * 60,
    open: 100,
    high: 102,
    low: 98,
    close: 100,
    volume: 1,
  })),
  support: 96,
  resistance: null,
})
const state = () =>
  ({
    connected: true,
    environment: 'india_prod',
    account: 'a',
    asof: 2000,
    symbol: 'BTCUSD',
    product: { id: 1, symbol: 'BTCUSD', tick_size: 0.5, contract_value: 1, max_leverage: 200 },
    ticker: { mark: 105, last: 105, bid: 104.5, ask: 105.5 },
    leverage: 5,
    orders: [],
    fills: [],
    position: { version: 'pv', size: 1, entry: 100, mark: 105, pnl: 5, liquidation: 50 },
    accounting: {
      currency: 'USD',
      balance: 100,
      available_balance: 80,
      position_gross_pnl: 5,
      position_entry_fees: 0.1,
      estimated_maker_exit_fee: 0.15,
      estimated_exit_fee: 0.15,
      exit_fee_basis: 'taker',
      position_net_after_fees: 4.75,
      fee_status: 'verified',
      message: '',
    },
    managed_plans: [
      {
        id: 'p1',
        status: 'active',
        message: 'Protected',
        side: 'buy',
        entry_order_id: 'entry1',
        entry_price: 100,
        initial_stop: 95,
        stop: 95,
        target: 110,
        source_time: 1880,
        interval_seconds: 60,
      },
    ],
  }) satisfies DeltaChartState
beforeEach(() => {
  vi.restoreAllMocks()
  vi.resetAllMocks()
  sessionStorage.clear()
  vi.mocked(deltaChartApi.manage).mockImplementation(async (body) => ({
    status: 'confirmed',
    message: 'Checked',
    plan_id: body.plan_id,
    plan_status: 'active',
  }))
})
it('tightens an owned active plan only with verified fee-aware favorable trend', () => {
  const snapshot = state()
  snapshot.product.tick_size = .005
  expect(chooseDeltaManagement(snapshot, context(), 2000)).toEqual({
    plan_id: 'p1',
    decision: 'trail',
    source_time: 1940,
    stop: 104.945,
  })
  const unknownFees = state()
  unknownFees.accounting.fee_status = 'incomplete' as 'verified'
  expect(chooseDeltaManagement(unknownFees, context(), 2000)?.decision).toBe('sync')
})
it('cancels only a completely unfilled owned entry on a newer opposite trend', () => {
  const s = state()
  s.position = null as unknown as typeof s.position
  s.managed_plans[0].status = 'awaiting_entry'
  s.orders = [
    {
      id: 'entry1',
      side: 'buy',
      size: 2,
      unfilled: 2,
      type: 'limit_order',
      kind: 'entry',
      price: 100,
      post_only: true,
      reduce_only: false,
      state: 'open',
      version: 'v1',
    },
  ] as unknown as typeof s.orders
  expect(chooseDeltaManagement(s, context('down'), 2000)?.decision).toBe('cancel_entry')
  s.orders = [{ ...s.orders[0], id: 'foreign' }] as unknown as typeof s.orders
  expect(chooseDeltaManagement(s, context('down'), 2000)?.decision).toBe('sync')
  s.managed_plans[0].status = 'partial_fill'
  expect(chooseDeltaManagement(s, context('down'), 2000)?.decision).toBe('sync')
})
it('requests a maker exit for an active owned position on opposite trend', () => {
  expect(chooseDeltaManagement(state(), context('down'), 2000)?.decision).toBe('exit')
})
it('does nothing for replay, wrong symbols, stale evidence, interval changes or blocked plans', () => {
  expect(chooseDeltaManagement(state(), { ...context(), symbol: 'ETHUSD' }, 2000)).toBeNull()
  expect(chooseDeltaManagement(state(), context(), 2200)).toBeNull()
  expect(chooseDeltaManagement(state(), { ...context(), intervalSeconds: 300 }, 2000)).toBeNull()
  const s = state()
  s.managed_plans[0].status = 'blocked'
  expect(chooseDeltaManagement(s, context(), 2000)).toBeNull()
  expect(chooseDeltaManagement({ ...state(), managed_plans: [] }, context(), 2000)).toBeNull()
})
it('runs once per broker snapshot and after uncertainty reconciles only with sync', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(2000 * 1000)
  vi.mocked(deltaChartApi.manage).mockRejectedValueOnce(new Error('timeout'))
  const s = state()
  const risk = context()
  const view = renderHook(({ snapshot }) => useDeltaAutoManagement(true, snapshot, risk), {
    initialProps: { snapshot: s },
  })
  await waitFor(() => expect(view.result.current.message).toMatch(/reconcil/))
  expect(deltaChartApi.manage).toHaveBeenCalledTimes(1)
  view.rerender({ snapshot: { ...s } })
  await act(async () => {
    await Promise.resolve()
  })
  expect(deltaChartApi.manage).toHaveBeenCalledTimes(1)
  view.unmount()
  const remount = renderHook(() => useDeltaAutoManagement(true, { ...s, asof: 2001 }, risk))
  await waitFor(() => expect(deltaChartApi.manage).toHaveBeenCalledTimes(2))
  expect(vi.mocked(deltaChartApi.manage).mock.calls[1][0]).toEqual({
    plan_id: 'p1',
    decision: 'sync',
    source_time: 1940,
  })
  remount.unmount()
})
it('never submits when disabled or management intent storage is unavailable', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(2000 * 1000)
  const view = renderHook(() => useDeltaAutoManagement(false, state(), context()))
  await act(async () => {
    await Promise.resolve()
  })
  expect(deltaChartApi.manage).not.toHaveBeenCalled()
  view.unmount()
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  const blocked = renderHook(() => useDeltaAutoManagement(true, state(), context()))
  await waitFor(() => expect(blocked.result.current.message).toMatch(/storage/))
  expect(deltaChartApi.manage).not.toHaveBeenCalled()
})
it('does not clear a newer remounted reconciliation intent with an older acknowledgement', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(2000 * 1000)
  const finishes: Array<
    (result: {
      status: 'confirmed'
      message: string
      plan_id: string
      plan_status: 'active'
    }) => void
  > = []
  vi.mocked(deltaChartApi.manage).mockImplementation(
    () => new Promise((resolve) => finishes.push(resolve))
  )
  const s = state()
  const first = renderHook(() => useDeltaAutoManagement(true, s, context()))
  await waitFor(() => expect(finishes).toHaveLength(1))
  first.unmount()
  const second = renderHook(() => useDeltaAutoManagement(true, { ...s, asof: 2001 }, context()))
  await waitFor(() => expect(finishes).toHaveLength(2))
  const key = 'delta-chart:manage:v1:a:BTCUSD:p1'
  const newer = sessionStorage.getItem(key)
  await act(async () => {
    finishes[0]({
      status: 'confirmed',
      message: 'Old accepted',
      plan_id: 'p1',
      plan_status: 'active',
    })
    await Promise.resolve()
  })
  expect(sessionStorage.getItem(key)).toBe(newer)
  await act(async () => {
    finishes[1]({
      status: 'confirmed',
      message: 'New accepted',
      plan_id: 'p1',
      plan_status: 'active',
    })
    await Promise.resolve()
  })
  expect(sessionStorage.getItem(key)).toBeNull()
  second.unmount()
})
it('builds explicit adoption with a tighter existing market SL and exact leg versions', () => {
  const s = state()
  s.orders = [
    {
      id: 'legacy-stop',
      side: 'sell',
      size: 1,
      unfilled: 1,
      type: 'market_order',
      kind: 'sl',
      price: 102,
      post_only: false,
      reduce_only: true,
      state: 'pending',
      version: 'sv1',
    },
  ] as unknown as typeof s.orders
  const plan = buildDeltaAdoption(s, context(), undefined, 2000)
  expect(plan?.protection.stop).toBe(102)
  expect(plan?.existingStop).toEqual({ id: 'legacy-stop', version: 'sv1' })
  expect(plan?.protection.target).toBeGreaterThan(s.position.mark)
  expect(
    buildDeltaAdoption({ ...s, orders: [...s.orders, ...s.orders] }, context(), undefined, 2000)
  ).toBeNull()
  expect(
    buildDeltaAdoption(
      { ...s, orders: [{ ...s.orders[0], price: null }] },
      context(),
      undefined,
      2000
    )
  ).toBeNull()
})
it('refuses adoption when helper target cannot clear the actual entry or existing stop is already beyond mark', () => {
  const s = state()
  s.position.entry = 140
  expect(buildDeltaAdoption(s, context(), undefined, 2000)).toBeNull()
  const protectedState = state()
  protectedState.orders = [
    {
      id: 'sl',
      side: 'sell',
      size: 1,
      unfilled: 1,
      type: 'market_order',
      kind: 'sl',
      price: 106,
      post_only: false,
      reduce_only: true,
      state: 'pending',
      version: 'sv1',
    },
  ] as unknown as typeof protectedState.orders
  expect(buildDeltaAdoption(protectedState, context(), undefined, 2000)).toBeNull()
})
it('binds adoption to fresh matching product, symbol, account and position snapshots', () => {
  expect(
    buildDeltaAdoption({ ...state(), symbol: 'ETHUSD' }, context(), undefined, 2000)
  ).toBeNull()
  expect(
    buildDeltaAdoption(
      { ...state(), product: { ...state().product, symbol: 'ETHUSD' } },
      context(),
      undefined,
      2000
    )
  ).toBeNull()
  expect(buildDeltaAdoption({ ...state(), account: '' }, context(), undefined, 2000)).toBeNull()
  expect(buildDeltaAdoption(state(), context(), undefined, 2011)).toBeNull()
  expect(
    buildDeltaAdoption(
      { ...state(), position: { ...state().position, version: '' } },
      context(),
      undefined,
      2000
    )
  ).toBeNull()
})
it('never widens an existing short SL during reviewed adoption', () => {
  const s = state()
  s.position = { ...s.position, size: -1, entry: 110 }
  s.orders = [
    {
      id: 'short-stop',
      side: 'buy',
      size: 1,
      unfilled: 1,
      type: 'market_order',
      kind: 'sl',
      price: 108,
      post_only: false,
      reduce_only: true,
      state: 'pending',
      version: 'sv1',
    },
  ] as unknown as typeof s.orders
  const risk = { ...context('down'), support: null, resistance: 109 }
  const plan = buildDeltaAdoption(s, risk, undefined, 2000)
  expect(plan?.protection.stop).toBe(108)
  expect(plan?.protection.stop).toBeLessThanOrEqual(108)
})

it('can protect a held position after price has moved beyond the new-entry chase limit', () => {
  const snapshot = state()
  expect(buildDeltaAdoption(snapshot, context(), undefined, 2000)?.protection.stop).toBeLessThan(
    snapshot.position.mark
  )
})

it('keeps an in-flight check busy while disabled for close review, then clears on acknowledgement', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(2000 * 1000)
  let finish!: (result: {
    status: 'confirmed'
    message: string
    plan_id: string
    plan_status: 'active'
  }) => void
  vi.mocked(deltaChartApi.manage).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const snapshot = state(),
    risk = context()
  const view = renderHook(({ enabled }) => useDeltaAutoManagement(enabled, snapshot, risk), {
    initialProps: { enabled: true },
  })
  await waitFor(() => expect(view.result.current.busy).toBe(true))
  view.rerender({ enabled: false })
  expect(view.result.current.busy).toBe(true)
  await act(async () => {
    finish({ status: 'confirmed', message: 'Checked', plan_id: 'p1', plan_status: 'active' })
    await Promise.resolve()
  })
  expect(view.result.current.busy).toBe(false)
  expect(deltaChartApi.manage).toHaveBeenCalledTimes(1)
})

it('uses the generic taker exit estimate for the fee-aware trailing threshold', () => {
  const snapshot = state()
  const takerState: DeltaChartState = {
    ...snapshot,
    accounting: { ...snapshot.accounting, estimated_exit_fee: 20, exit_fee_basis: 'taker' },
  }
  expect(chooseDeltaManagement(takerState, context(), 2000)?.decision).toBe('reduce_risk')
  takerState.accounting!.estimated_exit_fee = null
  expect(chooseDeltaManagement(takerState, context(), 2000)?.decision).toBe('sync')
})

it.each([
  'missing',
  'null',
  'wrong-basis',
  'missing-basis',
] as const)('does not trail with %s market-exit fee evidence', (mode) => {
  const snapshot: DeltaChartState = state()
  snapshot.accounting!.estimated_exit_fee = 0.15
  snapshot.accounting!.exit_fee_basis = 'taker'
  if (mode === 'missing') delete snapshot.accounting!.estimated_exit_fee
  if (mode === 'null') snapshot.accounting!.estimated_exit_fee = null
  if (mode === 'wrong-basis') snapshot.accounting!.exit_fee_basis = 'maker'
  if (mode === 'missing-basis') delete snapshot.accounting!.exit_fee_basis
  expect(chooseDeltaManagement(snapshot, context(), 2000)?.decision).toBe('sync')
})

it('softly reviews a verified fill near the scalper deadline but keeps a protected profitable aligned trend', () => {
  const s = state()
  const plan = { ...s.managed_plans[0], first_fill_at: 100 }
  expect(chooseDeltaManagement({ ...s, managed_plans: [plan] }, context(), 2000)?.decision).toBe(
    'exit'
  )
  expect(
    chooseDeltaManagement(
      {
        ...s,
        orders: [
          {
            id: 'verified-sl',
            kind: 'sl',
            type: 'market_order',
            reduce_only: true,
            side: 'sell',
            state: 'open',
            unfilled: Math.abs(s.position!.size),
            price: 101,
            size: Math.abs(s.position!.size),
            post_only: false,
            version: 's1',
          },
        ],
        managed_plans: [{ ...plan, stop: 101, stop_order_id: 'verified-sl' }],
      },
      context(),
      2000
    )?.decision
  ).not.toBe('exit')
  expect(
    chooseDeltaManagement(
      { ...s, symbol: 'XAUTUSD', managed_plans: [plan] },
      { ...context(), symbol: 'XAUTUSD' },
      2000
    )?.decision
  ).not.toBe('exit')
})
