import { describe, expect, it } from 'vitest'
import type { LegState, Order, StrategyEvent } from '@/types/strategy_module'
import {
  confirmedSignalMarkers,
  fillMarkers,
  legLevels,
  signalMarker,
  snapToCandle,
  visibleLogicalRange,
} from './strategyChartMarkers'

const INTERVAL = 300

function order(overrides: Partial<Order>): Order {
  return {
    id: 1,
    run_id: 9,
    leg_id: 1,
    kind: 'entry',
    broker_order_id: '1',
    position_ref: null,
    symbol: 'NIFTY29SEP2622750CE',
    exchange: 'NFO',
    action: 'BUY',
    qty: 65,
    pricetype: 'LIMIT',
    price: 100,
    trigger_price: 0,
    status: 'complete',
    placed_at: '2026-09-28T09:20:00+05:30',
    filled_at: '2026-09-28T09:20:10+05:30',
    avg_fill_price: 101.5,
    filled_qty: 65,
    reject_reason: null,
    ...overrides,
  }
}

function event(payload: Record<string, unknown>, message = 'Fresh confirmed setup'): StrategyEvent {
  return {
    id: 8,
    run_id: null,
    strategy_id: 13,
    ts: '2026-09-28T09:20:00+05:30',
    kind: 'signal_evaluation',
    severity: 'info',
    leg_id: null,
    message,
    payload,
  }
}

describe('strategyChartMarkers', () => {
  it('plots BUY at a long fill and SELL at an exit fill', () => {
    const markers = fillMarkers(
      [
        order({ id: 1, action: 'BUY', kind: 'entry', avg_fill_price: 101.5 }),
        order({
          id: 2,
          action: 'SELL',
          kind: 'exit_target',
          filled_at: '2026-09-28T09:35:10+05:30',
          avg_fill_price: 130,
        }),
      ],
      INTERVAL
    )
    expect(markers.map((m) => m.kind)).toEqual(['buy', 'sell'])
    expect(markers[0].label).toBe('BUY')
    expect(markers[1].label).toBe('EXIT SELL')
    expect(markers[0].price).toBe(101.5)
  })

  it('uses checkpoint stop and target prices, not configured sl_pts', () => {
    const legs: LegState[] = [
      {
        leg_id: 1,
        position: 'B',
        symbol: 'NIFTY29SEP2622750CE',
        exchange: 'NFO',
        lots: 1,
        qty: 65,
        entry_order_id: 1,
        entry_status: 'complete',
        entry_avg: 101.5,
        exit_order_id: null,
        exit_kind: null,
        exit_avg: null,
        ltp: 110,
        mtm: 500,
        realized_pnl: 0,
        status: 'open',
        tick_source: 'quote',
        sl_pts: 20,
        target_pts: 35,
        trail_x: 0,
        trail_y: 0,
        effective_sl: 88.25,
        effective_target: 140,
        trail_active: false,
        highest_price: 110,
        lowest_price: 101.5,
      },
    ]
    const levels = legLevels(legs)
    expect(levels.find((l) => l.kind === 'sl')?.price).toBe(88.25)
    expect(levels.find((l) => l.kind === 'target')?.price).toBe(140)
    expect(levels.find((l) => l.kind === 'entry')?.price).toBe(101.5)
    expect(levels.some((l) => l.price === 20)).toBe(false)
  })

  it('omits the SL line when the live stop is missing', () => {
    const levels = legLevels([
      {
        leg_id: 1,
        position: 'B',
        symbol: 'CE ATM',
        exchange: 'NFO',
        lots: 1,
        qty: 65,
        entry_order_id: 1,
        entry_status: 'complete',
        entry_avg: 50,
        exit_order_id: null,
        exit_kind: null,
        exit_avg: null,
        ltp: 51,
        mtm: 0,
        realized_pnl: 0,
        status: 'open',
        tick_source: 'quote',
        sl_pts: 20,
        target_pts: null,
        trail_x: 0,
        trail_y: 0,
        effective_sl: null,
        effective_target: null,
        trail_active: false,
        highest_price: 51,
        lowest_price: 50,
      },
    ])
    expect(levels.some((l) => l.kind === 'sl')).toBe(false)
    expect(levels.some((l) => l.kind === 'target')).toBe(false)
    expect(levels.find((l) => l.kind === 'entry')?.price).toBe(50)
  })

  it('does not plot a buy/sell marker for a waiting evaluation', () => {
    expect(
      signalMarker(
        event({ reason: 'Waiting for a fresh qualifying signal', direction: '' }, 'Waiting'),
        INTERVAL,
        false
      )
    ).toBeNull()
  })

  it('labels an unfilled confirmed CE evaluation as Signal BUY', () => {
    const marker = signalMarker(
      event({
        direction: 'CE',
        close: 24810,
        technical: { direction: 'CE', bar_at: '2026-09-28T09:20:00+05:30', data_ready: true },
      }),
      INTERVAL,
      false
    )
    expect(marker).toMatchObject({ kind: 'signal-buy', label: 'BUY', price: 24810 })
  })

  it('plots confirmed BUY and SELL signals even when later evaluations are waiting', () => {
    const markers = confirmedSignalMarkers(
      [
        event({ reason: 'Waiting for a fresh qualifying signal' }, 'Waiting'),
        event({
          direction: 'PE',
          technical: { direction: 'PE', bar_at: '2026-09-28T10:05:00+05:30', data_ready: true },
        }),
        event({
          direction: 'CE',
          technical: { direction: 'CE', bar_at: '2026-09-28T09:20:00+05:30', data_ready: true },
        }),
      ],
      INTERVAL
    )
    expect(markers.map((m) => m.label)).toEqual(['SELL', 'BUY'])
  })

  it('snaps a marker onto the nearest candle within one interval', () => {
    expect(snapToCandle(100, [0, 300, 600], 300)).toBe(0)
    expect(snapToCandle(280, [0, 300, 600], 300)).toBe(300)
    expect(snapToCandle(5000, [0, 300, 600], 300)).toBeNull()
  })

  it('zooms to the recent session instead of the full history', () => {
    expect(visibleLogicalRange(400, false)).toEqual({ from: 328, to: 403 })
    expect(visibleLogicalRange(20, true)).toEqual({ from: -1, to: 23 })
  })

  it('does not plot a signal marker once a fill exists', () => {
    expect(
      signalMarker(
        event({
          direction: 'CE',
          close: 24810,
          technical: { direction: 'CE', bar_at: '2026-09-28T09:20:00+05:30', data_ready: true },
        }),
        INTERVAL,
        true
      )
    ).toBeNull()
  })
})
