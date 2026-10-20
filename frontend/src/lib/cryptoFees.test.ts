import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  type ContractFees,
  fillFee,
  netPnl,
  openingVoucher,
  openPositionFees,
  positionFees,
  withProfile,
} from './cryptoFees'

/** The same vectors services/crypto_fees.py is tested against. */
const VECTORS = JSON.parse(
  readFileSync(join(process.cwd(), '..', 'test', 'crypto_fees', 'vectors.json'), 'utf8')
)

type Case = {
  name: string
  contract: ContractFees
  profile: Record<string, unknown>
  args: Record<string, unknown>
  expect: Record<string, number | boolean | null>
}

describe('cryptoFees matches the Python fee core', () => {
  for (const c of VECTORS.fill_fee as Case[]) {
    it(`fill fee: ${c.name}`, () => {
      const result = fillFee(c.contract, withProfile(c.profile), c.args as never)
      expect(result.fee).toBeCloseTo(c.expect.fee as number, 9)
      expect(result.gst).toBeCloseTo(c.expect.gst as number, 9)
      expect(result.total).toBeCloseTo(c.expect.total as number, 9)
      expect(result.waived).toBe(c.expect.waived)
      expect(result.capped).toBe(c.expect.capped)
    })
  }

  for (const c of VECTORS.open_position_fees as Case[]) {
    it(`open position: ${c.name}`, () => {
      const result = openPositionFees(c.contract, withProfile(c.profile), c.args as never)
      for (const [key, value] of Object.entries(c.expect)) {
        const actual = result[key as keyof typeof result]
        if (value === null) expect(actual).toBeNull()
        else expect(actual as number).toBeCloseTo(value as number, 9)
      }
    })
  }

  for (const c of VECTORS.net_pnl as { name: string; args: never; expect: number }[]) {
    it(`net P&L: ${c.name}`, () => {
      expect(netPnl(c.args)).toBeCloseTo(c.expect, 9)
    })
  }

  for (const c of VECTORS.opening_voucher as (Case & { expect: number })[]) {
    it(`voucher: ${c.name}`, () => {
      expect(openingVoucher(c.contract, withProfile(c.profile), c.args as never)).toBeCloseTo(
        c.expect,
        9
      )
    })
  }

  for (const c of VECTORS.diwali_examples as {
    name: string
    profile: Record<string, unknown>
    open: { notional: number; role: 'maker' | 'taker' }
    close: { notional: number; role: 'maker' | 'taker' }
    gross: number
    held_minutes: number
    expect: Record<string, number>
  }[]) {
    it(`Delta example: ${c.name}`, () => {
      const btc = { symbol: 'BTCUSD' }
      const profile = withProfile(c.profile)
      const opening = fillFee(btc, profile, c.open)
      const net = (p: ReturnType<typeof withProfile>) =>
        netPnl({
          gross: c.gross,
          fees_paid: opening.total,
          exit_fee_due: fillFee(btc, p, { ...c.close, closing: true, held_minutes: c.held_minutes })
            .total,
        })
      expect(net(withProfile({ gst_pct: profile.gst_pct, scalper_offer: false }))).toBeCloseTo(
        c.expect.no_offer_net,
        9
      )
      expect(net(withProfile({ gst_pct: profile.gst_pct }))).toBeCloseTo(c.expect.scalper_net, 9)
      expect(net(profile)).toBeCloseTo(c.expect.diwali_net, 9)
      expect(
        openingVoucher(btc, profile, { opening_fee: opening.fee, held_minutes: c.held_minutes })
      ).toBeCloseTo(c.expect.voucher, 9)
    })
  }
})

describe('positionFees', () => {
  it.each([
    undefined,
    'invalid',
    '2026-10-20T11:00:00Z',
  ])('does not invent a free-close window for an unknown or future entry time: %s', (opened_at) => {
    const view = positionFees(
      {
        symbol: 'BTCUSDFUT',
        quantity: 1,
        average_price: 60000,
        ltp: 60100,
        pnl: 0.1,
        lot_size: 0.001,
        opened_at,
      },
      withProfile({ diwali_offer: true }),
      {},
      Date.parse('2026-10-20T10:00:00Z')
    )
    expect(view.windowRemainingMinutes).toBeNull()
    expect(view.voucherWindowRemainingMinutes).toBeNull()
    expect(view.exitFeeNow).toBeGreaterThan(0)
    expect(view.voucherNow).toBe(0)
  })
  it('reports the Diwali voucher beside net cash, never inside it', () => {
    const now = Date.parse('2026-10-20T10:12:00Z')
    const view = positionFees(
      {
        symbol: 'BTCUSDFUT',
        quantity: 1000,
        average_price: 60000,
        mark_price: 60100,
        pnl: 100,
        lot_size: 0.001,
        opened_at: '2026-10-20T10:00:00Z',
      },
      withProfile({ diwali_offer: true }),
      {},
      now
    )
    expect(view.voucherNow).toBeCloseTo(30, 9)
    expect(view.voucherWindowRemainingMinutes).toBeCloseTo(18, 9)
    expect(view.net).toBeCloseTo(100 - 35.4, 9)
  })
})
