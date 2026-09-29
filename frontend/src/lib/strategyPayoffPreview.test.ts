import { describe, expect, it } from 'vitest'
import type { Strategy } from '@/types/strategy_module'
import { previewStrategyLegs, strategyPayoffPreview, strikeOffsetSteps } from './strategyPayoffPreview'

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: 29,
    name: 'Kotak Buy Call',
    strategy_kind: 'batch',
    direction: 'both',
    universe_tab: 'weekly_monthly',
    underlying: 'NIFTY',
    underlying_exchange: 'NSE_INDEX',
    strategy_type: 'intraday',
    entry_time: '09:20',
    exit_time: '15:20',
    product: 'MIS',
    pricetype: 'MARKET',
    overall_sl_mtm: 300,
    overall_target_mtm: null,
    lock_profit: null,
    trail_sl_to_entry: false,
    scheduler: null,
    live_enabled: false,
    webhook_locked: false,
    webhook_ip_allowlist: null,
    daily_loss_limit_inr: 2000,
    automation_state: 'disabled',
    automation_state_reason: null,
    automation_state_updated_at: null,
    status: 'stopped',
    current_run_id: null,
    created_at: '2026-09-29T00:00:00+00:00',
    updated_at: '2026-09-29T00:00:00+00:00',
    legs: [
      {
        id: 1,
        segment: 'options',
        position: 'B',
        lots: 1,
        option_type: 'CE',
        strike_mode: 'atm',
        atm_offset: 'ATM',
        expiry: 'weekly',
      },
    ],
    ...overrides,
  }
}

describe('strategy payoff preview', () => {
  it('maps ATM offsets onto current strike steps', () => {
    expect(strikeOffsetSteps('ATM', 'CE')).toBe(0)
    expect(strikeOffsetSteps('OTM1', 'CE')).toBe(1)
    expect(strikeOffsetSteps('ITM1', 'CE')).toBe(-1)
    expect(strikeOffsetSteps('OTM1', 'PE')).toBe(-1)
    expect(strikeOffsetSteps('ITM1', 'PE')).toBe(1)
  })

  it('plots a long call with finite samples and a rising right tail', () => {
    const preview = strategyPayoffPreview(strategy())
    expect(preview).not.toBeNull()
    expect(preview?.payoff.samples.length).toBeGreaterThan(20)
    const first = preview!.payoff.samples[0].expiry
    const last = preview!.payoff.samples.at(-1)!.expiry
    expect(last).toBeGreaterThan(first)
    expect(preview!.payoff.maxProfit).toBe(Infinity)
  })

  it('keeps a bull call spread as two distinct NIFTY strikes', () => {
    const legs = previewStrategyLegs(
      strategy({
        name: 'Kotak Bull Call Spread',
        legs: [
          {
            id: 1,
            segment: 'options',
            position: 'B',
            lots: 1,
            option_type: 'CE',
            strike_mode: 'atm',
            atm_offset: 'ATM',
          },
          {
            id: 2,
            segment: 'options',
            position: 'S',
            lots: 1,
            option_type: 'CE',
            strike_mode: 'atm',
            atm_offset: 'OTM1',
          },
        ],
      })
    )
    expect(legs.map((leg) => leg.strike)).toEqual([25000, 25050])
    expect(legs.map((leg) => leg.side)).toEqual(['BUY', 'SELL'])
  })

  it('does not invent a payoff for cash-only strategies', () => {
    expect(
      strategyPayoffPreview(
        strategy({
          strategy_kind: 'signal',
          legs: [{ id: 1, segment: 'cash', symbol: 'RELIANCE', exchange: 'NSE', side: 'long', qty: 1 }],
        })
      )
    ).toBeNull()
  })
})
